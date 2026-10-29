"""Genera el logo de cromo, el icono, las imagenes del instalador y las de la pagina.

Uso (desde la raiz del repo):  python herramientas/generar_assets.py
"""

import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)

from cromo import cromo, destello, mascara  # noqa: E402

FUENTE = os.path.join(AQUI, "NewRocker-Regular.ttf")
ASSETS = os.path.join(RAIZ, "app", "assets")
INSTALADOR = os.path.join(RAIZ, "installer", "imagenes")
WEB = os.path.join(RAIZ, "docs", "assets")


def wordmark():
    m = mascara("CLW GANG", FUENTE, 320, tracking=10, pad=110)
    c = cromo(m, glow=0.22)
    bb = m.getbbox()
    w = bb[2] - bb[0]
    h = bb[3] - bb[1]
    c = destello(c, int(bb[0] + w * 0.175), int(bb[1] + h * 0.10), h * 0.30)
    c = destello(c, int(bb[0] + w * 0.955), int(bb[1] + h * 0.86), h * 0.18, 0.8)
    margen = int(h * 0.38)
    return c.crop((bb[0] - margen, bb[1] - margen, bb[2] + margen, bb[3] + margen))


def icono(tam=1024):
    base = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    r = int(tam * 0.22)
    forma = Image.new("L", (tam, tam), 0)
    ImageDraw.Draw(forma).rounded_rectangle((0, 0, tam - 1, tam - 1), r, fill=255)
    ImageDraw.Draw(base).rounded_rectangle((0, 0, tam - 1, tam - 1), r, fill=(0, 0, 0, 255))
    ImageDraw.Draw(base).rounded_rectangle((3, 3, tam - 4, tam - 4), r, outline=(255, 255, 255, 46),
                                           width=max(2, tam // 150))
    m = mascara("CLW", FUENTE, int(tam * 0.7), tracking=int(tam * 0.004), pad=int(tam * 0.45))
    c = cromo(m, glow=0.12)
    bb = m.getbbox()
    esc = (tam * 0.84) / (bb[2] - bb[0])
    c = c.resize((int(c.width * esc), int(c.height * esc)), Image.LANCZOS)
    cx, cy = (bb[0] + bb[2]) / 2 * esc, (bb[1] + bb[3]) / 2 * esc
    ox, oy = int(tam / 2 - cx), int(tam / 2 - cy + tam * 0.03)
    capa = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    capa.paste(c.crop((max(0, -ox), max(0, -oy), max(0, -ox) + tam, max(0, -oy) + tam)), (max(0, ox), max(0, oy)))
    capa.putalpha(Image.composite(capa.getchannel("A"), Image.new("L", (tam, tam), 0), forma))
    base.alpha_composite(capa)
    return destello(base, int(tam * 0.80), int(tam * 0.27), tam * 0.10)


def icono_chico(tam):
    """Para 16 y 24 px: letras blancas planas (el cromo no se lee tan chico)."""
    g = 16
    T = tam * g
    im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, T - 1, T - 1), int(T * 0.2), fill=(0, 0, 0, 255))
    m = mascara("CLW", FUENTE, int(T * 0.7), pad=int(T * 0.2))
    bb = m.getbbox()
    m = m.crop(bb)
    esc = (T * 0.88) / m.width
    m = m.resize((int(m.width * esc), int(m.height * esc)), Image.LANCZOS)
    blanco = Image.new("RGBA", m.size, (255, 255, 255, 255))
    im.paste(blanco, ((T - m.width) // 2, (T - m.height) // 2), m)
    return im.resize((tam, tam), Image.LANCZOS)


def estrellas(w, h, semilla=11, densidad=1.0, caida=True):
    rnd = random.Random(semilla)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    d = ImageDraw.Draw(im)
    n = int(w * h / 1500 * densidad)
    for _ in range(n):
        x, y = rnd.random() * w, rnd.random() * h
        if caida and rnd.random() < y / h * 0.7:
            continue
        r = rnd.choice([0.5, 0.6, 0.7, 0.8, 1.0, 1.2])
        a = int(rnd.uniform(50, 220))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, a))
    return im


def imagen_lateral(w, h, wm):
    im = estrellas(w, h, semilla=w, densidad=1.4, caida=False).convert("RGBA")
    brillo = Image.new("L", (w, h), 0)
    ImageDraw.Draw(brillo).ellipse((-w * 0.6, h * 0.12, w * 1.6, h * 0.62), fill=34)
    brillo = brillo.filter(ImageFilter.GaussianBlur(w * 0.25))
    im.paste((255, 255, 255, 255), (0, 0), brillo)
    # logo en vertical (girado) para que llene la franja
    girado = wm.rotate(90, expand=True, resample=Image.BICUBIC)
    esc = (h * 0.86) / girado.height
    girado = girado.resize((max(1, int(girado.width * esc)), max(1, int(girado.height * esc))), Image.LANCZOS)
    if girado.width > w * 0.92:
        esc2 = (w * 0.92) / girado.width
        girado = girado.resize((int(girado.width * esc2), int(girado.height * esc2)), Image.LANCZOS)
    im.alpha_composite(girado, ((w - girado.width) // 2, (h - girado.height) // 2))
    return im.convert("RGB")


def main():
    os.makedirs(ASSETS, exist_ok=True)
    os.makedirs(INSTALADOR, exist_ok=True)
    os.makedirs(WEB, exist_ok=True)

    wm = wordmark()
    alto = 1300
    wm_app = wm.resize((alto, int(wm.height * alto / wm.width)), Image.LANCZOS)
    wm_app.save(os.path.join(ASSETS, "wordmark.png"), optimize=True)
    wm.resize((1400, int(wm.height * 1400 / wm.width)), Image.LANCZOS).save(os.path.join(WEB, "wordmark.png"), optimize=True)

    ic = icono(1024)
    ic.resize((256, 256), Image.LANCZOS).save(os.path.join(ASSETS, "icono.png"))
    tam_ico = [256, 128, 64, 48, 32, 24, 16]
    imgs = {t: (icono_chico(t) if t <= 24 else ic.resize((t, t), Image.LANCZOS)) for t in tam_ico}
    imgs[256].save(os.path.join(ASSETS, "icono.ico"), sizes=[(t, t) for t in tam_ico],
                   append_images=[imgs[t] for t in tam_ico[1:]])
    ic.resize((180, 180), Image.LANCZOS).save(os.path.join(WEB, "icono-180.png"))
    ic.resize((64, 64), Image.LANCZOS).save(os.path.join(WEB, "favicon.png"))

    # imagenes del instalador (Inno Setup): franja izquierda y logo chico, varias escalas
    for pct, (w, h), (cw, ch) in [(100, (164, 314), (58, 58)), (125, (205, 393), (73, 73)),
                                  (150, (246, 471), (87, 87)), (200, (328, 628), (116, 116))]:
        imagen_lateral(w, h, wm).save(os.path.join(INSTALADOR, f"lateral_{pct}.bmp"))
        chico = Image.new("RGB", (cw, ch), (0, 0, 0))
        i = ic.resize((cw, ch), Image.LANCZOS)
        chico.paste(i, (0, 0), i)
        chico.save(os.path.join(INSTALADOR, f"chico_{pct}.bmp"))

    # imagen para compartir el link (WhatsApp, etc.)
    og = estrellas(1200, 630, semilla=5, densidad=1.6, caida=False)
    brillo = Image.new("L", (1200, 630), 0)
    ImageDraw.Draw(brillo).ellipse((150, 120, 1050, 520), fill=40)
    og.paste((255, 255, 255, 255), (0, 0), brillo.filter(ImageFilter.GaussianBlur(160)))
    w_og = 900
    wm_og = wm.resize((w_og, int(wm.height * w_og / wm.width)), Image.LANCZOS)
    og.alpha_composite(wm_og, ((1200 - w_og) // 2, (630 - wm_og.height) // 2))
    og.convert("RGB").save(os.path.join(WEB, "compartir.png"), optimize=True)
    print("listo")


if __name__ == "__main__":
    main()
