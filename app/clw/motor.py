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
            "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2}


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
                if ancho < 28 * zoom and (h < 1.5 * ancho or h < 24 * zoom):
                    continue   # cuadrito chico: casilla o letra, no un campo para escribir
                tinta = total = 0
                for y in range(t1 + 2, b0 - 1):
                    seg = filas[y * W + izq + 3: y * W + der - 2]
                    tinta += seg.count(255)
                    total += len(seg)
                if total and tinta / total > 0.5:
                    continue
                rects.append((izq, t0, der, b1))

    rects.sort(key=lambda r: -(r[2] - r[0]) * (r[3] - r[1]))
    finales = []
    for r in rects:
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
    """Lineas oscuras largas (posibles ejes): [(desde, hasta, fila0, fila1)]."""
    patron = re.compile(rb"\x01{%d,}" % max(20, int(0.35 * W)))
    filas = []
    for k in range(H):
        mejor = None
        for m in patron.finditer(buf, k * W, (k + 1) * W):
            if mejor is None or m.end() - m.start() > mejor[1] - mejor[0]:
                mejor = (m.start() - k * W, m.end() - k * W)
        if mejor:
            filas.append((k, mejor[0], mejor[1]))
    lineas = []
    for k, d, h in filas:
        if lineas and k - lineas[-1][3] <= 1 and abs(d - lineas[-1][0]) < 12 * zoom:
            u = lineas[-1]
            lineas[-1] = (min(u[0], d), max(u[1], h), u[2], k)
        else:
            lineas.append((d, h, k, k))
    return [l for l in lineas if l[3] - l[2] <= max(4, int(4 * zoom))]


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


def _rayitas(buf, W, H, linea, zoom):
    """Rayitas (marcas) que cruzan el eje: trazos cortos y continuos hacia afuera de la linea."""
    desde, hasta, a, b = linea
    largo = max(3, int(3 * zoom))
    cols = []
    for c in range(desde, hasta):
        arriba = a - largo >= 0 and all(buf[(a - 1 - t) * W + c] for t in range(largo))
        abajo = b + largo < H and all(buf[(b + 1 + t) * W + c] for t in range(largo))
        if arriba or abajo:
            cols.append(c)
    return _agrupar(cols, zoom)


def _cuadricula(gbuf, W, H, linea, zoom):
    """Si el eje no tiene rayitas (como en Desmos): donde lo cruzan las lineas de la cuadricula."""
    desde, hasta, a, b = linea
    alto = int(40 * zoom)
    filas = list(range(max(0, a - alto), max(0, a - 2))) + list(range(min(H, b + 3), min(H, b + alto)))
    if len(filas) < 10:
        return []
    minimo = 0.7 * len(filas)
    cols = [c for c in range(desde, hasta) if sum(1 for y in filas if gbuf[y * W + c] < 236) >= minimo]
    return _agrupar(cols, zoom)


def _limpiar_numeros(img, zoom):
    """Sin los puntitos de la cuadricula ni lineas largas, y mas grande (asi el OCR lee bien los numeros)."""
    gris = ImageOps.grayscale(img)
    W, H = gris.size
    px = gris.load()
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


def _numeros_de(img, zoom, ocr):
    """[(valor, cx, cy)] de los numeros en la imagen (solo digitos, punto y signo menos). Se lee de dos formas
    (texto suelto y en bloque) y se juntan: la recta robusta despues descarta lo mal leido."""
    limpia, f = _agrandar(_limpiar_numeros(img, zoom)[0], zoom)
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


def _numeros_por_rayita(img, zoom, ocr, marcas, paso, horizontal):
    """Cuando los numeros vienen muy pegados ('-20-15-10'): se junta lo que hay alrededor de cada rayita y cada
    numero se pone en su propio renglon, con mucho espacio, para leerlos de una vez.
    Devuelve [(valor, posicion_de_la_rayita)] (en la imagen)."""
    gris, letras = _limpiar_numeros(img, zoom)
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


def _recta_robusta(pares, paso):
    """pixel = a*valor + b con los pares que cuadran (algun numero puede venir mal leido). None si no hay 3 que cuadren."""
    mejor = None
    for i in range(len(pares)):
        for j in range(i + 1, len(pares)):
            (v1, p1), (v2, p2) = pares[i], pares[j]
            if v1 == v2:
                continue
            a = (p2 - p1) / (v2 - v1)
            b = p1 - a * v1
            buenos = list({p: (v, p) for v, p in pares if abs(a * v + b - p) <= max(3.0, 0.3 * paso)}.values())
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


def _ejes_candidatos(buf, gbuf, W, H, zoom):
    """Lineas que pueden ser un eje (con rayitas o cruzadas por la cuadricula), las mejores primero."""
    out = []
    for linea in _lineas_largas(buf, W, H, zoom):
        for marcas in (_rayitas(buf, W, H, linea, zoom), None):
            if marcas is None:
                marcas = _cuadricula(gbuf, W, H, linea, zoom)
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


def ejes_del_plano(img, zoom=1.0, ocr=None):
    """Plano cartesiano en la imagen: encuentra los ejes por sus rayitas (o por la cuadricula) y lee el numero de
    cada una con OCR de solo numeros. No se confunde con la cruz que sigue al mouse ni con el marco.
    Devuelve {"x": (a, b) o None, "y": (a, b) o None, "rango": {"x": (min, max, paso), "y": ...}}
    con pixel = a * valor + b."""
    out = {"x": None, "y": None, "rango": {}}
    if ocr is None or not getattr(ocr, "disponible", False):
        return out
    gris = ImageOps.grayscale(img)
    W, H = gris.size
    if W < 60 or H < 60:
        return out
    oscuro = gris.point(lambda v: 1 if v < 120 else 0)
    vistas = {"x": (oscuro.tobytes(), gris.tobytes(), W, H),
              "y": (oscuro.transpose(Image.Transpose.TRANSPOSE).tobytes(),
                    gris.transpose(Image.Transpose.TRANSPOSE).tobytes(), H, W)}
    usados = {}
    for eje, (buf, gbuf, w, h) in vistas.items():
        horizontal = eje == "x"
        for linea, marcas, paso in _ejes_candidatos(buf, gbuf, w, h, zoom):
            desde, hasta, a, b = linea
            r7, r14 = int(7 * zoom), int(14 * zoom)       # (sin las rayitas; un poco mas alla de las puntas)
            d0, d1 = max(0, desde - r14), min(w, hasta + r14)
            if horizontal:          # numeros abajo del eje x (si no, arriba)
                bandas = [(d0, b + r7, d1, min(H, b + int(34 * zoom))), (d0, max(0, a - int(34 * zoom)), d1, a - r7)]
            else:                   # numeros a la izquierda del eje y (si no, a la derecha)
                bandas = [(max(0, a - int(50 * zoom)), d0, a - r7, d1), (b + r7, d0, min(W, b + int(50 * zoom)), d1)]
            hecho = False
            for banda in bandas:
                if banda[2] - banda[0] < 6 or banda[3] - banda[1] < 6:
                    continue
                pares = []
                try:
                    trozo = img.crop(banda)
                    for v, cx, cy in _numeros_de(trozo, zoom, ocr):
                        pos = (cx + banda[0]) if horizontal else (cy + banda[1])
                        m = min(marcas, key=lambda t: abs(t - pos))
                        if abs(m - pos) <= 0.6 * paso:
                            pares.append((v, m))
                    r = _recta_robusta(pares, paso)
                    if not r or len(pares) < 4:
                        base = banda[0] if horizontal else banda[1]
                        rel = [m - base for m in marcas]
                        pares += [(v, m + base) for v, m in _numeros_por_rayita(trozo, zoom, ocr, rel, paso, horizontal)]
                except Exception:
                    continue
                r = _recta_robusta(pares, paso)
                if not r or not ((horizontal and r[0] > 0) or (not horizontal and r[0] < 0)):
                    continue
                # que cuadre con la cuadricula: cada rayita vale un numero "redondo" (1, 2, 5, 0.5...)
                por_rayita = paso / abs(r[0])
                if not any(abs(por_rayita - n) <= 0.08 * n for n in _REDONDOS):
                    continue
                out[eje] = r
                usados[eje] = (linea, por_rayita)
                vals = sorted(((desde - r[1]) / r[0], (hasta - r[1]) / r[0]))
                out["rango"][eje] = (round(vals[0], 3), round(vals[1], 3), round(por_rayita, 3))
                hecho = True
                break
            if hecho:
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
        if any(c["caja"][0] - 2 <= r[0] and r[2] <= c["caja"][2] + 2 and c["caja"][1] - 2 <= r[1]
               and r[3] <= c["caja"][3] + 2 and (c["caja"][3] - c["caja"][1]) < 1.4 * (r[3] - r[1])
               and (c["caja"][2] - c["caja"][0]) > 1.8 * (r[2] - r[0]) for c in cajas):
            continue   # es una letra dentro de un renglon de texto
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
        return min(0.3, difflib.SequenceMatcher(None, a, b).ratio())
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
