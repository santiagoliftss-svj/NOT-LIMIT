"""Genera la marca NO LIMIT (logo 3D sin fondo), los iconos, las imagenes del instalador y las de la pagina.

El logo sale de herramientas/logo_nolimit.png (letras blancas 3D sobre negro puro).
Uso (desde la raiz del repo):  python herramientas/generar_assets.py
"""

import os

from PIL import Image, ImageChops, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
LOGO = os.path.join(AQUI, "logo_nolimit.png")
ASSETS = os.path.join(RAIZ, "app", "assets")
INSTALADOR = os.path.join(RAIZ, "installer", "imagenes")
WEB = os.path.join(RAIZ, "docs", "assets")


def _original():
    im = Image.open(LOGO).convert("RGB")
    caja = im.convert("L").point(lambda v: 255 if v > 6 else 0).getbbox()
    pad = 6
    caja = (max(0, caja[0] - pad), max(0, caja[1] - pad), min(im.width, caja[2] + pad), min(im.height, caja[3] + pad))
    return im.crop(caja)


def sin_fondo(im):
    """Quita el negro: lo oscuro del borde se vuelve transparente (rampa suave), las letras quedan igual."""
    lum = im.convert("L")
    alfa = lum.point(lambda v: 0 if v <= 5 else 255 if v >= 34 else int((v - 5) * 255 / 29))
    out = im.convert("RGBA")
    out.putalpha(alfa)
    return out


def marca():
    return sin_fondo(_original())


def _no():
    """Solo 'NO' (para el icono). La L se encima en la O, asi que el lado derecho se desvanece."""
    im = _original()
    k = im.width / 1214                       # medidas tomadas sobre el logo de 1214 px de ancho
    c = im.crop((0, 0, int(436 * k), im.height))
    m = Image.new("L", c.size, 255)
    d = ImageDraw.Draw(m)
    fade = int(64 * k)
    for i in range(fade):
        x = c.width - fade + i
        d.line((x, 0, x, c.height), fill=int(255 * (1 - i / fade) ** 1.6))
    return Image.composite(c, Image.new("RGB", c.size, (0, 0, 0)), m)


def icono(tam=1024, apagado=False):
    """Cuadro negro redondeado con el NO 3D."""
    base = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle((0, 0, tam - 1, tam - 1), int(tam * 0.22), fill=(0, 0, 0, 255))
    no = sin_fondo(_no())
    if apagado:
        r, g, b, a = no.split()
        no = Image.merge("RGBA", [c.point(lambda v: int(v * 0.42)) for c in (r, g, b)] + [a])
    lado = tam * (0.86 if tam > 24 else 0.94)
    k = lado / max(no.width, no.height)
    no = no.resize((max(1, int(no.width * k)), max(1, int(no.height * k))), Image.LANCZOS)
    base.alpha_composite(no, ((tam - no.width) // 2, (tam - no.height) // 2))
    return base


def lateral(w, h):
    """Franja del instalador: negro total con el logo en vertical."""
    im = Image.new("RGB", (w, h), (0, 0, 0))
    lg = _original().rotate(90, expand=True, resample=Image.BICUBIC)
    k = min((h * 0.86) / lg.height, (w * 0.86) / lg.width)
    lg = lg.resize((max(1, int(lg.width * k)), max(1, int(lg.height * k))), Image.LANCZOS)
    im.paste(lg, ((w - lg.width) // 2, (h - lg.height) // 2))
    return im


def _ico(destino, imagenes):
    tamanos = sorted(imagenes, reverse=True)
    imagenes[tamanos[0]].save(destino, sizes=[(t, t) for t in tamanos],
                              append_images=[imagenes[t] for t in tamanos[1:]])


def main():
    for carpeta in (ASSETS, INSTALADOR, WEB):
        os.makedirs(carpeta, exist_ok=True)
    for viejo in (os.path.join(ASSETS, "marca.json"), os.path.join(WEB, "marca.json")):
        if os.path.exists(viejo):
            os.remove(viejo)

    mk = marca()
    k = 1400 / mk.width
    mk = mk.resize((1400, int(mk.height * k)), Image.LANCZOS)
    mk.save(os.path.join(ASSETS, "marca.png"), optimize=True)
    mk.save(os.path.join(WEB, "marca.png"), optimize=True)
    mk.save(os.path.join(WEB, "marca.webp"), "WEBP", quality=90, method=6)

    grande = icono(1024)
    grande.resize((256, 256), Image.LANCZOS).save(os.path.join(ASSETS, "icono.png"))
    _ico(os.path.join(ASSETS, "icono.ico"),
         {t: (icono(t) if t <= 48 else grande.resize((t, t), Image.LANCZOS)) for t in (256, 128, 64, 48, 32, 24, 16)})
    grande.resize((180, 180), Image.LANCZOS).save(os.path.join(WEB, "icono-180.png"))
    grande.resize((64, 64), Image.LANCZOS).save(os.path.join(WEB, "favicon.png"))

    # junto al reloj: prendido / apagado (tenue)
    for nombre, apagado in (("bandeja", False), ("bandeja_apagado", True)):
        ims = {t: icono(t, apagado) for t in (64, 48, 40, 32, 24, 20, 16)}
        ims[64].save(os.path.join(ASSETS, nombre + ".png"))
        if not apagado:
            ims[64].save(os.path.join(WEB, "bandeja.png"), optimize=True)
        _ico(os.path.join(ASSETS, nombre + ".ico"), ims)

    for pct, (w, h), (cw, ch) in [(100, (164, 314), (58, 58)), (125, (205, 393), (73, 73)),
                                  (150, (246, 471), (87, 87)), (200, (328, 628), (116, 116))]:
        lateral(w, h).save(os.path.join(INSTALADOR, f"lateral_{pct}.bmp"))
        chico = Image.new("RGB", (cw, ch), (0, 0, 0))
        i = icono(cw)
        chico.paste(i, (0, 0), i)
        chico.save(os.path.join(INSTALADOR, f"chico_{pct}.bmp"))

    # imagen para compartir el link
    og = Image.new("RGB", (1200, 630), (0, 0, 0))
    lg = _original()
    k = min(1000 / lg.width, 500 / lg.height)
    lg = lg.resize((int(lg.width * k), int(lg.height * k)), Image.LANCZOS)
    og.paste(lg, ((1200 - lg.width) // 2, (630 - lg.height) // 2))
    og.save(os.path.join(WEB, "compartir.png"), optimize=True)
    print("listo", mk.size)


if __name__ == "__main__":
    main()
