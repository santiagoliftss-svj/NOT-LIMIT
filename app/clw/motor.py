"""El cerebro: captura la pantalla, lee el texto, encuentra las cajitas, pregunta a la IA y contesta."""

import base64
import ctypes
import io
import json
import math
import os
import re
import threading
import time

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
- Si hay que calcular o razonar (matematicas, fisica, logica), resuelvelo primero en "pasos" de forma breve y luego da la respuesta. Si no hace falta, omite "pasos".

Si es de OPCION MULTIPLE (circulos, casillas o botones con opciones):
{"tipo": "opcion", "pasos": "...", "ids": [<id>], "respuesta": "<texto de la opcion>"}
- "ids" son los ids numericos de las cajas de texto de las opciones correctas, nunca el de la pregunta.
- Normalmente es una sola. Solo si la pregunta pide marcar varias (casillas), pon todas las correctas.
- Si una opcion correcta no tiene caja de texto (por ejemplo es una imagen), en su lugar pon {"x": <x>, "y": <y>} con su centro.

Si es ABIERTA (hay que escribir en uno o varios campos):
{"tipo": "abierta", "pasos": "...", "respuestas": [{"campo": "C0", "texto": "..."}, {"campo": "C1", "texto": "..."}]}
- Una entrada por cada campo de ESA pregunta, en orden: de arriba a abajo y de izquierda a derecha.
- "campo" es el id del campo marcado (C0, C1, ...). Si el campo no se marco pero si se leyo el texto gris de adentro (por ejemplo "Escriba su respuesta"), usa el id numerico de esa caja de texto. Si no hay ninguno, cambia "campo" por "x" y "y" con el centro del espacio para escribir.
- El texto va tal como se teclearia: texto plano, sin markdown, sin saltos de linea y sin LaTeX.
- El largo depende de lo que pide la pregunta: si pide un dato, nombre, fecha, numero o resultado, contesta corto y directo. Si pide explicar, describir, comparar o argumentar, escribe un parrafo de 3 a 6 oraciones en espanol natural.
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
    if ImageStat.Stat(gris).mean[0] < 110:
        gris = ImageOps.invert(gris)  # pantalla oscura: el OCR lee mejor negro sobre blanco
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

def fondo_por_zonas(gris, lado):
    """Color de fondo de cada zona (el tono que mas se repite), del tamano de la imagen."""
    W, H = gris.size
    cw, ch = (W + lado - 1) // lado, (H + lado - 1) // lado
    valores = []
    for j in range(ch):
        for i in range(cw):
            h = gris.crop((i * lado, j * lado, min(W, (i + 1) * lado), min(H, (j + 1) * lado))).histogram()
            valores.append(max(range(256), key=h.__getitem__))
    mapa = Image.new("L", (cw, ch))
    mapa.putdata(valores)
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


def _dentro(x, y, caja, margen=0):
    return caja[0] - margen <= x <= caja[2] + margen and caja[1] - margen <= y <= caja[3] + margen


def filtrar_campos(rects, cajas, px, py):
    campos = []
    for r in rects:
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        otros = [f for f in rects if f is not r and _dentro((f[0] + f[2]) / 2, (f[1] + f[3]) / 2, r)
                 and (f[2] - f[0]) * (f[3] - f[1]) < (r[2] - r[0]) * (r[3] - r[1])]
        textos = [c for c in cajas if _dentro(c["cx"], c["cy"], r)]
        if otros or len(textos) >= 2:
            continue
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
