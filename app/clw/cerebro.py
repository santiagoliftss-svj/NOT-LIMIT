"""NO LIMIT 2.0: el cerebro.

Tres fases, como lo haria una persona con calma:
  1. UBICAR: con la pantalla completa (reducida) la IA dice donde esta la pregunta que se senalo y de que tipo es.
  2. CONTESTAR: se recorta SOLO esa pregunta, se lee de cerca (OCR + campos) y la IA la resuelve y dice que acciones
     hacer (clic, escribir, elegir en un menu, arrastrar, ordenar).
  3. REVISAR: despues de actuar se vuelve a ver la pregunta y la IA dice si quedo bien o que falta corregir.

Entre la IA y el mouse hay un candado: todo tiene que caer dentro de la pregunta, nunca se pican botones de
avanzar/enviar, solo se escribe en campos de verdad y si algo no cuadra no se hace nada (se avisa la respuesta).
"""

import base64
import inspect
import io
import json
import math
import re
import time

from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import motor

REGLA = 26                     # margen con las reglas de coordenadas (arriba y a la izquierda)
MAX_ACCIONES = 40
PAUSA = 0.35                   # entre accion y accion (que la pagina alcance a registrar cada clic)
TIPOS_CALCULO = ("numerica", "matematica", "graficar", "estadistica", "problema")

# ================================================================ instrucciones para la IA

SISTEMA_UBICAR = """Eres la vista de NO LIMIT, un asistente que contesta la pregunta que el usuario senala en su pantalla.

Recibes una captura reducida de la pantalla. Un circulo rojo marca el puntero del mouse. Arriba y a la izquierda hay reglas con coordenadas en pixeles de la captura: (0,0) es la esquina de arriba a la izquierda de la captura, sin contar las reglas.

Tu trabajo: encontrar UNA pregunta, la que esta bajo el puntero o la mas cercana a el, y decir donde esta y de que tipo es. NO la contestes.

Responde SOLO un JSON en una linea:
{"hay_pregunta": true, "caja": [x0, y0, x1, y1], "tipo": "<tipo>", "controles": "<como se contesta en pantalla>"}

- "caja" encierra TODA esa pregunta: el enunciado, sus imagenes, graficas o tablas, y TODOS sus controles para contestar (opciones, casillas, campos, menus, elementos para arrastrar y los lugares donde se sueltan, el plano para graficar). Si dudas, hazla un poco mas grande, pero no metas otras preguntas.
- "tipo" es uno de: opcion_unica, opcion_multiple, verdadero_falso, completar, desplegable, relacionar, abierta, numerica, matematica, zona_clic, graficar, estadistica, pasos, ordenar, arrastrar, matriz, simulacion, audio_video, otra.
  (opcion_multiple = varias casillas; desplegable = menus para elegir, tambien dentro de un parrafo; matematica = editor de ecuaciones; zona_clic = dar clic en una parte de una imagen; matriz = tabla de filas y columnas con circulos o casillas.)
- Si no hay ninguna pregunta cerca del puntero: {"hay_pregunta": false}"""

SISTEMA_CONTESTAR = """Eres el motor de NO LIMIT: contestas UNA pregunta que el usuario tiene en su pantalla y dices exactamente que acciones hacer con el mouse y el teclado para dejarla contestada.

Recibes:
1) Una imagen recortada SOLO con la pregunta. Arriba y a la izquierda tiene reglas con coordenadas en pixeles: (0,0) es la esquina de arriba a la izquierda de la imagen, sin contar las reglas. Los campos para escribir que se detectaron estan marcados con un recuadro morado y su etiqueta (C0, C1, ...).
2) La lista de cajas de texto leidas con OCR: id, centro (x,y) y texto. El OCR puede traer errores o simbolos raros; guiate por la imagen.
3) La lista de campos para escribir: id (C0, C1, ...), centro y tamano.
4) Una pista del tipo de pregunta (puede estar mal: tu decides).

Trabaja en este orden:
1. Lee TODA la pregunta con calma: enunciado, imagen, grafica o tabla, unidades y lo que pide exactamente. Palabras como NO, EXCEPTO, INCORRECTA, FALSA, MENOS, NUNCA, TODAS o "selecciona todas" cambian la respuesta.
2. Decide el tipo de pregunta y como se contesta en esta pantalla.
3. Resuelvela. Si hay que calcular o razonar (matematicas, fisica, quimica, logica), hazlo paso a paso en "pasos" y comprueba el resultado (sustituye o recalcula). Si hay grafica o imagen, lee sus datos con cuidado.
4. Escribe la respuesta final en "respuesta" (en palabras; si son varias, separadas con " | ").
5. Arma las acciones. Revisa que cada id que uses tenga el texto de tu respuesta (es facil equivocarse por uno).

Responde SOLO un JSON en una linea, sin texto antes ni despues:
{"tipo":"...","pasos":"...","respuesta":"...","acciones":[...],"seguro":"alto"}

Acciones. "en", "desde" y "hasta" pueden ser: el id de una caja de texto (numero), un campo ("C0") o un punto {"x":..,"y":..} de la imagen. En matrices tambien {"fila": id del texto del renglon, "columna": id del texto de la columna}.
- {"hacer":"clic","en":5,"texto":"texto de la opcion"}   marcar una opcion, casilla, circulo, celda o zona de una imagen.
- {"hacer":"escribir","en":"C0","texto":"..."}   escribir en un campo.
- {"hacer":"elegir","en":7,"opcion":"texto exacto de la opcion"}   abrir un menu desplegable y elegir una opcion.
- {"hacer":"arrastrar","desde":3,"hasta":{"x":420,"y":310}}   arrastrar un elemento y soltarlo en su lugar.
- {"hacer":"ordenar","orden":["primero","segundo","tercero"]}   preguntas de ordenar arrastrando: el orden final (de arriba a abajo o de izquierda a derecha) con el texto de cada elemento como se ve.

Reglas de seguridad (muy importantes):
- NUNCA des clic en botones para avanzar, mandar o cerrar: Siguiente, Anterior, Enviar, Entregar, Terminar, Comprobar, Continuar, Saltar, Responder, Aceptar, Submit, Next, Check, Done. Esos los toca el usuario.
- NUNCA des clic en el texto del enunciado ni fuera de la pregunta.
- Solo escribe en campos para escribir: los C#, o el texto gris que esta adentro de un campo (como "Escriba su respuesta"). Si no ves donde escribir, NO inventes un punto: deja "acciones" vacio y pon la respuesta en "respuesta".
- Pon "seguro":"bajo" si no estas seguro de COMO se contesta en esta pantalla (donde dar clic, que arrastrar). Asi NO LIMIT no toca nada y solo muestra la respuesta.
- Si no se puede contestar (audio, video, algo que no se ve), pon "acciones": [] y explica en "no_se_puede".

Por tipo:
- OPCION UNICA, VERDADERO O FALSO, SI O NO: un clic en la opcion correcta (el id de su texto). Si las opciones son imagenes sin texto, el centro de la imagen.
- OPCION MULTIPLE (casillas, "selecciona todas"): un clic por CADA opcion correcta, ni una de mas ni una de menos. Revisa las opciones una por una.
- COMPLETAR (espacios en blanco en un texto): un "escribir" por cada espacio, en orden, solo con la palabra o dato que va.
- DESPLEGABLE (menus, tambien dentro de un parrafo): un "elegir" por cada menu, en orden, con el texto exacto de la opcion. "en" es el menu (su id de texto, su campo o el centro del menu).
- RELACIONAR COLUMNAS: si cada concepto tiene su menu, un "elegir" por concepto. Si se une arrastrando, "arrastrar" de cada elemento a su pareja. Si se escriben letras o numeros, "escribir".
- ABIERTA, RESPUESTA CORTA O ENSAYO: "escribir" en el campo. Corto y directo si pide un dato, nombre, fecha o numero; si pide explicar, describir, comparar o argumentar, un parrafo de 3 a 6 oraciones naturales en el idioma de la pregunta. Texto plano: sin markdown, sin saltos de linea, sin LaTeX.
- NUMERICA (aunque los numeros cambien al azar): usa los numeros que se ven en ESTA imagen, comprueba, y escribe solo el valor (con unidad solo si no aparece ya junto al campo). Redondea como lo pida la pregunta; decimales con punto.
- MATEMATICA EXACTA (editor de ecuaciones con fracciones, exponentes o raices): escribe con / para fracciones, ^ para exponentes y sqrt para raices, y pon {derecha} para salir de un exponente, del denominador o de una raiz. Ejemplo: x^2{derecha}+3/4{derecha}. En campos normales escribe 3/4, x^2 o √3 tal cual.
- ZONA DE CLIC (clic sobre una parte de una imagen, mapa o diagrama): un clic en el centro exacto de esa parte; usa las reglas para dar coordenadas precisas.
- GRAFICAR en un plano cartesiano: da un clic por punto con sus coordenadas DEL PLANO: {"hacer":"clic","en":{"gx":2,"gy":-3}}. NO LIMIT calcula donde cae en la pantalla con los numeros de los ejes. Si hay que mover un punto, "arrastrar" con "hasta":{"gx":..,"gy":..}. Si los ejes no tienen numeros, usa puntos {"x","y"} de la imagen.
- PASOS GUIADOS: contesta solo los pasos que se ven ahorita.
- GRAFICOS ESTADISTICOS: para leerlos usa los valores de los ejes; para construirlos, arrastra la orilla de arriba de cada barra hasta su valor con "hasta":{"x": x de la barra, "gy": valor}, o da clic en cada punto con {"gx","gy"}.
- ORDENAR: usa "ordenar" con el orden final.
- ARRASTRAR ETIQUETAS (a un esquema, plano anatomico, mapa o categorias): un "arrastrar" por etiqueta, desde la etiqueta hasta el lugar exacto donde va.
- MATRIZ (tabla con circulos o casillas): un clic por renglon en la columna correcta con {"fila": id, "columna": id}.
- SIMULACION: contesta con lo que se ve y con la teoria; no muevas controles a lo loco.
- AUDIO O VIDEO: no puedes escuchar ni ver el video completo; si la respuesta no se puede saber con lo que se ve, "acciones": [] y "no_se_puede": "es de audio o video".

Si en la imagen no hay ninguna pregunta: {"tipo":"ninguna","acciones":[]}"""

SISTEMA_REVISAR = """Eres el revisor de NO LIMIT. Ya se hicieron acciones con el mouse y el teclado para contestar una pregunta. Recibes la imagen de la pregunta COMO QUEDO (con reglas de coordenadas arriba y a la izquierda, y los campos marcados en morado), la lista de textos leidos con OCR, la respuesta que se queria dejar y las acciones que se hicieron.

Revisa si quedo contestada EXACTAMENTE como se queria:
- opciones y casillas: marcadas las correctas y NINGUNA de mas.
- campos: con el texto correcto y completo.
- menus: mostrando la opcion correcta.
- arrastrar u ordenar: cada elemento en su lugar.

Responde SOLO un JSON en una linea:
{"ok": true}
o, si falta o sobra algo:
{"ok": false, "falta": "que falta", "acciones": [...]}
con SOLO las acciones para corregir, en el mismo formato (clic, escribir, elegir, arrastrar, ordenar) y con ids y puntos de ESTA imagen.
- Cuidado: picar una casilla que ya esta marcada la DESMARCA. Solo corrige lo que claramente esta mal.
- Nunca piques botones de avanzar o enviar.
- Si no se puede saber, responde {"ok": true}."""

SISTEMAS = {"ubicar": SISTEMA_UBICAR, "contestar": SISTEMA_CONTESTAR, "revisar": SISTEMA_REVISAR}

# botones que NUNCA se pican (los toca el usuario): avanzar, mandar, cerrar
_NAVEGACION = {
    "siguiente", "siguiente pregunta", "anterior", "pregunta anterior", "enviar", "enviar respuesta", "enviar todo",
    "enviar todo y terminar", "entregar", "entregar examen", "terminar", "terminar intento", "finalizar",
    "finalizar intento", "comprobar", "comprobar respuesta", "verificar", "verificar respuesta", "continuar", "saltar",
    "omitir", "salir", "cerrar", "guardar", "guardar y salir", "responder", "aceptar", "listo", "regresar", "volver",
    "submit", "submit answer", "submit all and finish", "next", "next question", "previous", "prev", "back", "check",
    "check answer", "continue", "skip", "finish", "finish attempt", "done", "exit", "close", "save", "save and exit",
    "turn in", "hand in", "ok", "start", "empezar", "comenzar", "reintentar", "retry", "try again",
}


def es_navegacion(texto):
    t = motor._norm(texto)
    if not t:
        return False
    t = re.sub(r"^(?:\d+\s+)?", "", t).strip()       # (algunos botones traen numero o flecha)
    return t in _NAVEGACION


# ================================================================ utilidades de imagen

def _fuente(tam):
    try:
        return ImageFont.load_default(size=tam)
    except Exception:
        return ImageFont.load_default()


def con_reglas(im):
    """La imagen con reglas de coordenadas arriba y a la izquierda (en pixeles de 'im')."""
    W, H = im.size
    out = Image.new("RGB", (W + REGLA, H + REGLA), (244, 244, 246))
    out.paste(im, (REGLA, REGLA))
    d = ImageDraw.Draw(out)
    f = _fuente(10)
    paso = 50 if max(W, H) <= 1100 else 100
    for x in range(0, W, paso):
        largo = 9 if x % (paso * 2) == 0 else 5
        d.line((REGLA + x, REGLA - largo, REGLA + x, REGLA - 1), fill=(90, 90, 100), width=1)
        if x % (paso * 2) == 0:
            d.text((REGLA + x + 2, 1), str(x), fill=(40, 40, 50), font=f)
    for y in range(0, H, paso):
        largo = 9 if y % (paso * 2) == 0 else 5
        d.line((REGLA - largo, REGLA + y, REGLA - 1, REGLA + y), fill=(90, 90, 100), width=1)
        if y % (paso * 2) == 0:
            d.text((1, REGLA + y + 2), str(y), fill=(40, 40, 50), font=f)
    d.line((REGLA - 1, REGLA - 1, REGLA + W, REGLA - 1), fill=(120, 120, 130), width=1)
    d.line((REGLA - 1, REGLA - 1, REGLA - 1, REGLA + H), fill=(120, 120, 130), width=1)
    return out


def _b64(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    datos, tipo = buf.getvalue(), "image/png"
    if len(datos) > 3_500_000:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=90)
        datos, tipo = buf.getvalue(), "image/jpeg"
    return base64.standard_b64encode(datos).decode("ascii"), tipo


def _escala(w, h, lado=1568, tokens=1560):
    """Escala para la IA contando el margen de las reglas."""
    s = motor.factor_para_ia(w + REGLA, h + REGLA, lado, tokens)
    return min(1.0, s)


def preparar_imagen(img, campos=(), puntero=None, lado=1568, tokens=1560):
    """(b64, mime, s, (w, h)): la imagen reducida para la IA, con campos, puntero y reglas."""
    s = _escala(img.width, img.height, lado, tokens)
    tam = (max(1, int(img.width * s)), max(1, int(img.height * s)))
    im = img.resize(tam, Image.LANCZOS) if s != 1.0 else img.copy()
    dib = ImageDraw.Draw(im)
    fuente = _fuente(13)
    for i, c in enumerate(campos):
        x0, y0, x1, y1 = [v * s for v in c["caja"]]
        dib.rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), outline=motor.MORADO, width=2)
        etiqueta = f"C{i}"
        ty = y0 - 17 if y0 - 17 >= 0 else y1 + 3
        caja_txt = dib.textbbox((x0, ty), etiqueta, font=fuente)
        dib.rectangle((caja_txt[0] - 1, caja_txt[1] - 1, caja_txt[2] + 1, caja_txt[3] + 1), fill=(255, 255, 255))
        dib.text((x0, ty), etiqueta, fill=motor.MORADO, font=fuente)
    if puntero is not None:
        x, y = puntero[0] * s, puntero[1] * s
        if 0 <= x < tam[0] and 0 <= y < tam[1]:
            r = 14
            dib.ellipse((x - r, y - r, x + r, y + r), outline=(255, 0, 0), width=4)
    b64, mime = _b64(con_reglas(im))
    return b64, mime, s, tam


def texto_cajas(cajas, campos, s, tam, puntero=None):
    filas = [f"Imagen de {tam[0]}x{tam[1]} px (sin contar las reglas)."]
    if puntero is not None:
        x, y = int(puntero[0] * s), int(puntero[1] * s)
        if 0 <= x < tam[0] and 0 <= y < tam[1]:
            filas.append(f"El puntero (circulo rojo) esta en ({x},{y}).")
    if cajas:
        filas.append("Cajas de texto (id | centro x,y | texto):")
        for i, c in enumerate(cajas):
            filas.append(f"[{i}] ({int(c['cx'] * s)},{int(c['cy'] * s)}) {c['texto']}")
    else:
        filas.append("No se detectaron cajas de texto: usa puntos x,y.")
    if campos:
        filas.append("Campos para escribir detectados (id | centro x,y | ancho x alto):")
        for i, c in enumerate(campos):
            x0, y0, x1, y1 = c["caja"]
            filas.append(f"[C{i}] ({int(c['cx'] * s)},{int(c['cy'] * s)}) {int((x1 - x0) * s)}x{int((y1 - y0) * s)}")
    else:
        filas.append("No se detectaron campos para escribir.")
    return "\n".join(filas)


def hubo_cambio(a, b, caja=None, umbral=8, minimo=10):
    """True si entre dos fotos de la misma zona cambio algo (en 'caja' o en toda la foto)."""
    if a is None or b is None or a.size != b.size:
        return True
    if caja is not None:
        x0, y0, x1, y1 = (int(max(0, caja[0])), int(max(0, caja[1])), int(min(a.width, caja[2])), int(min(a.height, caja[3])))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return True
        a, b = a.crop((x0, y0, x1, y1)), b.crop((x0, y0, x1, y1))
    dif = ImageChops.difference(a.convert("L"), b.convert("L")).point(lambda v: 255 if v > umbral else 0)
    return dif.histogram()[255] >= minimo


def zona_cambiada(a, b, umbral=10):
    """Caja (x0, y0, x1, y1) donde cambio algo entre dos fotos, o None."""
    if a is None or b is None or a.size != b.size:
        return None
    dif = ImageChops.difference(a.convert("L"), b.convert("L")).point(lambda v: 255 if v > umbral else 0)
    return dif.getbbox()


# ================================================================ hablar con la IA

def llamar(preguntar, b64, mime, texto, fase, esfuerzo=None):
    """Llama a 'preguntar' con la fase si la acepta (las pruebas viejas mandan solo 3 argumentos)."""
    try:
        params = inspect.signature(preguntar).parameters
        acepta = "fase" in params or any(p.kind == p.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        acepta = False
    if acepta:
        return preguntar(b64, mime, texto, fase=fase, esfuerzo=esfuerzo)
    return preguntar(b64, mime, texto)


def _caja_de(valor):
    """[x0, y0, x1, y1] de lo que haya mandado la IA (lista o diccionario), o None."""
    if isinstance(valor, dict):
        if all(k in valor for k in ("x0", "y0", "x1", "y1")):
            valor = [valor["x0"], valor["y0"], valor["x1"], valor["y1"]]
        elif all(k in valor for k in ("x", "y", "w", "h")):
            valor = [valor["x"], valor["y"], motor._numero(valor["x"]) + motor._numero(valor["w"]),
                     motor._numero(valor["y"]) + motor._numero(valor["h"])]
        else:
            return None
    if not isinstance(valor, (list, tuple)) or len(valor) != 4:
        return None
    nums = [motor._numero(v) for v in valor]
    if any(n is None for n in nums):
        return None
    x0, y0, x1, y1 = nums
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return x0, y0, x1, y1


def expandir(caja, W, H, zoom=1.0, rel=0.05, px=28):
    x0, y0, x1, y1 = caja
    mx = px * zoom + rel * W
    my = px * zoom + rel * H
    x0, y0, x1, y1 = x0 - mx, y0 - my, x1 + mx, y1 + my
    min_w, min_h = 420 * zoom, 220 * zoom          # que nunca quede una tirita
    if x1 - x0 < min_w:
        c = (x0 + x1) / 2
        x0, x1 = c - min_w / 2, c + min_w / 2
    if y1 - y0 < min_h:
        c = (y0 + y1) / 2
        y0, y1 = c - min_h / 2, c + min_h / 2
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(W, int(math.ceil(x1))), min(H, int(math.ceil(y1)))
    return x0, y0, x1, y1


def _elegir_caja(caja, tam, puntero, margen=60):
    """Algunas IA mandan la caja en 0..1000 y al reves ([y0, x0, y1, x1]). Si asi como vino no queda cerca del
    puntero pero leida de otra forma si, se usa esa."""
    W, H = tam
    px, py = puntero
    a, b, c, d = caja
    opciones = [(a, b, c, d)]
    if max(caja) <= 1000:
        opciones.append((b * W / 1000, a * H / 1000, d * W / 1000, c * H / 1000))     # [y0, x0, y1, x1] / 1000
        opciones.append((a * W / 1000, b * H / 1000, c * W / 1000, d * H / 1000))     # [x0, y0, x1, y1] / 1000
    for o in opciones:
        x0, y0, x1, y1 = min(o[0], o[2]), min(o[1], o[3]), max(o[0], o[2]), max(o[1], o[3])
        if x0 - margen <= px <= x1 + margen and y0 - margen <= py <= y1 + margen:
            return x0, y0, x1, y1
    return opciones[0]


class Ubicacion:
    def __init__(self, region, tipo="", controles="", hay=True, salida="", respaldo=False):
        self.region = region            # (x0, y0, x1, y1) en pixeles de la captura
        self.tipo = tipo
        self.controles = controles
        self.hay = hay
        self.salida = salida
        self.respaldo = respaldo        # True si la IA no dio caja y se usa toda la captura


def ubicar(img, px, py, preguntar, zoom=1.0):
    """Fase 1: donde esta la pregunta y de que tipo es."""
    b64, mime, s, tam = preparar_imagen(img, puntero=(px, py), lado=1280, tokens=1200)
    texto = (f"FASE: UBICAR\nCaptura de {tam[0]}x{tam[1]} px (sin contar las reglas). "
             f"El puntero (circulo rojo) esta en ({int(px * s)},{int(py * s)}).")
    salida, _ = llamar(preguntar, b64, mime, texto, "ubicar")
    datos = motor.interpretar(salida)
    todo = (0, 0, img.width, img.height)
    if datos.get("hay_pregunta") is False:
        return Ubicacion(None, hay=False, salida=salida)
    if str(datos.get("tipo") or "").strip().lower() == "ninguna" and not any(k in datos for k in ("caja", "acciones", "ids", "id")):
        return Ubicacion(None, hay=False, salida=salida)
    caja = _caja_de(datos.get("caja"))
    tipo = str(datos.get("tipo") or "").strip().lower()
    controles = str(datos.get("controles") or "")[:200]
    if caja is None or s <= 0:
        return Ubicacion(todo, tipo, controles, salida=salida, respaldo=True)
    caja = _elegir_caja(caja, tam, (px * s, py * s))
    caja = tuple(v / s for v in caja)
    if caja[2] - caja[0] < 8 or caja[3] - caja[1] < 8:
        return Ubicacion(todo, tipo, controles, salida=salida, respaldo=True)
    return Ubicacion(expandir(caja, img.width, img.height, zoom), tipo, controles, salida=salida)


# ================================================================ leer de cerca

def leer(img, px, py, zoom, ocr):
    """OCR y campos para escribir de una imagen (ya recortada)."""
    import threading
    rects = {}

    def buscar():
        try:
            rects["r"] = motor.rectangulos(img, zoom)
        except Exception:
            rects["r"] = []

    hilo = threading.Thread(target=buscar, daemon=True)
    hilo.start()
    cajas = []
    if ocr is not None and getattr(ocr, "disponible", False):
        try:
            cajas = motor.detectar_cajas(img, px, py, zoom, ocr)
        except Exception:
            cajas = []
    hilo.join()
    campos = motor.filtrar_campos(rects.get("r", []), cajas, px, py)
    return cajas, campos


# ================================================================ de lo que dijo la IA a acciones seguras

def _a_lista_de_acciones(datos):
    """Las acciones de la IA; si contesto en el formato viejo (opcion/abierta) se convierten."""
    acc = datos.get("acciones")
    if isinstance(acc, list):
        return [a for a in acc if isinstance(a, dict)]
    tipo = str(datos.get("tipo") or "").strip().lower()
    salida = []
    if tipo.startswith("abiert") or "respuestas" in datos:
        entradas = datos.get("respuestas")
        if not isinstance(entradas, list):
            entradas = [{"campo": datos.get("id"), "texto": datos.get("respuesta"),
                         "x": datos.get("x"), "y": datos.get("y")}]
        for e in entradas:
            if not isinstance(e, dict):
                continue
            obj = e.get("campo", e.get("id"))
            if obj is None and e.get("x") is not None:
                obj = {"x": e.get("x"), "y": e.get("y")}
            salida.append({"hacer": "escribir", "en": obj, "texto": e.get("texto") or e.get("respuesta")})
        return salida
    if tipo == "ninguna":
        return []
    ids = datos.get("ids")
    if not isinstance(ids, list):
        ids = [datos.get("id")] if datos.get("id") is not None else []
        if not ids and datos.get("x") is not None:
            ids = [{"x": datos.get("x"), "y": datos.get("y")}]
    textos = [t.strip() for t in str(datos.get("respuesta") or "").split("|")]
    for i, obj in enumerate(ids):
        a = {"hacer": "clic", "en": obj}
        if len(textos) == len(ids) and textos[i]:
            a["texto"] = textos[i]
        salida.append(a)
    return salida


class Plan:
    def __init__(self):
        self.tipo = ""
        self.respuesta = ""
        self.pasos = []                 # acciones listas: dicts con 'hacer' y puntos en pixeles de la region
        self.rechazadas = []            # (accion, motivo)
        self.no_se_puede = ""
        self.seguro = "alto"
        self.datos = {}


def _campo_en(x, y, campos, radio):
    mejor = None
    for i, c in enumerate(campos):
        d = motor._distancia(x, y, c["caja"])
        if d <= radio and (mejor is None or d < mejor[0]):
            mejor = (d, i)
    return mejor[1] if mejor else None


def _caja_en(x, y, cajas):
    for i, c in enumerate(cajas):
        if motor._dentro(x, y, c["caja"], 2):
            return i
    return None


# ---------------------------------------------------------------- planos cartesianos: de coordenadas a pixeles

def _valor(texto):
    t = str(texto or "").strip().replace("\u2212", "-").replace("–", "-").replace(",", ".")
    t = t.replace(" ", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", t):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _ajuste(pares):
    """Recta pixel = a * valor + b por minimos cuadrados; None si no cuadra bien."""
    n = len(pares)
    if n < 3:
        return None
    sv = sum(v for v, _ in pares)
    sp = sum(p for _, p in pares)
    svv = sum(v * v for v, _ in pares)
    svp = sum(v * p for v, p in pares)
    den = n * svv - sv * sv
    if abs(den) < 1e-9:
        return None
    a = (n * svp - sv * sp) / den
    b = (sp - a * sv) / n
    if abs(a) < 1e-6:
        return None
    span = max(p for _, p in pares) - min(p for _, p in pares)
    if max(abs(a * v + b - p) for v, p in pares) > max(4.0, 0.03 * span):
        return None
    return a, b


def ejes(cajas):
    """Los numeros de los ejes de un plano (leidos con OCR) -> {"x": (a, b), "y": (a, b)} para pasar de coordenadas
    del plano a pixeles. Lo que no se pueda calcular queda en None."""
    nums = [(v, c) for c in cajas for v in [_valor(c["texto"])] if v is not None]
    out = {"x": None, "y": None}
    if len(nums) < 3:
        return out
    # eje x: numeros en un mismo renglon, crecen a la derecha
    mejor = None
    for v0, c0 in nums:
        fila = [(v, c) for v, c in nums if abs(c["cy"] - c0["cy"]) <= 7]
        if len(fila) >= 3 and (mejor is None or len(fila) > len(mejor)):
            mejor = fila
    if mejor:
        out["x"] = _ajuste([(v, c["cx"]) for v, c in mejor])
        if out["x"] and out["x"][0] <= 0:
            out["x"] = None
    # eje y: numeros en una misma columna (alineados a la derecha), crecen hacia arriba
    mejor = None
    for v0, c0 in nums:
        col = [(v, c) for v, c in nums if abs(c["caja"][2] - c0["caja"][2]) <= 8]
        if len(col) >= 3 and (mejor is None or len(col) > len(mejor)):
            mejor = col
    if mejor:
        out["y"] = _ajuste([(v, c["cy"]) for v, c in mejor])
        if out["y"] and out["y"][0] >= 0:
            out["y"] = None
    return out


def resolver(obj, cajas, campos, s, W, H, plano=None):
    """Lo que eligio la IA -> (x, y, i_caja, i_campo) en pixeles de la region, o None si no cuadra."""
    if isinstance(obj, str):
        mc = re.fullmatch(r"\s*[Cc]\s*(\d+)\s*", obj)
        if mc:
            i = int(mc.group(1))
            if 0 <= i < len(campos):
                return campos[i]["cx"], campos[i]["cy"], None, i
            return None
        obj = obj.strip()
    if isinstance(obj, dict):
        if "fila" in obj and "columna" in obj:
            f, c = motor._numero(obj.get("fila")), motor._numero(obj.get("columna"))
            if f is None or c is None or not float(f).is_integer() or not float(c).is_integer():
                return None
            f, c = int(f), int(c)
            if not (0 <= f < len(cajas) and 0 <= c < len(cajas)):
                return None
            return cajas[c]["cx"], cajas[f]["cy"], None, None
        x, y = motor._numero(obj.get("x")), motor._numero(obj.get("y"))
        gx, gy = motor._numero(obj.get("gx")), motor._numero(obj.get("gy"))
        if (gx is not None or gy is not None) and s > 0:
            plano = plano if plano is not None else ejes(cajas)
            if gx is not None:
                if not plano["x"]:
                    return None          # sin numeros en el eje no se adivina
                x = (plano["x"][0] * gx + plano["x"][1]) * s
            if gy is not None:
                if not plano["y"]:
                    return None
                y = (plano["y"][0] * gy + plano["y"][1]) * s
        if x is None or y is None or s <= 0:
            return None
        x, y = x / s, y / s
        if not (0 <= x < W and 0 <= y < H):
            return None                  # fuera de la pregunta: no
        return x, y, _caja_en(x, y, cajas), None
    n = motor._numero(obj)
    if n is not None and float(n).is_integer():
        i = int(n)
        if 0 <= i < len(cajas):
            return cajas[i]["cx"], cajas[i]["cy"], i, None
    return None


def refinar_campo(img, x, y, zoom=1.0):
    """Busca un rectangulo (campo para escribir) que contenga el punto o este pegado a el: primero de cerca y luego
    mas amplio (campos anchos de ensayo). Devuelve (cx, cy, caja) o None."""
    for rx, ry in ((140, 90), (560, 200)):
        rx, ry = int(rx * zoom), int(ry * zoom)
        zona = (max(0, int(x - rx)), max(0, int(y - ry)), min(img.width, int(x + rx)), min(img.height, int(y + ry)))
        if zona[2] - zona[0] < 10 or zona[3] - zona[1] < 10:
            continue
        mejor = None
        for r in motor.rectangulos(img.crop(zona), zoom, relajado=True):
            c = (r[0] + zona[0], r[1] + zona[1], r[2] + zona[0], r[3] + zona[1])
            d = motor._distancia(x, y, c)
            if d > 30 * zoom:
                continue
            clave = (d, (c[2] - c[0]) * (c[3] - c[1]))
            if mejor is None or clave < mejor[0]:
                mejor = (clave, c)
        if mejor is not None:
            c = mejor[1]
            return (c[0] + c[2]) / 2, (c[1] + c[3]) / 2, c
    return None


def _corregir_id(i, texto, cajas):
    """Si la IA puso un id cuyo texto no es el de su respuesta (error por uno), busca la caja correcta."""
    if i is None or not texto or not cajas:
        return i
    actual = motor.parecido(texto, cajas[i]["texto"])
    if actual >= 0.6:
        return i
    puntajes = [(motor.parecido(texto, c["texto"]), j) for j, c in enumerate(cajas)]
    mejor = max(p for p, _ in puntajes)
    if mejor >= 0.75 and mejor - actual >= 0.25:
        empatados = [j for p, j in puntajes if p >= mejor - 0.05]
        return min(empatados, key=lambda j: math.hypot(cajas[j]["cx"] - cajas[i]["cx"], cajas[j]["cy"] - cajas[i]["cy"]))
    return i


def planear(datos, cajas, campos, s, region_img, zoom=1.0):
    """Revisa cada accion de la IA contra el candado. Puntos en pixeles de la region (la imagen recortada)."""
    plan = Plan()
    plan.datos = datos
    plan.tipo = str(datos.get("tipo") or "").strip().lower()
    plan.respuesta = motor.limpiar_respuesta(str(datos.get("respuesta") or ""))
    plan.no_se_puede = str(datos.get("no_se_puede") or "").strip()
    plan.seguro = str(datos.get("seguro") or "alto").strip().lower()
    W, H = region_img.size
    vistos = set()
    plano = ejes(cajas)

    def _res(obj):
        return resolver(obj, cajas, campos, s, W, H, plano)

    def rechazar(a, motivo):
        plan.rechazadas.append((a, motivo))

    for a in _a_lista_de_acciones(datos)[:MAX_ACCIONES]:
        hacer = str(a.get("hacer") or a.get("accion") or "").strip().lower()
        if hacer in ("marcar", "seleccionar", "click"):
            hacer = "clic"
        if hacer in ("teclear", "write", "type"):
            hacer = "escribir"
        if hacer in ("menu", "desplegable", "select"):
            hacer = "elegir"
        if hacer in ("mover", "drag", "soltar"):
            hacer = "arrastrar"

        if hacer == "clic":
            obj = a.get("en", a.get("id"))
            r = _res(obj)
            if r is None:
                rechazar(a, "fuera de la pregunta o no existe")
                continue
            x, y, i, _ = r
            es_id = not isinstance(obj, dict) and motor._numero(obj) is not None
            if i is not None and es_id:
                j = _corregir_id(i, a.get("texto"), cajas)
                if j != i:
                    i = j
                    x, y = cajas[i]["cx"], cajas[i]["cy"]
            texto_caja = cajas[i]["texto"] if i is not None else ""
            if i is not None and es_navegacion(texto_caja):
                rechazar(a, f"es un boton para avanzar o mandar ({texto_caja})")
                continue
            clave = (round(x / 6), round(y / 6))
            if clave in vistos:
                continue                 # el mismo clic dos veces desmarcaria la casilla
            vistos.add(clave)
            plan.pasos.append({"hacer": "clic", "p": (x, y), "desc": texto_caja or a.get("texto") or "punto",
                               "caja": cajas[i]["caja"] if i is not None else None})

        elif hacer == "escribir":
            texto = motor.limpiar_respuesta(str(a.get("texto") or ""))
            if not texto:
                continue
            obj = a.get("en", a.get("campo", a.get("id")))
            if obj is None and a.get("x") is not None:
                obj = {"x": a.get("x"), "y": a.get("y")}
            r = _res(obj)
            if r is None:
                rechazar(a, "no hay un campo para escribir ahi")
                continue
            x, y, i, k = r
            if k is None:
                # solo se escribe en campos de verdad: uno detectado cerca, o un rectangulo alrededor del punto
                k = _campo_en(x, y, campos, 40 * zoom)
                if k is None and i is not None:
                    for kk, c in enumerate(campos):
                        if motor._dentro(c["cx"], c["cy"], cajas[i]["caja"]) or motor._dentro(cajas[i]["cx"], cajas[i]["cy"], c["caja"]):
                            k = kk
                            break
            if k is not None:
                x, y = campos[k]["cx"], campos[k]["cy"]
                caja = campos[k]["caja"]
            else:
                fino = refinar_campo(region_img, x, y, zoom)
                if not fino:
                    rechazar(a, "no se ve un campo para escribir ahi")
                    continue
                x, y, caja = fino
            if i is not None and es_navegacion(cajas[i]["texto"]):
                rechazar(a, "es un boton")
                continue
            plan.pasos.append({"hacer": "escribir", "p": (x, y), "texto": texto, "caja": caja})

        elif hacer == "elegir":
            opcion = str(a.get("opcion") or a.get("texto") or "").strip()
            r = _res(a.get("en", a.get("id")))
            if r is None or not opcion:
                rechazar(a, "menu u opcion no validos")
                continue
            x, y, i, _ = r
            if i is not None and es_navegacion(cajas[i]["texto"]):
                rechazar(a, "es un boton")
                continue
            plan.pasos.append({"hacer": "elegir", "p": (x, y), "opcion": opcion,
                               "desc": cajas[i]["texto"] if i is not None else "menu"})

        elif hacer == "arrastrar":
            r1 = _res(a.get("desde"))
            r2 = _res(a.get("hasta"))
            if r1 is None or r2 is None:
                rechazar(a, "arrastre fuera de la pregunta")
                continue
            if math.hypot(r2[0] - r1[0], r2[1] - r1[1]) < 12:
                rechazar(a, "arrastre de cero")
                continue
            if r1[2] is not None and es_navegacion(cajas[r1[2]]["texto"]):
                rechazar(a, "es un boton")
                continue
            plan.pasos.append({"hacer": "arrastrar", "p": (r1[0], r1[1]), "p2": (r2[0], r2[1]),
                               "desc": cajas[r1[2]]["texto"] if r1[2] is not None else "elemento"})

        elif hacer == "ordenar":
            orden = [str(t).strip() for t in (a.get("orden") or []) if str(t).strip()]
            if len(orden) < 2:
                rechazar(a, "orden vacio")
                continue
            plan.pasos.append({"hacer": "ordenar", "orden": orden[:15]})
        elif hacer:
            rechazar(a, f"accion desconocida: {hacer}")

    if plan.seguro == "bajo" and plan.pasos:
        for p in plan.pasos:
            plan.rechazadas.append((p, "la IA no estaba segura de como contestarla en pantalla"))
        plan.pasos = []
    return plan


# ================================================================ hacer las acciones

def _escribir_con_teclas(acciones, texto, cancelar):
    """Escribe el texto; {derecha}, {izquierda}, {arriba}, {abajo} y {retroceso} se mandan como teclas."""
    partes = re.split(r"\{(derecha|izquierda|arriba|abajo|retroceso)\}", texto)
    for k, parte in enumerate(partes):
        if k % 2 == 1:
            if hasattr(acciones, "tecla"):
                acciones.tecla(parte)
                time.sleep(0.05)
        elif parte:
            acciones.escribir(parte, cancelar)


class Ejecutor:
    """Hace las acciones de un plan con calma, revisando que cada clic se haya registrado.

    region: (x0, y0, x1, y1) de la pregunta en pixeles de la captura; left/top: donde empieza la captura en pantalla.
    foto(): foto nueva de la region (misma medida) o None; foto_todo(): foto nueva de toda la captura o None.
    """

    def __init__(self, acciones, left, top, region, cancelar=None, foto=None, foto_todo=None, ocr=None, zoom=1.0,
                 pausa=PAUSA):
        self.a = acciones
        self.left, self.top = left, top
        self.region = region
        self.cancelar = cancelar or (lambda: False)
        self.foto = foto or (lambda: None)
        self.foto_todo = foto_todo or (lambda: None)
        self.ocr = ocr
        self.zoom = zoom
        self.pausa = pausa
        self.hecho = {"clic": 0, "escribir": 0, "elegir": 0, "arrastrar": 0, "ordenar": 0}
        self.fallas = []
        self.marcados = []               # textos de lo que se marco (para avisar)
        self.escritos = []

    def pantalla(self, x, y):
        return self.left + self.region[0] + x, self.top + self.region[1] + y

    def _revisar_cancelar(self):
        if self.cancelar() or self.a.tecla_abajo(self.a.VK_ESCAPE):
            raise self.a.Cancelado()

    def correr(self, pasos):
        antes = self.foto()
        for paso in pasos:
            self._revisar_cancelar()
            hacer = paso["hacer"]
            try:
                if hacer == "clic":
                    antes = self._clic(paso, antes)
                elif hacer == "escribir":
                    antes = self._escribir(paso, antes)
                elif hacer == "elegir":
                    antes = self._elegir(paso, antes)
                elif hacer == "arrastrar":
                    antes = self._arrastrar(paso, antes)
                elif hacer == "ordenar":
                    antes = self._ordenar(paso, antes)
            except self.a.Cancelado:
                raise
            except Exception as e:      # una accion que falla no tumba las demas
                self.fallas.append((paso, f"{type(e).__name__}: {e}"))
        return self.hecho

    # ---- cada accion
    def _clic(self, paso, antes):
        X, Y = self.pantalla(*paso["p"])
        if hasattr(self.a, "mover"):
            # primero solo se pone encima: asi el "antes" ya trae el efecto de pasar el mouse y si despues del
            # clic no cambia nada es que el clic de verdad no se registro
            self.a.mover(X, Y)
            time.sleep(0.15)
            antes = self.foto() or antes
        self.a.clic(X, Y)
        time.sleep(self.pausa)
        despues = self.foto()
        if antes is not None and despues is not None and not hubo_cambio(antes, despues):
            # no cambio NADA en toda la pregunta: el clic no se registro (la pagina iba lenta); otra vez
            self._revisar_cancelar()
            self.a.clic(X, Y)
            time.sleep(self.pausa + 0.15)
            despues = self.foto()
            if not hubo_cambio(antes, despues):
                self.fallas.append((paso, "el clic no cambio nada"))
        self.hecho["clic"] += 1
        self.marcados.append(paso.get("desc") or "")
        return despues

    def _escribir(self, paso, antes):
        X, Y = self.pantalla(*paso["p"])
        self.a.clic(X, Y)
        time.sleep(0.3)
        self.a.seleccionar_todo()
        time.sleep(0.06)
        _escribir_con_teclas(self.a, paso["texto"], self.cancelar)
        time.sleep(0.25)
        self.hecho["escribir"] += 1
        self.escritos.append(paso["texto"])
        foto = self.foto()
        paso["ok_local"] = self._se_lee(foto, paso["p"], paso.get("caja"), paso["texto"])
        return foto

    def _se_lee(self, foto, punto, caja, esperado):
        """True si con OCR se lee el texto esperado en ese lugar (asi no hace falta preguntarle a la IA)."""
        if foto is None or self.ocr is None or not esperado or re.search(r"[{}^/√]", esperado):
            return False
        x, y = punto
        if caja:
            zona = (caja[0] - 6, caja[1] - 6, caja[2] + 6, caja[3] + 6)
        else:
            zona = (x - 320 * self.zoom, y - 30 * self.zoom, x + 320 * self.zoom, y + 30 * self.zoom)
        zona = (int(max(0, zona[0])), int(max(0, zona[1])), int(min(foto.width, zona[2])), int(min(foto.height, zona[3])))
        if zona[2] - zona[0] < 8 or zona[3] - zona[1] < 8:
            return False
        try:
            trozo = foto.crop(zona)
            cajas = motor.detectar_cajas(trozo, trozo.width / 2, trozo.height / 2, self.zoom, self.ocr)
        except Exception:
            return False
        leido = motor._norm(" ".join(c["texto"] for c in cajas))
        buscado = motor._norm(esperado)[:40]
        if not buscado or not leido:
            return False
        return buscado in leido or motor.parecido(buscado, leido[:len(buscado) + 10]) >= 0.8

    def _elegir(self, paso, antes):
        X, Y = self.pantalla(*paso["p"])
        todo_antes = self.foto_todo()
        self.a.clic(X, Y)
        time.sleep(0.55)
        todo_despues = self.foto_todo()
        if todo_antes is None or todo_despues is None or self.ocr is None:
            self.fallas.append((paso, "no se pudo ver el menu"))
            return self.foto()
        zona = zona_cambiada(todo_antes, todo_despues)
        if zona is None:
            time.sleep(0.4)              # menus que abren con animacion
            todo_despues = self.foto_todo()
            zona = zona_cambiada(todo_antes, todo_despues)
        mascara = ImageChops.difference(todo_antes.convert("L"), todo_despues.convert("L")).point(
            lambda v: 255 if v > 10 else 0) if zona is not None else None
        if zona is None:
            self.fallas.append((paso, "no se abrio el menu"))
            return self.foto()
        m = int(12 * self.zoom)
        zx0, zy0 = max(0, zona[0] - m), max(0, zona[1] - m)
        zx1, zy1 = min(todo_despues.width, zona[2] + m), min(todo_despues.height, zona[3] + m)
        menu = todo_despues.crop((zx0, zy0, zx1, zy1))
        cajas = motor.detectar_cajas(menu, menu.width / 2, menu.height / 2, self.zoom, self.ocr)

        def aparecio(c):              # solo cuenta lo que aparecio con el menu (no el mismo texto en la pregunta)
            x0, y0, x1, y1 = c["caja"]
            trozo = mascara.crop((int(zx0 + x0), int(zy0 + y0), int(zx0 + x1) + 1, int(zy0 + y1) + 1))
            return trozo.histogram()[255] >= 4
        puntajes = sorted(((motor.parecido(paso["opcion"], c["texto"]), i) for i, c in enumerate(cajas) if aparecio(c)),
                          reverse=True)
        if not puntajes or puntajes[0][0] < 0.72:
            self.a.clic(X, Y)            # se cierra el menu (otro clic en el mismo menu)
            time.sleep(0.3)
            self.fallas.append((paso, f"no encontre la opcion '{paso['opcion']}' en el menu"))
            return self.foto()
        c = cajas[puntajes[0][1]]
        self.a.clic(self.left + zx0 + c["cx"], self.top + zy0 + c["cy"])
        time.sleep(self.pausa + 0.1)
        self.hecho["elegir"] += 1
        self.marcados.append(paso["opcion"])
        foto = self.foto()
        paso["ok_local"] = self._se_lee(foto, paso["p"], None, paso["opcion"])
        return foto

    def _arrastrar(self, paso, antes):
        X0, Y0 = self.pantalla(*paso["p"])
        X1, Y1 = self.pantalla(*paso["p2"])
        self.a.arrastrar(X0, Y0, X1, Y1, cancelar=self.cancelar)
        time.sleep(0.45)
        despues = self.foto()
        if antes is not None and despues is not None and not hubo_cambio(antes, despues):
            self._revisar_cancelar()
            self.a.arrastrar(X0, Y0, X1, Y1, cancelar=self.cancelar)
            time.sleep(0.5)
            despues = self.foto()
            if not hubo_cambio(antes, despues):
                self.fallas.append((paso, "el arrastre no movio nada"))
        self.hecho["arrastrar"] += 1
        return despues

    def _ordenar(self, paso, antes):
        """Va acomodando de arriba a abajo: el que debe ir en el lugar i se arrastra al lugar i (relee cada vez)."""
        if self.ocr is None:
            self.fallas.append((paso, "sin OCR para ordenar"))
            return antes
        orden = paso["orden"]
        movidas = 0
        for _ in range(len(orden) + 3):
            self._revisar_cancelar()
            foto = self.foto()
            if foto is None:
                self.fallas.append((paso, "no se pudo ver la lista"))
                break
            cajas = motor.detectar_cajas(foto, foto.width / 2, foto.height / 2, self.zoom, self.ocr)
            elegidas, usadas = [], set()
            for texto in orden:
                mejor = max(((motor.parecido(texto, c["texto"]), i) for i, c in enumerate(cajas) if i not in usadas),
                            default=(0, None))
                if mejor[1] is None or mejor[0] < 0.6:
                    elegidas = None
                    break
                usadas.add(mejor[1])
                elegidas.append(cajas[mejor[1]])
            if not elegidas:
                self.fallas.append((paso, "no encontre todos los elementos para ordenar"))
                break
            ys = [c["cy"] for c in elegidas]
            xs = [c["cx"] for c in elegidas]
            vertical = (max(ys) - min(ys)) >= (max(xs) - min(xs))
            actuales = sorted(elegidas, key=lambda c: c["cy"] if vertical else c["cx"])
            fuera = next((i for i, c in enumerate(elegidas) if actuales[i] is not c), None)
            if fuera is None:
                self.hecho["ordenar"] += 1
                return foto
            mover, destino = elegidas[fuera], actuales[fuera]
            x0, y0 = mover["cx"], mover["cy"]
            if vertical:
                x1, y1 = destino["cx"], destino["caja"][1] + (destino["caja"][3] - destino["caja"][1]) * 0.25
            else:
                x1, y1 = destino["caja"][0] + (destino["caja"][2] - destino["caja"][0]) * 0.25, destino["cy"]
            X0, Y0 = self.pantalla(x0, y0)
            X1, Y1 = self.pantalla(x1, y1)
            self.a.arrastrar(X0, Y0, X1, Y1, cancelar=self.cancelar)
            movidas += 1
            time.sleep(0.6)
        else:
            self.fallas.append((paso, "no quedo en orden"))
        return self.foto()


# ================================================================ resumen de lo que se hizo (para avisar y para revisar)

def describir(pasos):
    out = []
    for p in pasos:
        if p["hacer"] == "clic":
            out.append(f"clic en '{p.get('desc') or 'punto'}'")
        elif p["hacer"] == "escribir":
            out.append(f"escribir '{p['texto'][:80]}'")
        elif p["hacer"] == "elegir":
            out.append(f"elegir '{p['opcion']}' en el menu '{p.get('desc') or ''}'")
        elif p["hacer"] == "arrastrar":
            out.append(f"arrastrar '{p.get('desc') or 'elemento'}'")
        elif p["hacer"] == "ordenar":
            out.append("ordenar: " + " > ".join(p["orden"]))
    return "; ".join(out)


def necesita_revision(plan, ejecutor):
    """La revision con la IA se salta solo en lo mas simple: un clic en una pregunta de una sola respuesta que si se
    registro. Todo lo demas (casillas, campos, menus, arrastrar, algo que fallo o se rechazo) se revisa."""
    if ejecutor.fallas or plan.rechazadas:
        return True
    tipos = {p["hacer"] for p in plan.pasos}
    if tipos and tipos <= {"escribir", "elegir"} and all(p.get("ok_local") for p in plan.pasos):
        return False                     # todo se lee bien en su lugar: no hace falta gastar otra pregunta
    if tipos & {"elegir", "arrastrar", "ordenar", "escribir"}:
        return True
    clics = sum(1 for p in plan.pasos if p["hacer"] == "clic")
    if clics == 1 and plan.tipo in ("opcion_unica", "verdadero_falso", "zona_clic", "opcion", ""):
        return False
    return clics >= 1


def revisar(foto, plan, preguntar, ocr, zoom=1.0):
    """Fase 3: con la foto de como quedo, la IA dice si esta bien o que corregir. Devuelve un Plan (vacio si ok)."""
    cajas, campos = leer(foto, foto.width / 2, foto.height / 2, zoom, ocr)
    b64, mime, s, tam = preparar_imagen(foto, campos)
    texto = ("FASE: REVISAR\n"
             f"Respuesta que se queria dejar: {plan.respuesta or '(ver acciones)'}\n"
             f"Acciones que se hicieron: {describir(plan.pasos)}\n" + texto_cajas(cajas, campos, s, tam))
    salida, _ = llamar(preguntar, b64, mime, texto, "revisar")
    datos = motor.interpretar(salida)
    vacio = Plan()
    if datos.get("ok") is not False:
        return vacio, salida
    correccion = planear({"acciones": datos.get("acciones") or [], "respuesta": plan.respuesta,
                          "tipo": plan.tipo}, cajas, campos, s, foto, zoom)
    return correccion, salida


def guardar_revision(carpeta, img, region, cajas, campos, pasos):
    import os
    try:
        os.makedirs(carpeta, exist_ok=True)
        img.save(os.path.join(carpeta, "ultima_captura.png"))
        rx, ry = region[0], region[1]
        rev = img.crop(region).copy()
        dib = ImageDraw.Draw(rev)
        for i, c in enumerate(cajas):
            dib.rectangle(c["caja"], outline=(0, 160, 255), width=1)
            dib.text((c["caja"][0], max(0, c["caja"][1] - 11)), str(i), fill=(0, 160, 255))
        for i, c in enumerate(campos):
            dib.rectangle(c["caja"], outline=motor.MORADO, width=2)
            dib.text((c["caja"][0], max(0, c["caja"][1] - 11)), f"C{i}", fill=motor.MORADO)
        for n, p in enumerate(pasos, 1):
            if "p" in p:
                x, y = p["p"]
                dib.ellipse((x - 10, y - 10, x + 10, y + 10), outline=(0, 200, 0), width=4)
                dib.text((x + 12, y - 6), str(n), fill=(0, 160, 0))
            if "p2" in p:
                dib.line((p["p"][0], p["p"][1], p["p2"][0], p["p2"][1]), fill=(0, 200, 0), width=3)
        rev.save(os.path.join(carpeta, "ultima_revision.png"))
        with open(os.path.join(carpeta, "ultima_region.json"), "w", encoding="utf-8") as f:
            json.dump({"region": list(region), "inicio": [rx, ry],
                       "pasos": [{k: v for k, v in p.items() if k != "caja"} for p in pasos]},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass
