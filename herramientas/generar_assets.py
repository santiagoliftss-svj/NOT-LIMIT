"""Genera la marca (letras anchas + halo en orbita), el icono, las imagenes del instalador y las de la pagina.

Uso (desde la raiz del repo):  python herramientas/generar_assets.py
"""

import json
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
FUENTE = os.path.join(RAIZ, "app", "assets", "fuentes", "Archivo.ttf")
ASSETS = os.path.join(RAIZ, "app", "assets")
INSTALADOR = os.path.join(RAIZ, "installer", "imagenes")
WEB = os.path.join(RAIZ, "docs", "assets")

# geometria del halo, relativa a las letras
RY, ANGULO, ESTRELLA = 0.95, -6.0, 16.0


def _mascara_texto(texto, tam, peso=900, ancho=125, tracking=0.0):
    f = ImageFont.truetype(FUENTE, tam, layout_engine=ImageFont.Layout.BASIC)
    f.set_variation_by_axes([peso, ancho])
    anchos = [f.getlength(c) for c in texto]
    total = sum(anchos) + tracking * tam * (len(texto) - 1)
    asc, desc = f.getmetrics()
    pad = tam // 2
    m = Image.new("L", (int(total + pad * 2), asc + desc + pad * 2), 0)
    d = ImageDraw.Draw(m)
    x = pad
    for c, a in zip(texto, anchos):
        d.text((x, pad), c, font=f, fill=255)
        x += a + tracking * tam
    return m.crop(m.getbbox())


def _punto_elipse(geo, grados):
    t = math.radians(grados)
    x, y = geo["rx"] * math.cos(t), geo["ry"] * math.sin(t)
    a = math.radians(geo["ang"])
    return (geo["cx"] + x * math.cos(a) - y * math.sin(a), geo["cy"] + x * math.sin(a) + y * math.cos(a))


def _arco(W, H, geo, desde, hasta, grosor, alfa=240):
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pts = [_punto_elipse(geo, desde + (hasta - desde) * i / 599) for i in range(600)]
    ImageDraw.Draw(capa).line(pts, fill=(255, 255, 255, alfa), width=grosor, joint="curve")
    return capa


def estrella(r, brillo=True):
    """Estrella de 4 picos con brillo suave. r = radio de las puntas (px)."""
    T = int(r * 3.2)
    im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    c = T / 2

    def picos(d, rr, alfa):
        pts = []
        for i in range(8):
            ang = math.pi / 4 * i - math.pi / 2
            radio = rr if i % 2 == 0 else rr * 0.2
            pts.append((c + math.cos(ang) * radio, c + math.sin(ang) * radio))
        d.polygon(pts, fill=(255, 255, 255, alfa))

    if brillo:
        g = Image.new("RGBA", (T, T), (0, 0, 0, 0))
        picos(ImageDraw.Draw(g), r * 1.25, 150)
        ImageDraw.Draw(g).ellipse((c - r * 0.35, c - r * 0.35, c + r * 0.35, c + r * 0.35), fill=(255, 255, 255, 120))
        im.alpha_composite(g.filter(ImageFilter.GaussianBlur(r * 0.22)))
    picos(ImageDraw.Draw(im), r, 255)
    return im


def marca(tam_letra=300, con_estrella=True, SS=2):
    """Devuelve (imagen RGBA, geometria del halo en px de la imagen)."""
    m = _mascara_texto("CLW GANG", tam_letra * SS)
    w, h = m.size
    padx, pady = int(w * 0.075), int(h * 1.05)
    W, H = w + 2 * padx, h + 2 * pady
    geo = {"cx": W / 2, "cy": H / 2 + h * 0.04, "rx": w * 0.565, "ry": h * RY, "ang": ANGULO}
    grosor = max(2, int(h * 0.036))

    letras = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    blanco = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    blanco.putalpha(m)
    letras.alpha_composite(blanco, (padx, pady))

    atras = _arco(W, H, geo, 180, 360, grosor)
    adelante = _arco(W, H, geo, 0, 180, grosor)
    # el arco de atras se esconde detras de las letras (con un respiro)
    respiro = letras.getchannel("A").filter(ImageFilter.MaxFilter(2 * (grosor // 2) + 5))
    atras.putalpha(ImageChops.subtract(atras.getchannel("A"), respiro))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(atras)
    out.alpha_composite(letras)
    # el de adelante corta las letras con un hueco para que se vea que pasa encima
    hueco = adelante.getchannel("A").filter(ImageFilter.MaxFilter(2 * (grosor // 2) + 7))
    out.putalpha(ImageChops.subtract(out.getchannel("A"), hueco))
    out.alpha_composite(adelante)
    if con_estrella:
        sx, sy = _punto_elipse(geo, ESTRELLA)
        e = estrella(h * 0.17)
        out.alpha_composite(e, (int(sx - e.width / 2), int(sy - e.height / 2)))
    out = out.resize((W // SS, H // SS), Image.LANCZOS)
    geo = {k: (v / SS if k != "ang" else v) for k, v in geo.items()}
    geo["grosor"] = grosor / SS
    geo["estrella"] = ESTRELLA
    geo["alto_letras"] = h / SS
    return out, geo


def icono(tam=1024):
    """Cuadro negro con CLW ancho en blanco, un halo y la estrella."""
    base = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    r = int(tam * 0.22)
    ImageDraw.Draw(base).rounded_rectangle((0, 0, tam - 1, tam - 1), r, fill=(0, 0, 0, 255))
    borde = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    ImageDraw.Draw(borde).rounded_rectangle((4, 4, tam - 5, tam - 5), r, outline=(255, 255, 255, 70),
                                            width=max(3, tam // 120))
    base.alpha_composite(borde)
    m = _mascara_texto("CLW", int(tam * 0.5))
    esc = (tam * 0.70) / m.width
    m = m.resize((int(m.width * esc), int(m.height * esc)), Image.LANCZOS)
    x0, y0 = (tam - m.width) // 2, int(tam * 0.52 - m.height / 2)
    blanco = Image.new("RGBA", m.size, (255, 255, 255, 255))
    blanco.putalpha(m)
    letras = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    letras.alpha_composite(blanco, (x0, y0))
    geo = {"cx": tam / 2, "cy": y0 + m.height * 0.55, "rx": m.width * 0.6, "ry": m.height * 1.05, "ang": -8}
    g = max(3, int(tam * 0.022))
    atras = _arco(tam, tam, geo, 180, 360, g)
    adelante = _arco(tam, tam, geo, 0, 180, g)
    respiro = letras.getchannel("A").filter(ImageFilter.MaxFilter(2 * (g // 2) + 5))
    atras.putalpha(ImageChops.subtract(atras.getchannel("A"), respiro))
    capa = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    capa.alpha_composite(atras)
    capa.alpha_composite(letras)
    hueco = adelante.getchannel("A").filter(ImageFilter.MaxFilter(2 * (g // 2) + 7))
    capa.putalpha(ImageChops.subtract(capa.getchannel("A"), hueco))
    capa.alpha_composite(adelante)
    sx, sy = _punto_elipse(geo, 20)
    e = estrella(tam * 0.085)
    capa.alpha_composite(e, (int(sx - e.width / 2), int(sy - e.height / 2)))
    base.alpha_composite(capa)
    return base


def icono_chico(tam):
    """Para 16-24 px: solo CLW blanco grueso (el halo no se distingue tan chico)."""
    T = tam * 16
    im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, T - 1, T - 1), int(T * 0.2), fill=(0, 0, 0, 255))
    m = _mascara_texto("CLW", int(T * 0.5))
    esc = (T * 0.86) / m.width
    m = m.resize((int(m.width * esc), int(m.height * esc)), Image.LANCZOS)
    blanco = Image.new("RGBA", m.size, (255, 255, 255, 255))
    blanco.putalpha(m)
    im.alpha_composite(blanco, ((T - m.width) // 2, (T - m.height) // 2))
    return im.resize((tam, tam), Image.LANCZOS)


def icono_bandeja(tam, activo=True):
    """Icono junto al reloj: la estrella del halo (se ve nitida hasta en 16 px). Apagado = estrella tenue."""
    T = tam * 16
    im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, T - 1, T - 1), int(T * 0.22), fill=(0, 0, 0, 255))
    c, r = T / 2, T * 0.40
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.24
        pts.append((c + math.cos(ang) * rr, c + math.sin(ang) * rr))
    d.polygon(pts, fill=(255, 255, 255, 255) if activo else (118, 118, 118, 255))
    return im.resize((tam, tam), Image.LANCZOS)


def lateral(w, h):
    """Franja del instalador: negro total con la marca en vertical."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    mk, _ = marca(200)
    girado = mk.rotate(90, expand=True, resample=Image.BICUBIC)
    esc = min((h * 0.9) / girado.height, (w * 0.95) / girado.width)
    girado = girado.resize((max(1, int(girado.width * esc)), max(1, int(girado.height * esc))), Image.LANCZOS)
    im.alpha_composite(girado, ((w - girado.width) // 2, (h - girado.height) // 2))
    return im.convert("RGB")


def main():
    for carpeta in (ASSETS, INSTALADOR, WEB):
        os.makedirs(carpeta, exist_ok=True)

    # marca para la app: sin estrella (la estrella se mueve en la app) + geometria
    mk, geo = marca(300, con_estrella=False)
    mk.save(os.path.join(ASSETS, "marca.png"), optimize=True)
    with open(os.path.join(ASSETS, "marca.json"), "w", encoding="utf-8") as f:
        json.dump({k: round(v, 2) for k, v in geo.items()}, f, indent=1)
    # marca para la pagina: tambien sin estrella (se anima con SVG)
    mk.save(os.path.join(WEB, "marca.png"), optimize=True)
    with open(os.path.join(WEB, "marca.json"), "w", encoding="utf-8") as f:
        json.dump({k: round(v, 2) for k, v in geo.items()} | {"w": mk.width, "h": mk.height}, f, indent=1)

    ic = icono(1024)
    ic.resize((256, 256), Image.LANCZOS).save(os.path.join(ASSETS, "icono.png"))
    tamanos = [256, 128, 64, 48, 32, 24, 16]
    imgs = {t: (icono_chico(t) if t <= 24 else ic.resize((t, t), Image.LANCZOS)) for t in tamanos}
    imgs[256].save(os.path.join(ASSETS, "icono.ico"), sizes=[(t, t) for t in tamanos],
                   append_images=[imgs[t] for t in tamanos[1:]])
    for nombre, activo in (("bandeja", True), ("bandeja_apagado", False)):
        tam_b = [64, 48, 40, 32, 24, 20, 16]
        ims = [icono_bandeja(t, activo) for t in tam_b]
        ims[0].save(os.path.join(ASSETS, nombre + ".png"))
        ims[0].save(os.path.join(ASSETS, nombre + ".ico"), sizes=[(t, t) for t in tam_b], append_images=ims[1:])
    ic.resize((180, 180), Image.LANCZOS).save(os.path.join(WEB, "icono-180.png"))
    ic.resize((64, 64), Image.LANCZOS).save(os.path.join(WEB, "favicon.png"))

    for pct, (w, h), (cw, ch) in [(100, (164, 314), (58, 58)), (125, (205, 393), (73, 73)),
                                  (150, (246, 471), (87, 87)), (200, (328, 628), (116, 116))]:
        lateral(w, h).save(os.path.join(INSTALADOR, f"lateral_{pct}.bmp"))
        chico = Image.new("RGB", (cw, ch), (0, 0, 0))
        i = ic.resize((cw, ch), Image.LANCZOS)
        chico.paste(i, (0, 0), i)
        chico.save(os.path.join(INSTALADOR, f"chico_{pct}.bmp"))

    # imagen para compartir el link
    og = Image.new("RGBA", (1200, 630), (0, 0, 0, 255))
    mk2, _ = marca(300, con_estrella=True)
    w_og = 980
    mk2 = mk2.resize((w_og, int(mk2.height * w_og / mk2.width)), Image.LANCZOS)
    og.alpha_composite(mk2, ((1200 - w_og) // 2, (630 - mk2.height) // 2))
    og.convert("RGB").save(os.path.join(WEB, "compartir.png"), optimize=True)
    print("listo", mk.size, geo)


if __name__ == "__main__":
    main()
