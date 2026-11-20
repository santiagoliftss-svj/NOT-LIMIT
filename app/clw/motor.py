"""El cerebro: captura la pantalla, lee el texto, encuentra las cajitas, pregunta a la IA y contesta."""

import base64
import ctypes
import difflib
import io
import json
import math
import os
import re
import sys
import threading
import time
import unicodedata

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageOps, ImageStat

from . import entrada

TAM_BASE = (1920, 1080)      # zona que se captura (se ajusta al zoom de Windows)
ARRIBA_BASE = 300            # cuanto se captura arriba del puntero
MAX_CAJAS = 160
MAX_CAMPOS = 40
LETRAS = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
MORADO = (200, 0, 200)

SISTEMA = """Eres el motor de un bot que contesta preguntas que aparecen en la pantalla del usuario.

Recibes:
1) Una captura de pantalla. Un circulo rojo marca donde esta el puntero del mouse. Los campos para escribir que se detectaron estan marcados con un recuadro morado y una etiqueta (C0, C1, ...).
2) Una lista de cajas de texto leidas con OCR: id numerico, centro (x,y) en pixeles de la captura y el texto. El OCR puede traer errores o simbolos raros (los iconos y los bordes salen como basura); guiate por la imagen.
3) Una lista de campos para escribir detectados: id (C0, C1, ...), centro (x,y) y tamano.

Reglas generales:
- Contesta solo la pregunta que esta bajo el puntero o la mas cercana a el, con todos sus espacios para responder. Ignora las demas preguntas de la pantalla.
- Si hay que calcular o razonar (matematicas, fisica, quimica, logica), resuelvelo primero en "pasos" de forma breve y luego da la respuesta. Si no hace falta, omite "pasos".
- Lee la pregunta completa con cuidado: palabras como NO, EXCEPTO, INCORRECTA, FALSA, MENOS o NUNCA cambian la respuesta.
- Antes de contestar, comprueba tu respuesta: en matematicas recalcula o sustituye el resultado; en las demas, revisa que cumpla TODO lo que pide la pregunta.
- Sirve para cualquier materia y cualquier tipo de pregunta: opcion multiple, verdadero o falso, si o no, completar espacios, respuesta corta, abiertas, problemas y preguntas con imagenes.
- Si la pregunta trae imagen, dibujo, diagrama, mapa, tabla o grafica, la respuesta casi siempre depende de ella: leela con cuidado en la captura (titulo, ejes, escala, unidades, etiquetas, leyenda, colores y los valores de barras, puntos o lineas) antes de contestar. Si la grafica no trae numeros, estimalos con la cuadricula o la escala. Si una parte se ve cortada, contesta con lo que si se ve.

Si es de OPCION MULTIPLE (circulos, casillas o botones con opciones):
{"tipo": "opcion", "pasos": "...", "respuesta": "<texto exacto de la opcion correcta>", "ids": [<id>]}
- Primero decide la respuesta correcta y escribela en "respuesta" tal como aparece en la pantalla.
- Luego busca en la lista la caja de texto de ESA opcion y pon su id en "ids". Revisa dos veces que el id que pones tenga el mismo texto que tu respuesta (es facil equivocarse por uno).
- Las opciones son las que tienen circulo, casilla o boton al lado. Los textos que estan dentro de imagenes (mapas, fotos, diagramas, graficas) NO son opciones aunque digan lo mismo.
- Nunca pongas el id de la pregunta.
- Normalmente es una sola. Solo si la pregunta pide marcar varias (casillas), pon todas las correctas en "ids" y en "respuesta" separalas con " | ".
- Verdadero/Falso y Si/No tambien son de opcion: marca la correcta.
- Si una opcion correcta no tiene caja de texto (por ejemplo es una imagen o un dibujo), en su lugar pon {"x": <x>, "y": <y>} con su centro. Igual si la pregunta pide hacer clic en una parte de una imagen (un punto de una grafica, un lugar en un mapa, una parte de un dibujo): pon el centro exacto de esa parte.
- Si los datos de la pregunta tienen un error y ninguna opcion es exacta, elige la mas cercana a la respuesta real.

Si es ABIERTA (hay que escribir en uno o varios campos):
{"tipo": "abierta", "pasos": "...", "respuestas": [{"campo": "C0", "texto": "..."}, {"campo": "C1", "texto": "..."}]}
- Una entrada por cada campo de ESA pregunta, en orden: de arriba a abajo y de izquierda a derecha.
- "campo" es el id del campo marcado (C0, C1, ...). Si el campo no se marco pero si se leyo el texto gris de adentro (por ejemplo "Escriba su respuesta"), usa el id numerico de esa caja de texto. Si no hay ninguno, cambia "campo" por "x" y "y" con el centro del espacio para escribir.
- El texto va tal como se teclearia: texto plano, sin markdown, sin saltos de linea y sin LaTeX.
- El largo depende de lo que pide la pregunta: si pide un dato, nombre, fecha, numero o resultado, contesta corto y directo. Si pide explicar, describir, comparar o argumentar, escribe un parrafo de 3 a 6 oraciones en espanol natural.
- Si es de completar (espacios en blanco dentro de un texto), cada espacio es un campo: pon solo la palabra o el dato que va en cada uno.
- Si piden interpretar una grafica o imagen, apoya la respuesta en los datos que leiste en ella (valores, tendencia, maximo o minimo).
- Si piden dibujar o trazar algo, no puedes dibujar en la pantalla: si hay campo para escribir, describe en texto lo que se pide (forma, puntos clave, ejes); si no hay campo, responde {"tipo": "ninguna"}.
- En matematicas escribe solo el valor final: fracciones simplificadas con / (ej. 5/13), negativos con -, decimales con punto y redondeados como pida la pregunta, raices con el simbolo √ (ej. √3/2). Si junto al campo ya aparece la unidad (por ejemplo "m"), escribe solo el numero.

Si no hay nada que contestar, responde {"tipo": "ninguna"}.
Responde SOLO con el JSON en una sola linea, nada mas."""


# ================================================================ pantalla

def _user32():
    try:
        return ctypes.windll.user32
    except Exception:
        return None


def factor_zoom():
    u = _user32()
    try:
        return max(1.0, u.GetDpiForSystem() / 96)
    except Exception:
        return 1.0


def pantalla_virtual():
    u = _user32()
    try:
        x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        w, h = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return x, y, w, h
    except Exception:
        pass
    im = ImageGrab.grab()
    return 0, 0, im.width, im.height


def calcular_zona(px, py, virtual, zoom):
    vx, vy, vw, vh = virtual
    w = min(int(TAM_BASE[0] * zoom), vw)
    h = min(int(TAM_BASE[1] * zoom), vh)
    left = int(min(max(px - w // 2, vx), vx + vw - w))
    top = int(min(max(py - int(ARRIBA_BASE * zoom), vy), vy + vh - h))
    return left, top, w, h


def capturar(px, py):
    left, top, w, h = calcular_zona(px, py, pantalla_virtual(), factor_zoom())
    img = ImageGrab.grab(bbox=(left, top, left + w, top + h), all_screens=True).convert("RGB")
    return img, left, top


def capturar_zona(left, top, w, h):
    """Foto de un rectangulo de la pantalla (pixeles), para ver como quedo despues de actuar."""
    left, top, w, h = int(left), int(top), int(w), int(h)
    return ImageGrab.grab(bbox=(left, top, left + w, top + h), all_screens=True).convert("RGB")


if sys.platform == "darwin":             # Mac: screencapture, en pixeles reales (Retina)
    from .mac import captura as _captura_mac

    def factor_zoom():  # noqa: F811
        return _captura_mac.factor_zoom()

    def pantalla_virtual():  # noqa: F811
        return _captura_mac.pantalla_virtual()

    def capturar(px, py):  # noqa: F811
        return _captura_mac.capturar(px, py, TAM_BASE, ARRIBA_BASE)

    def capturar_zona(left, top, w, h):  # noqa: F811
        return _captura_mac.capturar_zona(left, top, w, h)


# ================================================================ OCR (texto en pantalla)

def _unir(grupo):
    x0 = min(p["x"] for p in grupo)
    y0 = min(p["y"] for p in grupo)
    x1 = max(p["x"] + p["w"] for p in grupo)
    y1 = max(p["y"] + p["h"] for p in grupo)
    return {"texto": " ".join(p["t"] for p in grupo), "caja": (x0, y0, x1, y1),
            "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
            "palabras": [(p["t"], p["x"], p["y"], p["w"], p["h"]) for p in grupo]}


def _se_enciman(a, b):
    ax0, ay0, ax1, ay1 = a["caja"]
    bx0, by0, bx1, by1 = b["caja"]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    menor = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0)) or 1
    return ix * iy / menor > 0.3


def _cajas_de(d, escala, zoom):
    lineas = {}
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        if not t:
            continue
        try:
            if float(d["conf"][i]) < 0:
                continue
        except (TypeError, ValueError):
            continue
        clave = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        lineas.setdefault(clave, []).append({
            "t": t, "x": d["left"][i] / escala, "y": d["top"][i] / escala,
            "w": d["width"][i] / escala, "h": d["height"][i] / escala,
        })
    cajas = []
    for palabras in lineas.values():
        palabras.sort(key=lambda p: p["x"])
        alto = sorted(p["h"] for p in palabras)[len(palabras) // 2]
        grupo = [palabras[0]]
        for p in palabras[1:]:
            ant = grupo[-1]
            if p["x"] - (ant["x"] + ant["w"]) > max(25 * zoom, alto * 2.5):  # hueco grande = otra columna
                cajas.append(_unir(grupo))
                grupo = [p]
            else:
                grupo.append(p)
        cajas.append(_unir(grupo))
    return [c for c in cajas if LETRAS.search(c["texto"])]


def detectar_cajas(img, px, py, zoom, ocr):
    """Lee el texto y lo junta en cajas (una por opcion, aunque esten en columnas).
    Dos lecturas en paralelo con modos distintos para que no se escape nada."""
    gris = ImageOps.grayscale(img)
    # zonas oscuras se invierten (el OCR lee mejor negro sobre blanco), zona por zona:
    # asi sirve aunque la pantalla tenga partes claras y oscuras al mismo tiempo
    fondo = fondo_por_zonas(gris, max(24, int(40 * zoom)), suavizar=True)
    oscuras = fondo.point(lambda v: 255 if v < 110 else 0)
    if oscuras.getbbox():
        # (una caja blanca dentro de un fondo oscuro, como la de escribir en Kahoot o en un juego, NO se invierte:
        # se ve con zonas mas chicas, si no su texto queda mitad volteado y no se lee)
        claras = fondo_por_zonas(gris, max(12, int(16 * zoom))).point(lambda v: 255 if v >= 150 else 0)
        oscuras = ImageChops.subtract(oscuras, claras)
        gris = Image.composite(ImageOps.invert(gris), gris, oscuras.filter(ImageFilter.MaxFilter(3)))
    gris = ImageOps.autocontrast(gris, cutoff=1)
    escala = 2 if zoom < 1.5 else 1
    if escala != 1:
        gris = gris.resize((gris.width * escala, gris.height * escala), Image.LANCZOS)

    resultados = {}

    def pasada(psm):
        try:
            resultados[psm] = ocr.datos(gris, psm)
        except Exception as e:
            resultados[psm] = e

    hilos = [threading.Thread(target=pasada, args=(psm,), daemon=True) for psm in (11, 3)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    buenos = [resultados[p] for p in (11, 3) if isinstance(resultados.get(p), dict)]
    if not buenos:
        raise resultados.get(11) or RuntimeError("el OCR no respondio")

    cajas = []
    for d in buenos:
        for c in _cajas_de(d, escala, zoom):
            if not any(_se_enciman(c, otra) for otra in cajas):
                cajas.append(c)

    if len(cajas) > MAX_CAJAS:
        cajas.sort(key=lambda c: (c["cx"] - px) ** 2 + (c["cy"] - py) ** 2)
        cajas = cajas[:MAX_CAJAS]
    cajas.sort(key=lambda c: (round(c["caja"][1] / 12), c["caja"][0]))
    return cajas


# ================================================================ cajitas para escribir

def fondo_por_zonas(gris, lado, suavizar=False):
    """Color de fondo de cada zona (el tono que mas se repite), del tamano de la imagen.
    suavizar: cada zona toma el valor mediano de sus vecinas (para que letras grandes no cambien el fondo)."""
    W, H = gris.size
    cw, ch = (W + lado - 1) // lado, (H + lado - 1) // lado
    valores = []
    for j in range(ch):
        for i in range(cw):
            h = gris.crop((i * lado, j * lado, min(W, (i + 1) * lado), min(H, (j + 1) * lado))).histogram()
            valores.append(max(range(256), key=h.__getitem__))
    mapa = Image.new("L", (cw, ch))
    mapa.putdata(valores)
    if suavizar and cw >= 3 and ch >= 3:
        mapa = mapa.filter(ImageFilter.MedianFilter(3))
    return mapa.resize((cw * lado, ch * lado), Image.NEAREST).crop((0, 0, W, H))

def rectangulos(img, zoom=1.0, relajado=False):
    """Busca rectangulos huecos (cajas de respuesta) en la imagen. Devuelve [(x0, y0, x1, y1), ...].
    Compara cada pixel con su alrededor (no con un solo fondo), asi funciona aunque en la pantalla
    haya partes claras y oscuras al mismo tiempo."""
    gris = ImageOps.grayscale(img)
    umbral = 16 if relajado else 26
    mascara = ImageChops.difference(gris, fondo_por_zonas(gris, max(24, int(40 * zoom)))).point(
        lambda v: 255 if v > umbral else 0)
    rects = _rects_de_mascara(mascara, zoom, relajado)
    # Segunda pasada con las ORILLAS (donde cambia el color de un pixel a otro): una caja blanca sobre un fondo de
    # color (juegos, Kahoot, tarjetas moradas) se ve completa aunque el fondo de su zona sea el color de afuera.
    orillas = ImageChops.subtract(gris.filter(ImageFilter.MaxFilter(3)), gris.filter(ImageFilter.MinFilter(3))).point(
        lambda v: 255 if v > umbral + 4 else 0)
    # (en esta pasada la caja tiene que estar casi vacia por dentro: en texto claro sobre fondo oscuro, como una
    # consola, las letras forman "cajas" llenas de orillas)
    return _sin_repetidos(rects, _rects_de_mascara(orillas, zoom, relajado, solo_anchos=True, max_tinta=0.25))


def _hueca(filas, W, izq, der, t1, b0):
    """True si adentro de una cajita angosta no hay nada (o solo el cursor que parpadea, una rayita vertical).
    Una letra (8, B, D, 0...) tiene trazos adentro."""
    x0, x1, y0, y1 = izq + 2, der - 1, t1 + 2, b0 - 1
    if x1 <= x0 or y1 <= y0:
        return True
    renglones = y1 - y0
    cols = [sum(1 for y in range(y0, y1) if filas[y * W + x] == 255) for x in range(x0, x1)]
    llenas = [k for k, n in enumerate(cols) if n >= 0.6 * renglones]
    if len(llenas) > 2 or (len(llenas) == 2 and llenas[1] - llenas[0] > 1):
        return False
    resto = sum(n for k, n in enumerate(cols) if k not in llenas)
    return resto <= 0.06 * renglones * max(1, len(cols) - len(llenas))


def _rects_de_mascara(mascara, zoom, relajado, solo_anchos=False, max_tinta=0.5):
    W, H = mascara.size
    filas = mascara.tobytes()
    columnas = mascara.transpose(Image.Transpose.TRANSPOSE).tobytes()

    def tinta_col(c, y0, y1):
        if c < 0 or c >= W or y1 <= y0:
            return 0.0
        seg = columnas[c * H + max(0, y0): c * H + min(H, y1)]
        return seg.count(255) / len(seg) if seg else 0.0

    patron = re.compile(rb"\xff{%d,}" % (int(7 * zoom) + 1))
    por_ext = {}
    for y in range(H):
        for m in patron.finditer(filas[y * W:(y + 1) * W]):
            por_ext.setdefault((m.start(), m.end() - 1), []).append(y)
    bandas = {}
    for ext, ys in por_ext.items():
        lista, ini, ant = [], ys[0], ys[0]
        for y in ys[1:]:
            if y == ant + 1:
                ant = y
                continue
            lista.append((ini, ant))
            ini = ant = y
        lista.append((ini, ant))
        bandas[ext] = [b for b in lista if b[1] - b[0] <= 4 * zoom]

    min_h = int((14 if relajado else 18) * zoom)
    max_h = int(320 * zoom)
    min_w = int(8 * zoom)
    rects = []
    for (x0, x1), lista in bandas.items():
        ancho_banda = x1 - x0 + 1
        if ancho_banda < min_w or ancho_banda > 0.95 * W:
            continue
        abajo = []
        for d0 in range(-2, 3):
            for d1 in range(-2, 3):
                abajo.extend(bandas.get((x0 + d0, x1 + d1), ()))
        for (t0, t1) in lista:
            for (b0, b1) in abajo:
                h = b1 - t0 + 1
                if b0 <= t1 + 3 or h < min_h or h > max_h:
                    continue
                rmax = int(min(12 * zoom, (b0 - t1) / 3, ancho_banda / 3)) + 1
                ys, ye = t1 + 1 + rmax, b0 - rmax
                if ye - ys < 3:
                    continue
                izq = max(range(x0 - rmax - 1, x0 + 2), key=lambda c: (tinta_col(c, ys, ye), -abs(c - x0)))
                der = max(range(x1 - 1, x1 + rmax + 2), key=lambda c: (tinta_col(c, ys, ye), -abs(c - x1)))
                if tinta_col(izq, ys, ye) < 0.9 or tinta_col(der, ys, ye) < 0.9:
                    continue
                ancho = der - izq + 1
                if ancho < min_w or ancho_banda < 0.6 * ancho:
                    continue
                radio = max(x0 - izq, der - x1, 0)
                if (b0 - t1 - 2 * radio) < 0.55 * (b0 - t1) or tinta_col(izq, t1 + 1 + radio, b0 - radio) < 0.9:
                    continue   # lados curvos: es una letra (o, 0, D), no una caja
                if ancho < 28 * zoom and (solo_anchos or h < 1.3 * ancho or h < 17 * zoom):
                    continue   # cuadrito chico: casilla o letra, no un campo para escribir
                    # (las cajitas angostas y altas SI son campos: las casillas vacias de ALEKS miden 10 x 22)
                if ancho < 28 * zoom and not _hueca(filas, W, izq, der, t1, b0):
                    continue   # cajita angosta con trazos adentro: es una letra (8, B, D), no una casilla vacia
                tinta = total = 0
                for y in range(t1 + 2, b0 - 1):
                    seg = filas[y * W + izq + 3: y * W + der - 2]
                    tinta += seg.count(255)
                    total += len(seg)
                if total and tinta / total > max_tinta:
                    continue
                rects.append((izq, t0, der, b1))
    return rects


def _sin_repetidos(rects, extra=()):
    """Quita los rectangulos que son casi el mismo que otro mas grande (la misma caja vista dos veces). Los de
    'extra' (segunda pasada) solo entran si no son una caja que ya estaba."""
    def por_area(lista):
        return sorted(lista, key=lambda r: -(r[2] - r[0]) * (r[3] - r[1]))
    finales = []
    for r in por_area(rects) + por_area(extra):
        repetido = False
        for f in finales:
            ix = max(0, min(r[2], f[2]) - max(r[0], f[0]))
            iy = max(0, min(r[3], f[3]) - max(r[1], f[1]))
            union = (r[2] - r[0]) * (r[3] - r[1]) + (f[2] - f[0]) * (f[3] - f[1]) - ix * iy
            if union and ix * iy / union > 0.6:
                repetido = True
                break
        if not repetido:
            finales.append(r)
    return finales


def subrayados(img, zoom=1.0):
    """Campos que son solo una raya abajo (el 'Tu respuesta' de Google Forms, un ______ para completar).
    Devuelve [(x0, y0, x1, y1)]: el espacio para escribir, justo arriba de la raya.
    Descarta: orillas de cajas o tablas, texto subrayado (enlaces), separadores y bordes entre dos colores."""
    gris = ImageOps.grayscale(img)
    W, H = gris.size
    if W < 20 or H < 20:
        return []
    mascara = ImageChops.difference(gris, fondo_por_zonas(gris, max(24, int(40 * zoom)))).point(
        lambda v: 255 if v > 14 else 0)
    filas = mascara.tobytes()
    columnas = mascara.transpose(Image.Transpose.TRANSPOSE).tobytes()
    pix = gris.tobytes()
    largo_min = int(46 * zoom)
    grueso_max = max(3, int(round(3 * zoom)))
    holgura = max(3, int(3 * zoom))
    patron = re.compile(rb"\xff{%d,}" % largo_min)

    # 1) rayas: corridas horizontales que siguen en renglones seguidos con casi el mismo largo
    abiertas, rayas = [], []
    for y in range(H):
        nuevas = []
        for m in patron.finditer(filas[y * W:(y + 1) * W]):
            a, b = m.start(), m.end()
            for g in abiertas:
                if g[3] == y - 1 and abs(g[0] - a) <= holgura and abs(g[1] - b) <= holgura:
                    g[0], g[1], g[3] = min(g[0], a), max(g[1], b), y
                    abiertas.remove(g)
                    nuevas.append(g)
                    break
            else:
                nuevas.append([a, b, y, y])
        rayas.extend(abiertas)
        abiertas = nuevas
        if len(rayas) > 600:
            break                     # pantalla con demasiadas rayas (un patron): no adivinar
    rayas.extend(abiertas)

    def valores(y, a, b):
        return pix[y * W + a: y * W + b]

    def mediana(seg):
        return sorted(seg)[len(seg) // 2]

    def parejo(seg, v):
        return sum(1 for p in seg if abs(p - v) <= 16) / len(seg)

    def tinta(c, y0, y1):
        if c < 0 or c >= W:
            return 0.0
        y0, y1 = max(0, y0), min(H, y1)
        seg = columnas[c * H + y0: c * H + y1]
        return seg.count(255) / len(seg) if seg else 0.0

    sep = int(2 * zoom) + 1
    alto = int(24 * zoom)
    lado = int(26 * zoom)
    out = []
    for a, b, y0, y1 in rayas:
        ancho = b - a
        if y1 - y0 + 1 > grueso_max or ancho > 0.7 * W:
            continue                  # barra gruesa o separador de lado a lado
        ya, yb = y0 - sep, y1 + sep
        if ya < int(10 * zoom) or yb >= H:
            continue
        linea, arriba, abajo = valores((y0 + y1) // 2, a, b), valores(ya, a, b), valores(yb, a, b)
        va, vb, vl = mediana(arriba), mediana(abajo), mediana(linea)
        if abs(va - vb) > 18 or abs(vl - va) < 14 or abs(vl - vb) < 14:
            continue                  # borde entre dos colores, no una raya
        if parejo(arriba, va) < 0.85 or parejo(abajo, vb) < 0.85:
            continue                  # algo pegado a la raya (letras con colita): texto subrayado
        paso = max(1, int(zoom))
        cols = range(a, b, paso)
        marcadas = [c for c in cols if tinta(c, y0 - int(16 * zoom), y0 - int(2 * zoom)) > 0]
        cubre = len(marcadas) / len(cols)
        tramo = (marcadas[-1] - marcadas[0] + 1) / ancho if marcadas else 0.0
        if cubre > 0.6 or (tramo >= 0.75 and cubre >= 0.35):
            continue                  # renglon de texto subrayado (un enlace), no un espacio para escribir
        lados = {}
        for nombre, rango in (("abajo", (y1 + 1, y1 + 1 + lado)), ("arriba", (y0 - lado, y0))):
            izq = max(tinta(c, *rango) for c in range(a - int(14 * zoom), a + int(4 * zoom) + 1))
            der = max(tinta(c, *rango) for c in range(b - 1 - int(4 * zoom), b + int(14 * zoom)))
            lados[nombre] = (izq, der)
        if any(min(v) >= 0.55 or max(v) >= 0.8 for v in lados.values()):
            continue                  # orilla de una caja o de una tabla (eso lo ve rectangulos)
        out.append((a, max(0, y0 - alto), b, y1 + 1))

    out.sort(key=lambda r: (r[3], r[0]))
    finales = []
    for r in out:
        if not any(abs(r[3] - f[3]) < 6 * zoom and r[0] < f[2] and f[0] < r[2] for f in finales):
            finales.append(r)
    return finales[:16]


# ================================================================ planos cartesianos (MyLab, GeoGebra, Desmos...)
# Todo se busca como lineas horizontales en un "buffer" de 1 byte por pixel; para el eje y se usa la imagen
# transpuesta (asi el mismo codigo sirve para los dos ejes).

_REDONDOS = (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000)


def _lineas_largas(buf, W, H, zoom):
    """Lineas oscuras largas (posibles ejes): [(desde, hasta, fila0, fila1)]. Se ven TODOS los tramos de cada
    renglon (no solo el mas largo): asi un eje no se pierde junto a una zona oscura grande (el escritorio)."""
    patron = re.compile(rb"\x01{%d,}" % max(20, min(int(0.35 * W), max(int(100 * zoom), int(0.2 * W)))))
    abiertas, cerradas = [], []
    for k in range(H):
        siguen = []
        for m in patron.finditer(buf, k * W, (k + 1) * W):
            d, h = m.start() - k * W, m.end() - k * W
            for l in abiertas:
                if l[3] == k - 1 and abs(d - l[0]) < 12 * zoom:
                    l[0], l[1], l[3] = min(l[0], d), max(l[1], h), k
                    break
            else:
                siguen.append([d, h, k, k])
        cerradas += [l for l in abiertas if l[3] < k]
        abiertas = [l for l in abiertas if l[3] == k] + siguen
    cerradas += abiertas
    grueso = max(4, int(4 * zoom))
    return sorted((tuple(l) for l in cerradas if l[3] - l[2] <= grueso), key=lambda l: (l[2], l[0]))


def _agrupar(cols, zoom):
    centros, grupo = [], []
    for c in list(cols) + [None]:
        if c is not None and grupo and c - grupo[-1] <= 1:
            grupo.append(c)
            continue
        if grupo and len(grupo) <= max(3, int(3 * zoom)):
            centros.append(sum(grupo) / len(grupo))
        grupo = [c] if c is not None else []
    return centros


def _por_columna(img, x0, y0, x1, y1):
    """Promedio (0..255) de cada columna de un pedazo de una imagen L (en C, con PIL: rapido aunque sea grande)."""
    if x1 - x0 < 1 or y1 - y0 < 1:
        return b""
    return img.crop((x0, y0, x1, y1)).resize((x1 - x0, 1), Image.BOX).tobytes()


def _rayitas(osc, W, H, linea, zoom):
    """Rayitas (marcas) que cruzan el eje: trazos cortos y continuos hacia afuera de la linea.
    osc: imagen L con 255 donde hay tinta oscura."""
    desde, hasta, a, b = linea
    largo = max(3, int(3 * zoom))
    arriba = _por_columna(osc, desde, a - largo, hasta, a) if a - largo >= 0 else b""
    abajo = _por_columna(osc, desde, b + 1, hasta, b + 1 + largo) if b + largo < H else b""
    cols = [desde + k for k in range(hasta - desde)
            if (arriba and arriba[k] >= 250) or (abajo and abajo[k] >= 250)]
    return _agrupar(cols, zoom)


def _cuadricula(rej, W, H, linea, zoom):
    """Si el eje no tiene rayitas (como en Desmos): donde lo cruzan las lineas de la cuadricula.
    rej: imagen L con 255 donde el gris es < 236 (cualquier linea, aunque sea clarita)."""
    desde, hasta, a, b = linea
    alto = int(40 * zoom)
    tramos = [(max(0, a - alto), max(0, a - 2)), (min(H, b + 3), min(H, b + alto))]
    filas = sum(max(0, t1 - t0) for t0, t1 in tramos)
    if filas < 10:
        return []
    cuenta = [0.0] * (hasta - desde)
    for t0, t1 in tramos:
        if t1 - t0 < 1:
            continue
        prom = _por_columna(rej, desde, t0, hasta, t1)
        for k, v in enumerate(prom):
            cuenta[k] += v / 255.0 * (t1 - t0)
    return _agrupar([desde + k for k, n in enumerate(cuenta) if n >= 0.7 * filas], zoom)


def _borrar_rejilla(px, W, H, rejilla, zoom):
    """Borra las lineas de la cuadricula que pasan por encima de los numeros (columnas y renglones de las rayitas):
    se busca el trazo exacto de la linea (1 pixel, o 2 en pantallas Retina) y se borra solo donde va sola (a los
    lados no hay tinta). Asi el trazo de un numero que la cruza se queda."""
    cols, filas = rejilla
    ancho = 2 if zoom >= 1.5 else 1

    def osc(x, y):
        return 0 <= x < W and 0 <= y < H and px[x, y] < 170

    def borrar(g, n, largo, punto):
        # punto(k, t): (x, y) de la posicion t a lo largo de la linea k (columna o renglon)
        g = int(round(g))
        mejor = None
        for k0 in range(g - 2, g + 2):
            ks = list(range(k0, k0 + ancho))
            if ks[0] < 0 or ks[-1] >= n:
                continue
            sola = [t for t in range(largo)
                    if all(osc(*punto(k, t)) for k in ks)
                    and not osc(*punto(ks[0] - 1, t)) and not osc(*punto(ks[-1] + 1, t))]
            if mejor is None or len(sola) > len(mejor[1]):
                mejor = (ks, sola)
        if not mejor or len(mejor[1]) < 0.2 * largo:
            return                       # aqui no hay linea de cuadricula
        for t in mejor[1]:
            for k in mejor[0]:
                x, y = punto(k, t)
                px[x, y] = 255
    for g in cols:
        borrar(g, W, H, lambda k, t: (k, t))
    for g in filas:
        borrar(g, H, W, lambda k, t: (t, k))


def _limpiar_numeros(img, zoom, rejilla=None):
    """Sin los puntitos de la cuadricula ni lineas largas, y mas grande (asi el OCR lee bien los numeros)."""
    gris = ImageOps.grayscale(img)
    W, H = gris.size
    px = gris.load()
    if rejilla:
        _borrar_rejilla(px, W, H, rejilla, zoom)
    negro = [[px[x, y] < 140 for x in range(W)] for y in range(H)]
    visto = [[False] * W for _ in range(H)]
    chico = max(2, int(2.5 * zoom))
    delgado = max(3, int(4 * zoom))
    comps = []
    for y in range(H):
        for x in range(W):
            if not negro[y][x] or visto[y][x]:
                continue
            pila, comp = [(x, y)], []
            visto[y][x] = True
            while pila:
                cx, cy = pila.pop()
                comp.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < W and 0 <= ny < H and negro[ny][nx] and not visto[ny][nx]:
                        visto[ny][nx] = True
                        pila.append((nx, ny))
            xs, ys = [c[0] for c in comp], [c[1] for c in comp]
            comps.append((comp, min(xs), min(ys), max(xs), max(ys)))
    letras = [c for c in comps if c[4] - c[2] >= 6 * zoom and c[3] - c[1] <= 30 * zoom]

    def es_punto_decimal(c):
        # un punto pegado abajo entre dos numeros (1.5) NO es de la cuadricula
        _, x0, y0, x1, y1 = c
        izq = any(0 <= x0 - l[3] <= 4 * zoom and abs(l[4] - y1) <= 2.5 * zoom for l in letras)
        der = any(0 <= l[1] - x1 <= 4 * zoom and abs(l[4] - y1) <= 2.5 * zoom for l in letras)
        return izq and der

    borrar = []
    for c in comps:
        comp, x0, y0, x1, y1 = c
        w, h = x1 - x0, y1 - y0
        if (w < chico and h < chico and not es_punto_decimal(c)) or (w > 46 * zoom and h <= delgado) \
                or (h > 30 * zoom and w <= delgado):
            borrar.extend(comp)                          # puntito de la cuadricula, o una linea larga
    borrados = set(borrar)
    for x, y in borrar:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if 0 <= x + dx < W and 0 <= y + dy < H:
                    px[x + dx, y + dy] = 255
    # las lineas claras de la cuadricula (Desmos) tambien estorban: todo lo claro se vuelve blanco
    gris = gris.point(lambda v: 255 if v > 200 else v)
    quedan = [c[1:] for c in comps if c[0][0] not in borrados]
    return gris, quedan


def _agrandar(gris, zoom):
    f = 3.0 / zoom
    out = gris.resize((max(1, int(gris.width * f)), max(1, int(gris.height * f))), Image.LANCZOS)
    return ImageOps.expand(out, border=20, fill=255), f


def _numeros_de(img, zoom, ocr, rejilla=None):
    """[(valor, cx, cy)] de los numeros en la imagen (solo digitos, punto y signo menos). Se lee de dos formas
    (texto suelto y en bloque) y se juntan: la recta robusta despues descarta lo mal leido."""
    limpia, f = _agrandar(_limpiar_numeros(img, zoom, rejilla)[0], zoom)
    out = []
    for psm in (11, 6):
        try:
            d = ocr.datos(limpia, psm=psm, solo="-0123456789.")
        except Exception:
            continue
        for i, t in enumerate(d.get("text", [])):
            t = (t or "").strip().strip(".")
            if not re.fullmatch(r"-?\d{1,4}(?:\.\d{1,3})?", t):
                continue
            cx = (d["left"][i] + d["width"][i] / 2 - 20) / f
            cy = (d["top"][i] + d["height"][i] / 2 - 20) / f
            out.append((float(t), cx, cy))
    return out


def _numeros_por_rayita(img, zoom, ocr, marcas, paso, horizontal, rejilla=None):
    """Cuando los numeros vienen muy pegados ('-20-15-10'): se junta lo que hay alrededor de cada rayita y cada
    numero se pone en su propio renglon, con mucho espacio, para leerlos de una vez.
    Devuelve [(valor, posicion_de_la_rayita)] (en la imagen)."""
    gris, letras = _limpiar_numeros(img, zoom, rejilla)
    grupos = {}
    for x0, y0, x1, y1 in letras:
        if x1 - x0 <= max(3, 4 * zoom) and y1 - y0 >= 20 * zoom:
            continue                                     # pedazo de una linea (el otro eje), no un numero
        centro = (x0 + x1) / 2 if horizontal else (y0 + y1) / 2
        m = min(marcas, key=lambda t: abs(t - centro)) if marcas else None
        if m is None or abs(m - centro) > 0.5 * paso:
            continue
        g = grupos.setdefault(m, [x0, y0, x1, y1])
        g[0], g[1], g[2], g[3] = min(g[0], x0), min(g[1], y0), max(g[2], x1), max(g[3], y1)
    if not grupos:
        return []
    hueco = int(20 * zoom)
    trozos = [(m, gris.crop((g[0] - 1, g[1] - 1, g[2] + 2, g[3] + 2))) for m, g in sorted(grupos.items())]
    ancho = max(t.width for _, t in trozos) + 2 * hueco
    alto = sum(t.height for _, t in trozos) + hueco * (len(trozos) + 1)
    hoja = Image.new("L", (ancho, alto), 255)
    lugares, y = [], hueco
    for m, t in trozos:
        hoja.paste(t, (hueco, y))
        lugares.append((y, y + t.height, m))
        y += t.height + hueco
    grande, f = _agrandar(hoja, zoom)
    out = []
    for psm in (6, 4):
        try:
            d = ocr.datos(grande, psm=psm, solo="-0123456789.")
        except Exception:
            continue
        for i, t in enumerate(d.get("text", [])):
            t = (t or "").strip().strip(".")
            if not re.fullmatch(r"-?\d{1,4}(?:\.\d{1,3})?", t):
                continue
            cy = (d["top"][i] + d["height"][i] / 2 - 20) / f
            for y0, y1, m in lugares:
                if y0 - 4 <= cy <= y1 + 4:
                    out.append((float(t), m))
                    break
    return out


def _quitar_lineas(px, W, H, umbral, zoom=1.0):
    """Borra las lineas largas de una banda de numeros (el otro eje, la cuadricula, punteada o no) sin borrar los
    numeros: solo se blanquean los pixeles de la linea que tienen su mismo tono (los numeros casi siempre son mas
    oscuros que la cuadricula) o que van solos (sin tinta a los lados)."""
    def tinta(x, y):
        return 0 <= x < W and 0 <= y < H and px[x, y] < umbral
    salto = max(6, int(6 * zoom))
    for vertical in (True, False):
        largo, n = (H, W) if vertical else (W, H)
        for k in range(n):
            pts = [(k, t) if vertical else (t, k) for t in range(largo)]
            con = [p for p in pts if tinta(*p)]
            if len(con) < 0.25 * largo:
                continue
            # cuanto cubre (los huecos chicos de una linea punteada cuentan como linea)
            cubre, ultimo = 0, None
            for t in range(largo):
                if tinta(*pts[t]):
                    cubre += 1 if ultimo is None or t - ultimo > salto else t - ultimo
                    ultimo = t
            if cubre < 0.6 * largo:
                continue
            tono = sorted(px[p] for p in con)[len(con) // 2]
            for x, y in con:
                lados = (tinta(x - 1, y) or tinta(x + 1, y)) if vertical else (tinta(x, y - 1) or tinta(x, y + 1))
                if px[x, y] >= tono - 25 or not lados:
                    px[x, y] = 255


def _numeros_por_ventana(img, zoom, ocr, marcas, paso, horizontal, umbral=170):
    """Otra forma de leer los numeros de un eje, sin destruir los numeros chiquitos (11 px, de colores, grises):
    se sube el contraste, se quitan las lineas, y lo escrito junto a cada rayita va en su propio renglon (con mucho
    espacio) para leerlo todo de una vez. Devuelve [(valor, posicion_de_la_rayita)] en la imagen."""
    g = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)
    W, H = g.size
    if W < 6 or H < 6 or not marcas:
        return []
    px = g.load()
    _quitar_lineas(px, W, H, umbral, zoom)
    # (todo en bytearrays planos y no en listas de listas: casi no se crean objetos)
    tinta = bytearray(g.point(lambda v: 1 if v < umbral else 0).tobytes())
    grupos = {}
    for i0 in range(W * H):
        if not tinta[i0]:
            continue
        tinta[i0] = 0
        pila = [i0]
        x0 = x1 = i0 % W
        y0 = y1 = i0 // W
        n = 0
        while pila:
            i = pila.pop()
            n += 1
            cx, cy = i % W, i // W
            x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
            for nx in (cx - 1, cx, cx + 1):
                if 0 <= nx < W:
                    for ny in (cy - 1, cy, cy + 1):
                        if 0 <= ny < H and tinta[ny * W + nx]:
                            tinta[ny * W + nx] = 0
                            pila.append(ny * W + nx)
        if (x1 - x0) > 30 * zoom or (y1 - y0) > 26 * zoom:
            continue                                   # algo grande que no es un numero
        centro = (x0 + x1) / 2 if horizontal else (y0 + y1) / 2
        m = min(marcas, key=lambda t: abs(t - centro))
        if abs(m - centro) > 0.55 * paso:
            continue
        gr = grupos.setdefault(m, [x0, y0, x1, y1, 0])
        gr[0], gr[1], gr[2], gr[3] = min(gr[0], x0), min(gr[1], y0), max(gr[2], x1), max(gr[3], y1)
        gr[4] += n
    # lo que quedo de cada rayita: debe parecer un numero (alto de letra, con tinta)
    buenos = [(m, gr) for m, gr in sorted(grupos.items()) if gr[3] - gr[1] >= 4 * zoom and gr[4] >= 6 * zoom]
    if not buenos:
        return []
    alto = sorted(gr[3] - gr[1] + 1 for _, gr in buenos)[len(buenos) // 2]
    f = max(1.0, 34.0 / alto)
    blanco = g.point(lambda v: 255 if v >= umbral + 40 else v)
    hueco = int(alto * 1.4) + 4
    trozos = [(m, blanco.crop((gr[0] - 1, gr[1] - 1, gr[2] + 2, gr[3] + 2))) for m, gr in buenos]
    ancho = max(t.width for _, t in trozos) + 2 * hueco
    hoja = Image.new("L", (ancho, sum(t.height for _, t in trozos) + hueco * (len(trozos) + 1)), 255)
    lugares, y = [], hueco
    for m, t in trozos:
        hoja.paste(t, (hueco, y))
        lugares.append((y, y + t.height, m))
        y += t.height + hueco
    grande = ImageOps.expand(hoja.resize((int(hoja.width * f), int(hoja.height * f)), Image.LANCZOS),
                             border=20, fill=255)
    out = []
    for psm in (6, 4):
        try:
            d = ocr.datos(grande, psm=psm, solo="-0123456789.")
        except Exception:
            continue
        for i, t in enumerate(d.get("text", [])):
            t = (t or "").strip().strip(".")
            if not re.fullmatch(r"-?\d{1,4}(?:\.\d{1,3})?", t):
                continue
            cy = (d["top"][i] + d["height"][i] / 2 - 20) / f
            for y0, y1, m in lugares:
                if y0 - 4 <= cy <= y1 + 4:
                    out.append((float(t), m))
                    break
        if len({m for _, m in out}) >= 0.7 * len(lugares):
            break
    return out


def _recta_robusta(pares, paso, signo=0):
    """pixel = a*valor + b con los pares que cuadran (algun numero puede venir mal leido, por ejemplo sin el signo
    menos). signo: +1 / -1 si la recta debe crecer o bajar. None si no hay 3 que cuadren."""
    mejor = None
    for i in range(len(pares)):
        for j in range(i + 1, len(pares)):
            (v1, p1), (v2, p2) = pares[i], pares[j]
            if v1 == v2:
                continue
            a = (p2 - p1) / (v2 - v1)
            if signo and a * signo <= 0:
                continue
            b = p1 - a * v1
            buenos = list({p: (v, p) for v, p in pares if abs(a * v + b - p) <= max(3.0, 0.08 * paso)}.values())
            if len(buenos) >= 3 and (mejor is None or len(buenos) > len(mejor)):
                mejor = buenos
    if not mejor:
        return None
    n = len(mejor)
    sv, sp = sum(v for v, _ in mejor), sum(p for _, p in mejor)
    svv, svp = sum(v * v for v, _ in mejor), sum(v * p for v, p in mejor)
    den = n * svv - sv * sv
    if abs(den) < 1e-9:
        return None
    a = (n * svp - sv * sp) / den
    return a, (sp - a * sv) / n


def _ejes_candidatos(osc, rej, W, H, zoom):
    """Lineas que pueden ser un eje (con rayitas o cruzadas por la cuadricula), las mejores primero.
    osc: imagen L con 255 donde hay tinta oscura; rej: 255 donde hay cualquier linea (aunque sea clarita)."""
    out = []
    lineas = _lineas_largas(osc.point(lambda v: 1 if v else 0).tobytes(), W, H, zoom)
    lineas = sorted(lineas, key=lambda l: -(l[1] - l[0]))[:40]      # (los ejes son de las mas largas)
    for linea in lineas:
        for marcas in (_rayitas(osc, W, H, linea, zoom), None):
            if marcas is None:
                marcas = _cuadricula(rej, W, H, linea, zoom)
            if len(marcas) < 5:
                continue
            pasos = sorted(b - a for a, b in zip(marcas, marcas[1:]))
            paso = pasos[len(pasos) // 2]
            parejas = sum(1 for d in pasos if abs(d - paso) <= max(2, 0.15 * paso))
            if paso < 4 * zoom or parejas < 0.6 * len(pasos):
                continue
            out.append((linea, marcas, paso))
            break
    out.sort(key=lambda c: -len(c[1]))
    return out[:3]


class _OCRContado:
    """El OCR con un tope de lecturas: cuando se acaba, ya no lee (devuelve vacio)."""

    def __init__(self, ocr, tope):
        self.ocr, self.quedan, self.usadas = ocr, tope, 0
        self.disponible = getattr(ocr, "disponible", True)

    def datos(self, *a, **k):
        if self.quedan <= 0:
            return {"text": []}
        self.quedan -= 1
        self.usadas += 1
        return self.ocr.datos(*a, **k)


def _bandas(linea, horizontal, zoom, W, H):
    """Donde pueden estar los numeros de un eje: abajo del eje x (si no, arriba); a la izquierda del eje y (si no, a
    la derecha). Sin las rayitas y un poco mas alla de las puntas."""
    desde, hasta, a, b = linea
    r7, r14 = int(7 * zoom), int(14 * zoom)
    if horizontal:
        d0, d1 = max(0, desde - r14), min(W, hasta + r14)
        return [(d0, b + r7, d1, min(H, b + int(34 * zoom))), (d0, max(0, a - int(34 * zoom)), d1, a - r7)]
    d0, d1 = max(0, desde - r14), min(H, hasta + r14)
    return [(max(0, a - int(56 * zoom)), d0, a - r7, d1), (b + r7, d0, min(W, b + int(56 * zoom)), d1)]


def _redondo(por_rayita):
    return next((n for n in _REDONDOS if abs(por_rayita - n) <= 0.08 * n), None)


def _algo_escrito(trozo, zoom, marcas, paso, horizontal):
    """True si junto a por lo menos 2 rayitas hay algo escrito (tinta oscura que no es una linea de lado a lado).
    Es rapido (sin OCR): asi las lineas que no son ejes no gastan tiempo leyendo."""
    g = ImageOps.autocontrast(ImageOps.grayscale(trozo), cutoff=1).point(lambda v: 255 if v < 140 else 0)
    W, H = g.size
    if W < 4 or H < 4:
        return False
    # (sin las lineas que cruzan toda la banda: el otro eje o la cuadricula)
    lineas = _por_columna(g, 0, 0, W, H) if horizontal else _por_columna(g.transpose(Image.Transpose.TRANSPOSE), 0, 0, H, W)
    lleno = {k for k, v in enumerate(lineas) if v >= 150}
    con = 0
    for m in marcas:
        a, b = int(m - 0.45 * paso), int(m + 0.45 * paso) + 1
        a, b = max(0, a), min(W if horizontal else H, b)
        if b - a < 2:
            continue
        caja = (a, 0, b, H) if horizontal else (0, a, W, b)
        tinta = g.crop(caja).histogram()[255]
        tinta -= sum(1 for k in range(a, b) if k in lleno) * (H if horizontal else W)
        if tinta >= 6 * zoom * zoom:
            con += 1
            if con >= 2:
                return True
    return False


def _leer_eje(img, linea, marcas, paso, horizontal, zoom, ocr, rejilla, W, H):
    """Lee los numeros de un eje de tres formas (de la mas rapida a la mas lenta) hasta que cuadren.
    Devuelve ((a, b) o None, por_rayita, todos los pares (valor, rayita) leidos)."""
    signo = 1 if horizontal else -1
    todos = []
    for banda in _bandas(linea, horizontal, zoom, W, H):
        if banda[2] - banda[0] < 6 or banda[3] - banda[1] < 6:
            continue
        base = banda[0] if horizontal else banda[1]
        rel = [m - base for m in marcas]
        rej = ([c - banda[0] for c in rejilla[0]], [f - banda[1] for f in rejilla[1]])
        trozo = img.crop(banda)
        if not _algo_escrito(trozo, zoom, rel, paso, horizontal):
            continue                     # junto a las rayitas no hay nada escrito: ni se gasta OCR

        def por_ventana():
            return [(v, m + base) for v, m in _numeros_por_ventana(trozo, zoom, ocr, rel, paso, horizontal)]

        def sueltos():
            out = []
            for v, cx, cy in _numeros_de(trozo, zoom, ocr, rej):
                pos = (cx + banda[0]) if horizontal else (cy + banda[1])
                m = min(marcas, key=lambda t: abs(t - pos))
                if abs(m - pos) <= 0.6 * paso:
                    out.append((v, m))
            return out

        def por_rayita():
            return [(v, m + base) for v, m in _numeros_por_rayita(trozo, zoom, ocr, rel, paso, horizontal, rej)]
        pares = []
        for leer in (por_ventana, sueltos, por_rayita):
            try:
                nuevos = leer()
            except Exception:
                continue
            pares += nuevos
            todos += nuevos
            r = _recta_robusta(pares, paso, signo)
            if not r or r[0] * signo <= 0:
                continue
            # que cuadre con la cuadricula: cada rayita vale un numero "redondo" (1, 2, 5, 0.5...)
            n = _redondo(paso / abs(r[0]))
            if n:
                return r, n, todos
    return None, None, todos


def _con_origen(pares, origen, paso, signo, otro_por_rayita):
    """Un eje con pocos numeros leidos, pero ya se sabe donde esta su 0 (donde lo cruza el otro eje):
    pixel = a * valor + origen. Cada numero leido "vota" por cuanto vale cada rayita."""
    votos = {}
    for v, m in pares:
        if not v:
            continue
        a = (m - origen) / v
        if a * signo <= 0:
            continue
        n = _redondo(paso / abs(a))
        if n and abs(abs(a) * n - paso) <= max(2.0, 0.08 * paso):
            votos[n] = votos.get(n, 0) + 1
    if not votos:
        return None
    n, cuantos = max(votos.items(), key=lambda t: t[1])
    if cuantos < 2 and n != otro_por_rayita:
        return None                  # un solo numero que no cuadra con el otro eje: puede estar mal leido
    return signo * paso / n, origen, n


def ejes_del_plano(img, zoom=1.0, ocr=None):
    """Plano cartesiano en la imagen: encuentra los ejes por sus rayitas (o por la cuadricula) y lee el numero de
    cada una con OCR de solo numeros. No se confunde con la cruz que sigue al mouse ni con el marco.
    Sirve con ejes negros, grises o de color, cuadricula clara o punteada, fondo oscuro, numeros chiquitos.
    Devuelve {"x": (a, b) o None, "y": (a, b) o None, "rango": {"x": (min, max, paso), "y": ...},
    "lineas": {"x": (linea, rayitas, paso), "y": ...}} con pixel = a * valor + b. "lineas" trae los ejes que se
    vieron aunque no se pudieran leer sus numeros (asi la IA puede decir cuanto vale cada rayita)."""
    out = {"x": None, "y": None, "rango": {}, "lineas": {}}
    if ocr is None or not getattr(ocr, "disponible", False):
        return out
    gris = ImageOps.grayscale(img)
    W, H = gris.size
    if W < 60 or H < 60:
        return out
    out = _ejes_de(img, gris, zoom, _OCRContado(ocr, 10))
    if out["x"] or out["y"]:
        return out
    hist = gris.histogram()
    if max(range(256), key=lambda v: hist[v]) < 110 or sum(hist[:90]) >= 0.25 * W * H:
        # tema oscuro (ejes y numeros claros sobre fondo oscuro): se voltea y se busca otra vez. (Primero se busca
        # sin voltear: una ventana blanca sobre un escritorio oscuro NO es tema oscuro.)
        otro = _ejes_de(ImageOps.invert(img.convert("RGB")), ImageOps.invert(gris), zoom, _OCRContado(ocr, 8))
        if otro["x"] or otro["y"]:
            return otro
        out["lineas"] = out["lineas"] or otro["lineas"]
    return out


def _ejes_de(img, gris, zoom, ocr):
    """ejes_del_plano con la imagen ya en gris (ejes oscuros sobre fondo claro)."""
    out = {"x": None, "y": None, "rango": {}, "lineas": {}}
    W, H = gris.size
    usados = {}
    pares_de = {}
    probadas = []
    for umbral in (120, 175):            # ejes negros; luego grises o de color
        if out["x"] and out["y"]:
            break
        oscuro = gris.point(lambda v, u=umbral: 255 if v < u else 0)
        rej = gris.point(lambda v: 255 if v < 236 else 0)
        vistas = {"x": (oscuro, rej, W, H),
                  "y": (oscuro.transpose(Image.Transpose.TRANSPOSE), rej.transpose(Image.Transpose.TRANSPOSE), H, W)}
        candidatos = {eje: _ejes_candidatos(o, r, w, h, zoom) if not out[eje] else []
                      for eje, (o, r, w, h) in vistas.items()}
        rejilla = (candidatos["x"][0][1] if candidatos["x"] else [],      # columnas de la cuadricula
                   candidatos["y"][0][1] if candidatos["y"] else [])      # renglones de la cuadricula
        for eje in ("x", "y"):
            if out[eje]:
                continue
            horizontal = eje == "x"
            for linea, marcas, paso in candidatos[eje]:
                if any(e == eje and abs(l[2] - linea[2]) <= 3 and min(l[1], linea[1]) - max(l[0], linea[0]) > 0
                       for e, l in probadas):
                    continue             # (esa linea ya se leyo con el otro umbral)
                probadas.append((eje, linea))
                out["lineas"].setdefault(eje, (linea, marcas, paso))
                r, n, todos = _leer_eje(img, linea, marcas, paso, horizontal, zoom, ocr, rejilla, W, H)
                pares_de.setdefault(eje, (linea, marcas, paso, todos))
                if not r:
                    continue
                out[eje] = r
                out["lineas"][eje] = (linea, marcas, paso)
                usados[eje] = (linea, n)
                desde, hasta = linea[0], linea[1]
                vals = sorted(((desde - r[1]) / r[0], (hasta - r[1]) / r[0]))
                out["rango"][eje] = (round(vals[0], 3), round(vals[1], 3), round(n, 3))
                break
    # el otro eje cruza en un numero de la cuadricula (casi siempre el 0): si no, algo se leyo mal
    for eje, otro in (("x", "y"), ("y", "x")):
        if out[eje] and otro in usados:
            linea = usados[otro][0]
            cruce = (linea[2] + linea[3]) / 2
            v = (cruce - out[eje][1]) / out[eje][0]
            paso = usados[eje][1]
            if abs(v / paso - round(v / paso)) > 0.3:
                out[eje] = None
                out["rango"].pop(eje, None)
                usados.pop(eje, None)
    # solo se pudo leer un eje: si el otro eje lo cruza en el 0, ahi esta el 0 del otro (el origen) y con
    # poquitos numeros leidos ya se sabe cuanto vale cada rayita
    for eje, otro in (("x", "y"), ("y", "x")):
        if out[eje] or not out[otro] or otro not in usados or eje not in out["lineas"]:
            continue
        linea_e, marcas, paso = out["lineas"][eje]
        cruce_otro = (linea_e[2] + linea_e[3]) / 2           # donde el eje que falta cruza al que si se leyo
        v0 = (cruce_otro - out[otro][1]) / out[otro][0]
        if abs(v0) > 0.3 * usados[otro][1]:
            continue
        linea_o = usados[otro][0]
        origen = (linea_o[2] + linea_o[3]) / 2               # renglon del eje x (o columna del eje y)
        pares = pares_de.get(eje, (None, None, None, []))[3]
        r = _con_origen(pares, origen, paso, 1 if eje == "x" else -1, usados[otro][1])
        if r:
            a, b, n = r
            out[eje] = (a, b)
            usados[eje] = (linea_e, n)
            vals = sorted(((linea_e[0] - b) / a, (linea_e[1] - b) / a))
            out["rango"][eje] = (round(vals[0], 3), round(vals[1], 3), round(n, 3))
    return out


def describir_plano(plano, s=1.0):
    """Texto para la IA: que plano se detecto (asi elige puntos que si se ven)."""
    r = plano.get("rango") or {}
    if not (plano.get("x") and plano.get("y")):
        return ""
    def num(v):
        return str(int(v)) if float(v).is_integer() else str(v)
    x0, x1, px = r.get("x", (None, None, None))
    y0, y1, py = r.get("y", (None, None, None))
    o = (plano["x"][1] * s, plano["y"][1] * s)
    return (f"PLANO CARTESIANO detectado: x de {num(x0)} a {num(x1)} (cada rayita {num(px)}), y de {num(y0)} a "
            f"{num(y1)} (cada rayita {num(py)}). El origen (0,0) esta en la imagen en ({int(o[0])},{int(o[1])}). "
            "Para puntos del plano usa {\"gx\":..,\"gy\":..}: NO LIMIT los pone exactos.")


def quitar_orillas(subs, rects, zoom=1.0):
    """Quita las rayas que en realidad son la orilla de arriba o de abajo de un rectangulo ya encontrado."""
    m = 4 * zoom
    salida = []
    for s in subs:
        y = s[3] - 1
        orilla = False
        for f in rects:
            junto = min(s[2], f[2]) - max(s[0], f[0])
            if junto > 0.6 * (s[2] - s[0]) and (abs(y - f[1]) <= m or abs(y - f[3]) <= m):
                orilla = True
                break
        if not orilla:
            salida.append(s)
    return salida


def _dentro(x, y, caja, margen=0):
    return caja[0] - margen <= x <= caja[2] + margen and caja[1] - margen <= y <= caja[3] + margen


def _renglones(textos):
    """Cuantos renglones distintos forman estas cajas de texto (ignora basura muy chaparra del OCR)."""
    textos = [c for c in textos if c["caja"][3] - c["caja"][1] >= 6]
    if not textos:
        return 0
    alto = sorted(c["caja"][3] - c["caja"][1] for c in textos)[len(textos) // 2] or 1
    ys = sorted(c["cy"] for c in textos)
    renglones = 1
    for a, b in zip(ys, ys[1:]):
        if b - a > 0.8 * alto:
            renglones += 1
    return renglones


def filtrar_campos(rects, cajas, px, py):
    campos = []
    for r in rects:
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        otros = [f for f in rects if f is not r and _dentro((f[0] + f[2]) / 2, (f[1] + f[3]) / 2, r)
                 and (f[2] - f[0]) * (f[3] - f[1]) < (r[2] - r[0]) * (r[3] - r[1])]
        textos = [c for c in cajas if _dentro(c["cx"], c["cy"], r)]
        if otros or _renglones(textos) >= 2:
            continue   # tiene varias lineas de texto adentro: es un cuadro con la pregunta, no un campo
        alta_y_angosta = (r[3] - r[1]) >= 1.35 * (r[2] - r[0])
        if not alta_y_angosta and any(
                c["caja"][0] - 2 <= r[0] and r[2] <= c["caja"][2] + 2 and c["caja"][1] - 2 <= r[1]
                and r[3] <= c["caja"][3] + 2 and (c["caja"][3] - c["caja"][1]) < 1.4 * (r[3] - r[1])
                and (c["caja"][2] - c["caja"][0]) > 1.8 * (r[2] - r[0]) for c in cajas):
            continue   # es una letra dentro de un renglon de texto
            # (una cajita alta y angosta en medio de un renglon NO es letra: es una casilla vacia, como en ALEKS)
        campos.append({"caja": r, "cx": cx, "cy": cy})
    if len(campos) > MAX_CAMPOS:
        campos.sort(key=lambda c: (c["cx"] - px) ** 2 + (c["cy"] - py) ** 2)
        campos = campos[:MAX_CAMPOS]
    campos.sort(key=lambda c: (round(c["caja"][1] / 12), c["caja"][0]))
    return campos


def _distancia(x, y, caja):
    dx = max(caja[0] - x, 0, x - caja[2])
    dy = max(caja[1] - y, 0, y - caja[3])
    return math.hypot(dx, dy)


def refinar_punto(img, x, y, zoom=1.0):
    rx, ry = int(140 * zoom), int(90 * zoom)
    zona = (max(0, int(x - rx)), max(0, int(y - ry)), min(img.width, int(x + rx)), min(img.height, int(y + ry)))
    if zona[2] - zona[0] < 10 or zona[3] - zona[1] < 10:
        return None
    mejor = None
    for r in rectangulos(img.crop(zona), zoom, relajado=True):
        caja = (r[0] + zona[0], r[1] + zona[1], r[2] + zona[0], r[3] + zona[1])
        d = _distancia(x, y, caja)
        if d > 30 * zoom:
            continue
        clave = (d, (caja[2] - caja[0]) * (caja[3] - caja[1]))
        if mejor is None or clave < mejor[0]:
            mejor = (clave, caja)
    if mejor is None:
        return None
    caja = mejor[1]
    return (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2


# ================================================================ imagen y texto para la IA

def factor_para_ia(w, h, lado=1568, tokens=1560):
    """Escala para que la IA vea la imagen sin redimensionarla por su cuenta (asi cuadran las coordenadas)."""
    def cabe(a, b):
        ca, cb = math.ceil(a / 28), math.ceil(b / 28)
        return ca * 28 <= lado and cb * 28 <= lado and ca * cb <= tokens

    if cabe(w, h):
        return 1.0
    lo, hi = 0.05, 1.0
    for _ in range(40):
        m = (lo + hi) / 2
        if cabe(int(w * m), int(h * m)):
            lo = m
        else:
            hi = m
    return lo


def _fuente(tam):
    try:
        return ImageFont.load_default(size=tam)
    except Exception:
        return ImageFont.load_default()


def imagen_para_ia(img, px, py, campos=()):
    s = factor_para_ia(img.width, img.height)
    tam = (max(1, int(img.width * s)), max(1, int(img.height * s)))
    im = img.resize(tam, Image.LANCZOS) if s != 1.0 else img.copy()
    dib = ImageDraw.Draw(im)
    fuente = _fuente(13)
    for i, c in enumerate(campos):
        x0, y0, x1, y1 = [v * s for v in c["caja"]]
        dib.rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), outline=MORADO, width=2)
        etiqueta = f"C{i}"
        ty = y0 - 17 if y0 - 17 >= 0 else y1 + 3
        caja_txt = dib.textbbox((x0, ty), etiqueta, font=fuente)
        dib.rectangle((caja_txt[0] - 1, caja_txt[1] - 1, caja_txt[2] + 1, caja_txt[3] + 1), fill=(255, 255, 255))
        dib.text((x0, ty), etiqueta, fill=MORADO, font=fuente)
    r = 14
    x, y = px * s, py * s
    dib.ellipse((x - r, y - r, x + r, y + r), outline=(255, 0, 0), width=4)

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    datos, tipo = buf.getvalue(), "image/png"
    if len(datos) > 3_500_000:
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
        datos, tipo = buf.getvalue(), "image/jpeg"
    return base64.standard_b64encode(datos).decode("ascii"), tipo, s, tam


def armar_texto(cajas, s, px, py, tam, campos=()):
    filas = [f"Captura de {tam[0]}x{tam[1]} px. El puntero (circulo rojo) esta en ({int(px * s)},{int(py * s)})."]
    if cajas:
        filas.append("Cajas de texto (id | centro x,y | texto):")
        for i, c in enumerate(cajas):
            filas.append(f"[{i}] ({int(c['cx'] * s)},{int(c['cy'] * s)}) {c['texto']}")
    else:
        filas.append("No se detectaron cajas de texto: usa x,y.")
    if campos:
        filas.append("Campos para escribir detectados (id | centro x,y | ancho x alto):")
        for i, c in enumerate(campos):
            x0, y0, x1, y1 = c["caja"]
            filas.append(f"[C{i}] ({int(c['cx'] * s)},{int(c['cy'] * s)}) {int((x1 - x0) * s)}x{int((y1 - y0) * s)}")
    else:
        filas.append("No se detectaron campos para escribir.")
    return "\n".join(filas)


# ================================================================ entender la respuesta

def _cadena_json(cadena):
    try:
        return json.loads('"' + cadena + '"', strict=False)
    except json.JSONDecodeError:
        return cadena


def interpretar(texto):
    texto = texto or ""
    m = re.search(r"\{.*\}", texto, re.S)
    if m:
        try:
            datos = json.loads(m.group(0), strict=False)
            if isinstance(datos, dict):
                return datos
        except json.JSONDecodeError:
            pass
    datos = {}
    mt = re.search(r'"tipo"\s*:\s*"(\w+)"', texto)
    if mt:
        datos["tipo"] = mt.group(1)
    pares = re.findall(r'"campo"\s*:\s*"?([Cc]?\s*\d+)"?\s*,\s*"texto"\s*:\s*"((?:[^"\\]|\\.)*)"', texto, re.S)
    if pares:
        datos["respuestas"] = [{"campo": c, "texto": _cadena_json(t)} for c, t in pares]
    mi = re.search(r'"ids"\s*:\s*\[([^\]]*)\]', texto)
    if mi:
        datos["ids"] = [int(n) for n in re.findall(r"\d+", mi.group(1))]
    else:
        m1 = re.search(r'"id"\s*:\s*(\d+)', texto)
        if m1:
            datos["id"] = int(m1.group(1))
    mx = re.search(r'"x"\s*:\s*(-?\d+(?:\.\d+)?)', texto)
    my = re.search(r'"y"\s*:\s*(-?\d+(?:\.\d+)?)', texto)
    if mx and my and "respuestas" not in datos and "ids" not in datos:
        datos["x"], datos["y"] = float(mx.group(1)), float(my.group(1))
    mr = re.search(r'"respuesta"\s*:\s*"((?:[^"\\]|\\.)*)"', texto, re.S)
    if mr:
        datos["respuesta"] = _cadena_json(mr.group(1))
    return datos


def limpiar_respuesta(texto):
    texto = re.sub(r"\*\*|__|`", "", texto or "")
    texto = re.sub(r"\s*[\r\n]+\s*", " ", texto)
    return re.sub(r"[ \t]{2,}", " ", texto).strip()


def _numero(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def resolver_objetivo(obj, cajas, campos, s, img, zoom=1.0, escribir_ahi=False):
    """Traduce lo que eligio la IA (C2, 5, o {x,y}) a un punto (x, y, descripcion) de la captura."""
    w, h = img.size

    def campo_cerca(x, y, radio):
        mejor = None
        for c in campos:
            d = _distancia(x, y, c["caja"])
            if d <= radio and (mejor is None or d < mejor[0]):
                mejor = (d, c)
        return mejor[1] if mejor else None

    if isinstance(obj, str):
        mc = re.fullmatch(r"\s*[Cc]\s*(\d+)\s*", obj)
        if mc:
            i = int(mc.group(1))
            if 0 <= i < len(campos):
                return campos[i]["cx"], campos[i]["cy"], f"cajita C{i}"
            return None

    n = _numero(obj) if not isinstance(obj, dict) else None
    if n is not None and float(n).is_integer():
        i = int(n)
        if not 0 <= i < len(cajas):
            return None
        c = cajas[i]
        if escribir_ahi:
            for campo in campos:
                if _dentro(campo["cx"], campo["cy"], c["caja"]) or _dentro(c["cx"], c["cy"], campo["caja"]):
                    return campo["cx"], campo["cy"], "cajita junto a: " + c["texto"]
            fino = refinar_punto(img, c["cx"], c["cy"], zoom)
            if fino:
                return fino[0], fino[1], "cajita junto a: " + c["texto"]
        return c["cx"], c["cy"], c["texto"]

    if isinstance(obj, dict):
        x, y = _numero(obj.get("x")), _numero(obj.get("y"))
        if x is None or y is None or s <= 0:
            return None
        x, y = min(max(x / s, 0), w - 1), min(max(y / s, 0), h - 1)
        campo = campo_cerca(x, y, 40 * zoom)
        if campo:
            return campo["cx"], campo["cy"], "cajita"
        if escribir_ahi:
            fino = refinar_punto(img, x, y, zoom)
            if fino:
                return fino[0], fino[1], "cajita"
        return x, y, "punto"
    return None


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", texto).split())


_DIGITO_EN_PALABRA = re.compile(r"(?<=[a-z])\d(?=[a-z])")


def _doblar_ocr(t, otro):
    """'t' (ya normalizado) con los errores tipicos del OCR corregidos: un digito en medio de una palabra es una
    letra mal leida ('col6n' -> 'colon') y un 0 solito entre palabras es la palabra 'o' (solo si el otro texto
    dice 'o')."""
    t = _DIGITO_EN_PALABRA.sub("o", t)
    if re.search(r"(?:^| )o(?: |$)", otro):
        t = re.sub(r"(?<=[a-z] )0(?= [a-z])", "o", t)
    return t


def parecido(a, b):
    """0..1: que tanto se parecen dos textos (aguanta basura del OCR alrededor).
    Si los dos traen numeros y los numeros no son los mismos, se toman como distintos (8466 no es 8488)."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    na, nb = re.findall(r"\d+", a), re.findall(r"\d+", b)
    if na and nb and sorted(na) != sorted(nb):
        # antes de decir que son distintos: lo que el OCR suele leer mal (una o con acento como 6 en medio de una
        # palabra, "Col6n"; la palabra "o" como 0, "raices 0 ceros"). Si asi los numeros ya cuadran, se comparan asi.
        a2, b2 = _doblar_ocr(a, b), _doblar_ocr(b, a)
        if sorted(re.findall(r"\d+", a2)) != sorted(re.findall(r"\d+", b2)):
            return min(0.3, difflib.SequenceMatcher(None, a, b).ratio())
        a, b = a2, b2
        if a == b:
            return 0.98
    corto, largo = (a, b) if len(a) <= len(b) else (b, a)
    if re.search(r"(^| )" + re.escape(corto) + r"($| )", largo):
        return 0.6 + 0.4 * len(corto) / len(largo)
    return difflib.SequenceMatcher(None, a, b).ratio()


def corregir_ids(ids, respuesta, cajas):
    """Si la IA puso un id cuyo texto no es su respuesta (error de indice), busca la caja correcta."""
    if not isinstance(respuesta, str) or not respuesta.strip() or not cajas:
        return ids
    textos = [t.strip() for t in respuesta.split("|") if t.strip()]
    numericos = [i for i in ids if isinstance(_numero(i), (int, float)) and float(_numero(i)).is_integer()
                 and 0 <= int(_numero(i)) < len(cajas)]
    if len(textos) != len(ids) or len(numericos) != len(ids):
        return ids
    corregidos = []
    for i, texto in zip(ids, textos):
        i = int(_numero(i))
        actual = parecido(texto, cajas[i]["texto"])
        if actual >= 0.6:
            corregidos.append(i)
            continue
        puntajes = [(parecido(texto, c["texto"]), j) for j, c in enumerate(cajas)]
        mejor = max(p for p, _ in puntajes)
        if mejor >= 0.75 and mejor - actual >= 0.25:
            empatados = [j for p, j in puntajes if p >= mejor - 0.05]
            j = min(empatados, key=lambda j: math.hypot(cajas[j]["cx"] - cajas[i]["cx"], cajas[j]["cy"] - cajas[i]["cy"]))
            corregidos.append(j)
        else:
            corregidos.append(i)
    return corregidos


def armar_plan(datos, cajas, campos, s, img, zoom=1.0):
    """Lista de pasos: [{'punto': (x, y, desc) o None, 'texto': str o None}, ...]."""
    tipo = str(datos.get("tipo") or "").strip().lower()
    pasos = []

    if tipo.startswith("abiert") or "respuestas" in datos:
        entradas = datos.get("respuestas")
        if not isinstance(entradas, list):
            entradas = [{"campo": datos.get("id"), "texto": datos.get("respuesta"),
                         "x": datos.get("x"), "y": datos.get("y")}]
        for e in entradas:
            if not isinstance(e, dict):
                continue
            texto = limpiar_respuesta(str(e.get("texto") or e.get("respuesta") or ""))
            if not texto:
                continue
            obj = e.get("campo", e.get("id"))
            if obj is None and e.get("x") is not None:
                obj = {"x": e.get("x"), "y": e.get("y")}
            punto = resolver_objetivo(obj, cajas, campos, s, img, zoom, escribir_ahi=True) if obj is not None else None
            pasos.append({"punto": punto, "texto": texto})
        return "abierta", pasos

    if tipo == "ninguna":
        return "ninguna", pasos

    ids = datos.get("ids")
    if not isinstance(ids, list):
        ids = [datos.get("id")] if datos.get("id") is not None else []
        if not ids and datos.get("x") is not None:
            ids = [{"x": datos.get("x"), "y": datos.get("y")}]
    ids = corregir_ids(ids, datos.get("respuesta"), cajas)
    vistos = set()
    for obj in ids:
        punto = resolver_objetivo(obj, cajas, campos, s, img, zoom, escribir_ahi=False)
        if punto:
            clave = (round(punto[0]), round(punto[1]))
            if clave in vistos:
                continue
            vistos.add(clave)
        pasos.append({"punto": punto, "texto": None})
    return "opcion", pasos


# ================================================================ revision (para ver que paso)

def guardar_revision(carpeta, img, cajas, campos, px, py, pasos):
    try:
        os.makedirs(carpeta, exist_ok=True)
        img.save(os.path.join(carpeta, "ultima_captura.png"))
        rev = img.copy()
        dib = ImageDraw.Draw(rev)
        for i, c in enumerate(cajas):
            dib.rectangle(c["caja"], outline=(0, 160, 255), width=1)
            dib.text((c["caja"][0], max(0, c["caja"][1] - 11)), str(i), fill=(0, 160, 255))
        for i, c in enumerate(campos):
            dib.rectangle(c["caja"], outline=MORADO, width=2)
            dib.text((c["caja"][0], max(0, c["caja"][1] - 11)), f"C{i}", fill=MORADO)
        dib.ellipse((px - 14, py - 14, px + 14, py + 14), outline=(255, 0, 0), width=4)
        for n, paso in enumerate(pasos, 1):
            if paso["punto"]:
                x, y = paso["punto"][0], paso["punto"][1]
                dib.ellipse((x - 10, y - 10, x + 10, y + 10), outline=(0, 200, 0), width=4)
                dib.text((x + 12, y - 6), str(n), fill=(0, 160, 0))
        rev.save(os.path.join(carpeta, "ultima_revision.png"))
    except Exception:
        pass


# ================================================================ todo junto

class Resultado:
    def __init__(self):
        self.tipo = "nada"
        self.pasos = []
        self.datos = {}
        self.cajas = []
        self.campos = []
        self.salida = ""
        self.cortado = False
        self.t_lectura = 0.0
        self.t_ia = 0.0


def procesar(img, px, py, preguntar, zoom=1.0, ocr=None, avisar=None):
    """Lee la captura, pregunta a la IA y arma el plan. 'preguntar(b64, mime, texto)' -> (salida, cortado)."""
    avisar = avisar or (lambda *_: None)
    res = Resultado()
    t = time.time()
    rects = {}

    def buscar():
        try:
            rects["r"] = rectangulos(img, zoom)
        except Exception:
            rects["r"] = []

    hilo = threading.Thread(target=buscar, daemon=True)
    hilo.start()
    if ocr is not None and ocr.disponible:
        try:
            res.cajas = detectar_cajas(img, px, py, zoom, ocr)
        except Exception:
            res.cajas = []
    hilo.join()
    res.campos = filtrar_campos(rects.get("r", []), res.cajas, px, py)
    res.t_lectura = time.time() - t

    avisar("pensando")
    t = time.time()
    b64, mime, s, tam = imagen_para_ia(img, px, py, res.campos)
    res.salida, res.cortado = preguntar(b64, mime, armar_texto(res.cajas, s, px, py, tam, res.campos))
    res.t_ia = time.time() - t
    res.datos = interpretar(res.salida)
    res.tipo, res.pasos = armar_plan(res.datos, res.cajas, res.campos, s, img, zoom)
    return res


def ejecutar(res, left, top, cancelar=None, acciones=entrada):
    """Da los clics o escribe. Devuelve (hecho, n): hecho en clic/escrita/solo_mostrar/nada."""
    cancelar = cancelar or (lambda: False)
    if res.tipo == "abierta":
        escritas = 0
        for paso in res.pasos:
            if paso["punto"] is None:
                continue
            if cancelar() or acciones.tecla_abajo(acciones.VK_ESCAPE):
                raise acciones.Cancelado()
            acciones.clic(left + paso["punto"][0], top + paso["punto"][1])
            time.sleep(0.35)
            acciones.seleccionar_todo()
            time.sleep(0.05)
            acciones.escribir(paso["texto"], cancelar)
            escritas += 1
            time.sleep(0.15)
        if escritas:
            return "escrita", escritas
        return ("solo_mostrar", 0) if res.pasos else ("nada", 0)

    if res.tipo == "opcion":
        clics = 0
        for paso in res.pasos:
            if paso["punto"] is None:
                continue
            if cancelar():
                raise acciones.Cancelado()
            acciones.clic(left + paso["punto"][0], top + paso["punto"][1])
            clics += 1
            time.sleep(0.15)
        return ("clic", clics) if clics else ("nada", 0)
    return "nada", 0
