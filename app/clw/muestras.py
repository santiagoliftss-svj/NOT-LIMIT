"""Pantallas de prueba dibujadas a mano (para las pruebas y la autoprueba del .exe)."""

from PIL import Image, ImageDraw, ImageFont

from . import rutas


def _f(tam, peso=500, ancho=100):
    f = ImageFont.truetype(rutas.asset("fuentes", "Archivo.ttf"), tam, layout_engine=ImageFont.Layout.BASIC)
    try:
        f.set_variation_by_axes([peso, ancho])
    except Exception:
        pass
    return f


def quiz_oscuro():
    """Quiz oscuro con opciones en dos columnas. Devuelve (img, tarjetas{texto: caja}, puntero)."""
    img = Image.new("RGB", (960, 640), (10, 14, 26))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((60, 40, 900, 600), 24, fill=(17, 24, 39))
    d.text((100, 80), "1. ¿Cuál es la capital de Francia?", font=_f(24, 700), fill=(240, 240, 245))
    opciones = ["Madrid", "París", "Roma", "Berlín"]
    tarjetas = {}
    for i, op in enumerate(opciones):
        x = 100 if i % 2 == 0 else 490
        y = 140 + (i // 2) * 80
        caja = (x, y, x + 360, y + 60)
        d.rounded_rectangle(caja, 14, fill=(30, 41, 59), outline=(51, 65, 85), width=1)
        d.ellipse((x + 22, y + 21, x + 40, y + 39), outline=(230, 230, 230), width=2)
        d.text((x + 58, y + 18), op, font=_f(20, 500), fill=(226, 232, 240))
        tarjetas[op] = caja
    d.text((100, 340), "2. ¿Cuánto es 7 × 8?", font=_f(24, 700), fill=(240, 240, 245))
    for i, op in enumerate(["54", "56", "64", "48"]):
        x = 100 if i % 2 == 0 else 490
        y = 400 + (i // 2) * 80
        caja = (x, y, x + 360, y + 60)
        d.rounded_rectangle(caja, 14, fill=(30, 41, 59), outline=(51, 65, 85), width=1)
        d.ellipse((x + 22, y + 21, x + 40, y + 39), outline=(230, 230, 230), width=2)
        d.text((x + 58, y + 18), op, font=_f(20, 500), fill=(226, 232, 240))
        tarjetas["q2_" + op] = caja
    return img, tarjetas, (200, 92)


def formulario_claro():
    """Formulario claro con dos preguntas abiertas. Devuelve (img, cajas_de_texto, puntero)."""
    img = Image.new("RGB", (1100, 700), (243, 242, 241))
    d = ImageDraw.Draw(img)
    d.rectangle((150, 50, 950, 320), fill="white")
    d.text((180, 80), "1. ¿En qué año inició la Revolución Mexicana?", font=_f(21, 500), fill=(30, 30, 30))
    caja1 = (180, 130, 850, 176)
    d.rectangle(caja1, outline=(150, 150, 150), width=1)
    d.text((196, 143), "Escriba su respuesta", font=_f(17, 400), fill=(140, 140, 140))
    d.rectangle((150, 350, 950, 680), fill="white")
    d.text((180, 380), "2. Explica las causas de la Independencia de México.", font=_f(21, 500), fill=(30, 30, 30))
    caja2 = (180, 430, 850, 600)
    d.rectangle(caja2, outline=(150, 150, 150), width=1)
    d.text((196, 443), "Escriba su respuesta", font=_f(17, 400), fill=(140, 140, 140))
    return img, [caja1, caja2], (300, 90)


def pantalla_mixta():
    """Pantalla con partes oscuras (consola) y una ventana blanca con un campo de texto de borde fino.
    Devuelve (img, caja_del_campo, puntero)."""
    img = Image.new("RGB", (1024, 768), (12, 12, 12))
    d = ImageDraw.Draw(img)
    for i in range(30):
        d.text((20, 10 + i * 25), '{"level":"INFO","ts":1793315075,"msg":"job started"}' * 2, font=_f(15, 400),
               fill=(200, 200, 200))
    d.rectangle((0, 0, 820, 390), fill="white")
    d.rectangle((0, 0, 820, 30), fill=(240, 240, 240))
    d.text((12, 6), "Prueba", font=_f(14, 400), fill=(30, 30, 30))
    d.text((48, 72), "1. ¿Cuánto es dos más dos?", font=_f(26, 400), fill=(34, 34, 34))
    caja = (48, 141, 648, 185)
    d.rectangle(caja, outline=(0, 0, 0), width=1)
    d.text((52, 150), "Escriba su respuesta", font=_f(22, 400), fill=(136, 136, 136))
    d.rounded_rectangle((330, 420, 710, 700), 12, fill=(0, 0, 0), outline=(60, 60, 60))
    d.rounded_rectangle((402, 440, 638, 504), 32, fill=(255, 255, 255))
    return img, caja, (160, 86)


def cajitas_mate():
    """Tres cajitas azules chiquitas tipo plataforma de mate. Devuelve (img, cajitas, puntero)."""
    img = Image.new("RGB", (700, 520), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((60, 40, 460, 470), outline=(40, 40, 40), width=1)
    cajitas = []
    for i, nombre in enumerate(["sec θ", "sen θ", "tan θ"]):
        y = 110 + i * 120
        d.text((100, y), nombre, font=_f(22, 400), fill=(30, 30, 30))
        d.text((190, y), "=", font=_f(22, 400), fill=(30, 30, 30))
        caja = (232, y - 6, 246, y + 30)
        d.rectangle(caja, outline=(80, 80, 255), width=2)
        cajitas.append(caja)
    return img, cajitas, (120, 60)
