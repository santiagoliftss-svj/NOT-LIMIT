from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import math, random

def curva(paradas, n):
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        for (a, va), (b, vb) in zip(paradas, paradas[1:]):
            if a <= t <= b:
                k = (t - a) / (b - a) if b > a else 0
                k = k * k * (3 - 2 * k)
                out.append(int(va + (vb - va) * k)); break
    return out

def mascara(texto, fuente, tam, tracking=0, pad=80):
    f = ImageFont.truetype(fuente, tam)
    anchos = [f.getlength(c) for c in texto]
    total = sum(anchos) + tracking * (len(texto) - 1)
    asc, desc = f.getmetrics()
    m = Image.new("L", (int(total + pad * 2), int(asc + desc + pad * 2)), 0)
    d = ImageDraw.Draw(m); x = pad
    for c, a in zip(texto, anchos):
        d.text((x, pad), c, font=f, fill=255); x += a + tracking
    bb = m.getbbox()
    return m.crop((bb[0] - pad // 2, bb[1] - pad // 2, bb[2] + pad // 2, bb[3] + pad // 2))

def cromo(mask, glow=0.22, semilla=7):
    W, H = mask.size
    x0, y0, x1, y1 = mask.getbbox()
    alto = y1 - y0
    paradas = [(0.0, 252), (0.22, 232), (0.42, 128), (0.475, 48), (0.50, 34), (0.515, 250), (0.55, 214),
               (0.70, 118), (0.86, 70), (0.95, 150), (1.0, 205)]
    vals = curva(paradas, alto)
    grad = Image.new("L", (1, H), 255)
    for i, v in enumerate(vals):
        grad.putpixel((0, y0 + i), v)
    for y in range(y1, H):
        grad.putpixel((0, y), vals[-1])
    grad = grad.resize((W, H))
    # leve inclinacion del reflejo (no perfectamente horizontal)
    grad = grad.transform((W, H), Image.AFFINE, (1, 0, 0, 0.06, 1, -0.06 * W / 2), resample=Image.BICUBIC)
    s = max(2, alto // 70)
    blur = mask.filter(ImageFilter.GaussianBlur(s))
    luz = ImageChops.subtract(blur, ImageChops.offset(blur, s, s)).point(lambda v: min(255, v * 4))
    sombra = ImageChops.subtract(blur, ImageChops.offset(blur, -s, -s)).point(lambda v: min(255, v * 3))
    base = Image.merge("RGB", [grad] * 3)
    base = Image.composite(Image.new("RGB", (W, H), (255, 255, 255)), base, luz)
    base = Image.composite(Image.new("RGB", (W, H), (10, 10, 12)), base, sombra)
    r, g, b = base.split()
    base = Image.merge("RGB", (r.point(lambda v: int(v * 0.97)), g.point(lambda v: int(v * 0.985)), b))
    borde = mask.filter(ImageFilter.MaxFilter(3))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if glow:
        halo = mask.filter(ImageFilter.GaussianBlur(alto / 9)).point(lambda v: int(v * glow))
        out.paste((255, 255, 255, 255), (0, 0), halo)
    out.paste((6, 6, 8, 255), (0, 0), borde)
    out.paste(base, (0, 0), mask)
    return out

def destello(img, x, y, r, alpha=1.0):
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    for ang, largo, grosor in ((0, r, 1.6), (90, r, 1.6), (45, r * 0.38, 1.0), (135, r * 0.38, 1.0)):
        a = math.radians(ang)
        n = int(largo * 2)
        for i in range(n + 1):
            t = -largo + i
            k = 1 - abs(t) / largo
            px, py = x + math.cos(a) * t, y + math.sin(a) * t
            gr = grosor * (0.4 + 0.6 * k)
            d.ellipse((px - gr, py - gr, px + gr, py + gr), fill=(255, 255, 255, int(255 * alpha * k ** 1.8)))
    nucleo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(nucleo).ellipse((x - r * 0.18, y - r * 0.18, x + r * 0.18, y + r * 0.18), fill=(255, 255, 255, int(200 * alpha)))
    capa = Image.alpha_composite(capa, nucleo.filter(ImageFilter.GaussianBlur(r * 0.12)))
    return Image.alpha_composite(img, capa)
