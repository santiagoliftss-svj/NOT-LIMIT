"""Colores, letras y piezas de NO LIMIT (total black, vidrio y blanco liquido como el logo).

Todo se dibuja con PIL y casi todo queda en cache: dibujar una pantalla completa es pegar piezas ya hechas,
por eso picar botones no traba la ventana.
"""

import math
from collections import OrderedDict
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .. import rutas

ANCHO, ALTO = 380, 600          # tamano logico de la ventana

NEGRO = (0, 0, 0)
BLANCO = (255, 255, 255)
TEXTO = (245, 245, 247)
SUAVE = (161, 161, 166)
TENUE = (110, 110, 115)
ERROR = (255, 105, 97)
GOTA = (205, 205, 211)
SS = 4                           # supermuestreo para bordes suaves

# rol: (tamano, peso, ancho, tracking en px logicos)
TIPOS = {
    "titulo":      (30, 820, 104, -1.2),
    "titulo_m":    (25, 820, 104, -0.9),
    "subtitulo":   (17, 760, 104, -0.4),
    "boton":       (13.5, 760, 125, 3.0),
    "boton_chico": (10.5, 740, 120, 1.3),
    "nombre":      (16, 640, 100, -0.2),
    "cuerpo":      (13.5, 440, 100, 0.0),
    "chico":       (12, 480, 100, 0.0),
    "mini":        (10.5, 600, 110, 0.3),
    "seccion":     (10.5, 700, 118, 1.6),
    "sello":       (13, 850, 112, -0.4),
}


@lru_cache(maxsize=64)
def fuente(rol, escala):
    tam, peso, ancho, _ = TIPOS[rol]
    f = ImageFont.truetype(rutas.asset("fuentes", "Archivo.ttf"), max(6, round(tam * escala)),
                           layout_engine=ImageFont.Layout.BASIC)
    try:
        f.set_variation_by_axes([peso, ancho])
    except Exception:
        pass
    return f


def tracking(rol):
    return TIPOS[rol][3]


@lru_cache(maxsize=4096)
def medir(texto, rol, escala):
    """Ancho en px del texto ya escalado."""
    f = fuente(rol, escala)
    tr = tracking(rol) * escala
    if not tr:
        return f.getlength(texto)
    return sum(f.getlength(c) for c in texto) + tr * max(0, len(texto) - 1)


def recortar(texto, rol, escala, ancho_max):
    if medir(texto, rol, escala) <= ancho_max:
        return texto
    while texto and medir(texto + "…", rol, escala) > ancho_max:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def partir(texto, rol, escala, ancho_max):
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = (actual + " " + palabra).strip()
        if medir(prueba, rol, escala) <= ancho_max or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def suave(p):
    """Sale rapido y llega lento (estilo Apple)."""
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def ida_y_vuelta(p):
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def acelera(p):
    p = max(0.0, min(1.0, p))
    return p * p * p


# ---------------------------------------------------------------- textos en cache

_TEXTOS = OrderedDict()


def _cachear(clave, valor):
    _TEXTOS[clave] = valor
    if len(_TEXTOS) > 900:
        _TEXTOS.popitem(last=False)
    return valor


def texto_sprite(txt, rol, color, escala, alfa=255):
    """(imagen RGBA, ancho_px, margen) del texto. Se dibuja una sola vez."""
    clave = (txt, rol, tuple(color[:3]), escala, alfa)
    hecho = _TEXTOS.get(clave)
    if hecho is not None:
        _TEXTOS.move_to_end(clave)
        return hecho
    f = fuente(rol, escala)
    tr = tracking(rol) * escala
    ancho = medir(txt, rol, escala)
    asc, desc = f.getmetrics()
    m = 3
    capa = Image.new("RGBA", (int(math.ceil(ancho)) + 2 * m + 4, asc + desc + 2 * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    col = tuple(color[:3]) + (alfa,)
    if tr:
        cx = 0.0
        for ch in txt:
            d.text((cx + m, m - 1), ch, font=f, fill=col)
            cx += f.getlength(ch) + tr
    else:
        d.text((m, m - 1), txt, font=f, fill=col)
    return _cachear(clave, (capa, ancho, m))


@lru_cache(maxsize=8)
def _columna_plata(alto):
    col = Image.new("RGB", (1, max(1, alto)))
    paradas = [(0.0, (255, 255, 255)), (0.45, (238, 238, 242)), (0.75, (196, 196, 202)), (1.0, (140, 140, 148))]
    for y in range(max(1, alto)):
        t = y / max(1, alto - 1)
        for (a, ca), (b, cb) in zip(paradas, paradas[1:]):
            if a <= t <= b:
                k = (t - a) / (b - a) if b > a else 0
                col.putpixel((0, y), tuple(int(ca[i] + (cb[i] - ca[i]) * k) for i in range(3)))
                break
    return col


def texto_plata(txt, rol, escala):
    """Texto con el degradado plateado de la pagina (blanco arriba, gris abajo)."""
    clave = (txt, rol, "plata", escala)
    hecho = _TEXTOS.get(clave)
    if hecho is not None:
        _TEXTOS.move_to_end(clave)
        return hecho
    capa, ancho, m = texto_sprite(txt, rol, BLANCO, escala)
    f = fuente(rol, escala)
    bb = f.getbbox("Hg")
    alto = max(2, bb[3] - bb[1])
    col = _columna_plata(alto).resize((1, alto))
    fondo = Image.new("RGB", capa.size, (140, 140, 148))
    fondo.paste((255, 255, 255), (0, 0, capa.width, m - 1 + bb[1]))
    fondo.paste(col.resize((capa.width, alto)), (0, m - 1 + bb[1]))
    plata = fondo.convert("RGBA")
    plata.putalpha(capa.getchannel("A"))
    return _cachear(clave, (plata, ancho, m))


# ---------------------------------------------------------------- piezas en cache

def _forma(W, H, r):
    m = Image.new("L", (W * SS, H * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, W * SS - 1, H * SS - 1), min(r * SS, W * SS // 2, H * SS // 2), fill=255)
    return m.resize((W, H), Image.LANCZOS)


@lru_cache(maxsize=160)
def forma(W, H, r):
    return _forma(max(1, W), max(1, H), r)


@lru_cache(maxsize=160)
def anillo(W, H, r, grosor):
    """Solo el borde de un rectangulo redondeado (mascara L)."""
    W, H = max(1, W), max(1, H)
    m = Image.new("L", (W * SS, H * SS), 0)
    g = max(1, round(grosor * SS))
    rr = min(r * SS, W * SS // 2, H * SS // 2)
    ImageDraw.Draw(m).rounded_rectangle((g / 2, g / 2, W * SS - 1 - g / 2, H * SS - 1 - g / 2), rr, outline=255, width=g)
    return m.resize((W, H), Image.LANCZOS)


@lru_cache(maxsize=24)
def _degradado_v(H, arriba, abajo):
    col = Image.new("L", (1, max(1, H)))
    for y in range(max(1, H)):
        t = y / max(1, H - 1)
        col.putpixel((0, y), int(round(arriba + (abajo - arriba) * t)))
    return col


def _alfa_degradado(mascara, arriba, abajo):
    deg = _degradado_v(mascara.height, arriba, abajo).resize(mascara.size)
    return ImageChops.multiply(mascara, deg)


@lru_cache(maxsize=160)
def vidrio(W, H, r, borde=(110, 30), relleno=(12, 4), grosor=1.0):
    """Vidrio: relleno blanco casi transparente + borde que brilla mas arriba que abajo."""
    W, H = max(1, W), max(1, H)
    im = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    if relleno[0] or relleno[1]:
        im.putalpha(_alfa_degradado(forma(W, H, r), relleno[0], relleno[1]))
    capa = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    capa.putalpha(_alfa_degradado(anillo(W, H, r, grosor), borde[0], borde[1]))
    im.alpha_composite(capa)
    return im


@lru_cache(maxsize=160)
def solido(W, H, r, color):
    im = Image.new("RGBA", (max(1, W), max(1, H)), tuple(color[:3]) + (0,))
    a = forma(W, H, r)
    if len(color) == 4:
        a = a.point(lambda v: v * color[3] // 255)
    im.putalpha(a)
    return im


@lru_cache(maxsize=48)
def liquido(W, H, r, tono=0):
    """Pastilla blanca brillosa, del mismo material que el logo (tono: 0 normal, 1 mouse encima, 2 presionada)."""
    W, H = max(1, W), max(1, H)
    arriba, medio, abajo = [((255, 255, 255), (237, 237, 240), (201, 201, 207)),
                            ((255, 255, 255), (244, 244, 247), (214, 214, 219)),
                            ((236, 236, 240), (214, 214, 219), (178, 178, 185))][tono]
    col = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / max(1, H - 1)
        a, b, k = (arriba, medio, t / .6) if t < .6 else (medio, abajo, (t - .6) / .4)
        col.putpixel((0, y), tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)))
    im = col.resize((W, H)).convert("RGBA")
    im.putalpha(forma(W, H, r))
    # sombra interna abajo (volumen) y brillo arriba
    sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sombra.putalpha(_alfa_degradado(anillo(W, H, r, max(2, H * .08)), 0, 60))
    im.alpha_composite(sombra)
    return im


@lru_cache(maxsize=24)
def resplandor(W, H, r, radio, nivel):
    """Brillo difuso alrededor de una pastilla. nivel 0..10."""
    pad = int(radio * 3)
    m = Image.new("L", (W + pad * 2, H + pad * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle((pad, pad, pad + W, pad + H), r, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(radio))
    capa = Image.new("RGBA", m.size, (255, 255, 255, 0))
    capa.putalpha(m.point(lambda v: int(v * (0.08 + nivel * 0.03))))
    return capa, pad


@lru_cache(maxsize=96)
def haz_borde(W, H, r, grosor, paso, pasos=72):
    """Luz que recorre el borde de una pastilla (paso de 0 a pasos-1)."""
    W, H = max(1, W), max(1, H)
    recto = max(0, W - H)
    per = 2 * recto + math.pi * H
    s = per * paso / pasos
    if s < recto:
        x, y = H / 2 + s, 0
    elif s < recto + math.pi * H / 2:
        a = (s - recto) / (H / 2) - math.pi / 2
        x, y = W - H / 2 + math.cos(a) * H / 2, H / 2 + math.sin(a) * H / 2
    elif s < 2 * recto + math.pi * H / 2:
        x, y = W - H / 2 - (s - recto - math.pi * H / 2), H
    else:
        a = (s - 2 * recto - math.pi * H / 2) / (H / 2) + math.pi / 2
        x, y = H / 2 + math.cos(a) * H / 2, H / 2 + math.sin(a) * H / 2
    radio = H * 0.95
    mancha = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mancha).ellipse((x - radio, y - radio, x + radio, y + radio), fill=255)
    mancha = mancha.filter(ImageFilter.GaussianBlur(radio * 0.45))
    borde = anillo(W, H, r, grosor * 1.6)
    capa = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    capa.putalpha(ImageChops.multiply(borde, mancha))
    return capa


# gotas que escurren debajo de una pastilla blanca (como el logo): (x relativa, radio, desfase)
GOTAS = ((0.27, 8.5, 0.0), (0.6, 6.5, 0.36), (0.8, 5.5, 0.7))
GOTAS_N = 36                    # cuadros por vuelta (1.8 s)


def _gota(q):
    """Para una fase q (0..1): (bajada en px logicos, escala del radio)."""
    if q < .45:
        k = suave(q / .45)
        return 10 * k, .4 + .6 * k
    if q < .62:
        k = (q - .45) / .17
        return 10 + 8 * k, 1 - .05 * k
    k = acelera((q - .62) / .38)
    return 18 + 24 * k, .95 - .6 * k


@lru_cache(maxsize=120)
def gotas(W, H, escala, cuadro, una=False):
    """Capa con las gotas (fusionadas como liquido) para el cuadro dado. Se pega debajo de la pastilla.
    Devuelve (imagen, pad)."""
    pad = int(16 * escala)
    caida = int(40 * escala)
    WW, HH = W + 2 * pad, H + caida + pad
    m = Image.new("L", (WW, HH), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((pad, pad, pad + W - 1, pad + H - 1), H // 2, fill=255)
    for fx, radio, desfase in (GOTAS[1:2] if una else GOTAS):
        q = (cuadro / GOTAS_N - (0 if una else desfase)) % 1.0
        baja, s = _gota(q)
        r = radio * escala * s
        cx = pad + W * fx
        cy = pad + H - radio * escala * .9 + baja * escala
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(5 * escala))
    m = m.point(lambda v: 0 if v < 105 else 255 if v > 150 else int((v - 105) * 255 / 45))
    # la gota que se suelta se desvanece antes de llegar al texto de abajo
    y0, y1 = pad + H + int(19 * escala), pad + H + int(29 * escala)
    if y0 < HH:
        rampa = Image.new("L", (1, HH), 255)
        for y in range(y0, HH):
            rampa.putpixel((0, y), max(0, int(255 * (y1 - y) / max(1, y1 - y0))))
        m = ImageChops.multiply(m, rampa.resize((WW, HH)))
    capa = Image.new("RGBA", (WW, HH), GOTA + (0,))
    capa.putalpha(m)
    return capa, pad


@lru_cache(maxsize=64)
def icono(nombre, tam, color):
    T = tam * SS
    im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    g = max(SS, int(T * 0.09))
    c = tuple(color[:3]) + (255,)
    if nombre == "abajo":
        d.line([(T * 0.22, T * 0.38), (T * 0.5, T * 0.64), (T * 0.78, T * 0.38)], fill=c, width=g, joint="curve")
    elif nombre == "atras":
        d.line([(T * 0.62, T * 0.2), (T * 0.34, T * 0.5), (T * 0.62, T * 0.8)], fill=c, width=g, joint="curve")
    elif nombre == "palomita":
        d.line([(T * 0.2, T * 0.52), (T * 0.42, T * 0.72), (T * 0.8, T * 0.3)], fill=c, width=g, joint="curve")
    elif nombre == "engrane":
        cx = cy = T / 2
        for i in range(8):
            a = math.pi * 2 * i / 8
            d.line([(cx + math.cos(a) * T * 0.30, cy + math.sin(a) * T * 0.30),
                    (cx + math.cos(a) * T * 0.44, cy + math.sin(a) * T * 0.44)], fill=c, width=int(g * 1.5))
        d.ellipse((cx - T * 0.31, cy - T * 0.31, cx + T * 0.31, cy + T * 0.31), outline=c, width=g)
        d.ellipse((cx - T * 0.11, cy - T * 0.11, cx + T * 0.11, cy + T * 0.11), outline=c, width=g)
    elif nombre == "afuera":
        d.line([(T * 0.3, T * 0.7), (T * 0.72, T * 0.28)], fill=c, width=g)
        d.line([(T * 0.4, T * 0.28), (T * 0.72, T * 0.28), (T * 0.72, T * 0.6)], fill=c, width=g, joint="curve")
    elif nombre == "bajar":
        d.line([(T * 0.5, T * 0.16), (T * 0.5, T * 0.62)], fill=c, width=g)
        d.line([(T * 0.3, T * 0.44), (T * 0.5, T * 0.64), (T * 0.7, T * 0.44)], fill=c, width=g, joint="curve")
        d.line([(T * 0.2, T * 0.84), (T * 0.8, T * 0.84)], fill=c, width=g)
    elif nombre == "candado":
        d.rounded_rectangle((T * 0.2, T * 0.44, T * 0.8, T * 0.88), radius=T * 0.1, fill=c)
        d.arc((T * 0.32, T * 0.14, T * 0.68, T * 0.62), 180, 360, fill=c, width=g)
        d.line([(T * 0.32, T * 0.38), (T * 0.32, T * 0.46)], fill=c, width=g)
        d.line([(T * 0.68, T * 0.38), (T * 0.68, T * 0.46)], fill=c, width=g)
    return im.resize((tam, tam), Image.LANCZOS)


@lru_cache(maxsize=24)
def sello(texto, lado, escala):
    """Placa blanca brillosa con las letras del proveedor (Cl, Ge, GPT), como en la pagina."""
    L = max(4, round(lado * escala))
    im = liquido(L, L, round(L * .3)).copy()
    rol = "sello" if len(texto) < 3 else "mini"
    capa, ancho, m = texto_sprite(texto, rol, (10, 10, 12), escala)
    f = fuente(rol, escala)
    bb = f.getbbox("H")
    y = (L - (bb[3] - bb[1])) / 2 - bb[1] - m + 1
    im.alpha_composite(capa, (int(round((L - ancho) / 2 - m)), int(round(y))))
    return im


@lru_cache(maxsize=4)
def foco(W, H):
    """Fondo: negro con una luz suave que cae desde arriba (como la portada de la pagina)."""
    im = Image.new("RGBA", (W, H), NEGRO + (255,))
    g = Image.radial_gradient("L").point(lambda v: int(255 * (max(0, 176 - v) / 176) ** 1.7))
    g = g.resize((int(W * 1.6), int(H * 1.0)), Image.BICUBIC)
    luz = Image.new("L", (W, H), 0)
    luz.paste(g, (int((W - g.width) / 2), int(-g.height * .45)))
    luz = luz.point(lambda v: int(v * .11))
    capa = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    capa.putalpha(luz)
    im.alpha_composite(capa)
    return im


@lru_cache(maxsize=4)
def marca(ancho_px):
    """Logo NO LIMIT (3D, sin fondo) al ancho pedido."""
    im = Image.open(rutas.asset("marca.png")).convert("RGBA")
    k = ancho_px / im.width
    return im.resize((ancho_px, max(1, int(im.height * k))), Image.LANCZOS)


@lru_cache(maxsize=4)
def reflejo_marca(ancho_px, alto_px, escala):
    """El logo reflejado en el piso: volteado, borroso y desvanecido."""
    im = marca(ancho_px).transpose(Image.FLIP_TOP_BOTTOM).crop((0, 0, ancho_px, max(1, alto_px)))
    im = im.filter(ImageFilter.GaussianBlur(1.2 * escala))
    a = _alfa_degradado(im.getchannel("A"), 60, 0)
    im.putalpha(a)
    return im


@lru_cache(maxsize=4)
def piso(ancho_px):
    linea = Image.new("RGBA", (ancho_px, 1), (255, 255, 255, 0))
    for x in range(ancho_px):
        t = abs(x / max(1, ancho_px - 1) - .5) * 2
        linea.putpixel((x, 0), (255, 255, 255, int(60 * (1 - t) ** 1.5)))
    return linea


PASOS_BRILLO = 36


@lru_cache(maxsize=48)
def brillo_marca(ancho_px, paso):
    """Reflejo de luz que cruza las letras en diagonal (paso 0..PASOS_BRILLO-1)."""
    im = marca(ancho_px)
    W, H = im.size
    centro = -0.25 * W + 1.5 * W * paso / (PASOS_BRILLO - 1)
    media, sesgo = 0.07 * W, 0.32 * H
    banda = Image.new("L", (W, H), 0)
    ImageDraw.Draw(banda).polygon([(centro - media + sesgo, 0), (centro + media + sesgo, 0),
                                   (centro + media - sesgo, H), (centro - media - sesgo, H)], fill=255)
    banda = banda.filter(ImageFilter.GaussianBlur(media * 0.6))
    alfa = ImageChops.multiply(banda, im.getchannel("A")).point(lambda v: int(v * 0.62))
    capa = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    capa.putalpha(alfa)
    return capa


@lru_cache(maxsize=4)
def _mancha(radio):
    g = Image.radial_gradient("L").point(lambda v: int(255 * (max(0, 128 - v) / 128) ** 1.5))
    return g.resize((radio * 2, radio * 2), Image.BICUBIC)


@lru_cache(maxsize=160)
def especular(ancho_px, x, y, radio):
    """Brillo que sigue al mouse sobre las letras (x, y en px dentro del logo)."""
    im = marca(ancho_px)
    W, H = im.size
    m = Image.new("L", (W, H), 0)
    m.paste(_mancha(radio), (x - radio, y - radio))
    alfa = ImageChops.multiply(m, im.getchannel("A")).point(lambda v: int(v * .55))
    capa = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    capa.putalpha(alfa)
    return capa


# ---------------------------------------------------------------- lienzo

class Lienzo:
    """Superficie de dibujo en coordenadas logicas (se multiplican por la escala)."""

    def __init__(self, escala, base=None):
        self.e = escala
        self.w, self.h = round(ANCHO * escala), round(ALTO * escala)
        self.im = base.copy() if base is not None else Image.new("RGBA", (self.w, self.h), NEGRO + (255,))
        self.zonas = []

    def px(self, v):
        return round(v * self.e)

    def zona(self, ident, x, y, w, h, cursor="hand2"):
        self.zonas.append((ident, (x, y, w, h), cursor))

    def caja_px(self, x, y, w, h):
        X, Y = self.px(x), self.px(y)
        return X, Y, self.px(x + w) - X, self.px(y + h) - Y

    def pegar_px(self, pieza, X, Y):
        X, Y = int(round(X)), int(round(Y))
        if X < 0 or Y < 0:
            if X <= -pieza.width or Y <= -pieza.height:
                return
            recorte = pieza.crop((max(0, -X), max(0, -Y), pieza.width, pieza.height))
            self.im.alpha_composite(recorte, (max(0, X), max(0, Y)))
        else:
            self.im.alpha_composite(pieza, (X, Y))

    def pegar(self, pieza, x, y):
        self.pegar_px(pieza, self.px(x), self.px(y))

    def vidrio(self, x, y, w, h, r, borde=(110, 30), relleno=(12, 4), grosor=1.0):
        X, Y, W, H = self.caja_px(x, y, w, h)
        self.im.alpha_composite(vidrio(W, H, round(r * self.e), borde, relleno, grosor * self.e), (X, Y))

    def solido(self, x, y, w, h, r, color):
        X, Y, W, H = self.caja_px(x, y, w, h)
        self.pegar_px(solido(W, H, round(r * self.e), tuple(color)), X, Y)

    def liquido(self, x, y, w, h, r, tono=0):
        X, Y, W, H = self.caja_px(x, y, w, h)
        self.pegar_px(liquido(W, H, round(r * self.e), tono), X, Y)

    def linea_h(self, x, y, w, color=(255, 255, 255, 40)):
        capa = Image.new("RGBA", (max(1, self.px(w)), max(1, round(self.e))), color)
        self.im.alpha_composite(capa, (self.px(x), self.px(y)))

    def texto(self, x, y, txt, rol, color=TEXTO, ancla="la", alfa=255):
        """ancla: 'la' izquierda, 'ma' centro, 'ra' derecha (y = arriba de las letras). Devuelve el ancho logico."""
        if not txt:
            return 0
        capa, ancho, m = texto_sprite(txt, rol, color, self.e, alfa)
        return self._poner(capa, ancho, m, x, y, ancla)

    def texto_plata(self, x, y, txt, rol, ancla="la"):
        capa, ancho, m = texto_plata(txt, rol, self.e)
        return self._poner(capa, ancho, m, x, y, ancla)

    def _poner(self, capa, ancho, m, x, y, ancla):
        X = self.px(x)
        if ancla[0] == "m":
            X -= ancho / 2
        elif ancla[0] == "r":
            X -= ancho
        self.pegar_px(capa, int(round(X)) - m, self.px(y) - m)
        return ancho / self.e

    def _y_centro(self, y_centro, rol):
        f = fuente(rol, self.e)
        bb = f.getbbox("H")
        return y_centro - (bb[3] - bb[1]) / self.e / 2 - bb[1] / self.e

    def texto_centrado_v(self, x, y_centro, txt, rol, color=TEXTO, ancla="la", alfa=255):
        return self.texto(x, self._y_centro(y_centro, rol), txt, rol, color, ancla, alfa)

    def icono(self, nombre, x, y, tam, color=TEXTO):
        self.pegar_px(icono(nombre, self.px(tam), tuple(color[:3])), self.px(x), self.px(y))

    def punto(self, cx, cy, r, color=BLANCO, alfa=255, anillo_solo=False):
        T = max(2, self.px(r * 2)) * SS
        im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if anillo_solo:
            d.ellipse((SS, SS, T - 1 - SS, T - 1 - SS), outline=tuple(color[:3]) + (alfa,), width=max(SS, int(T * 0.14)))
        else:
            d.ellipse((0, 0, T - 1, T - 1), fill=tuple(color[:3]) + (alfa,))
        im = im.resize((T // SS, T // SS), Image.LANCZOS)
        self.pegar_px(im, self.px(cx) - im.width // 2, self.px(cy) - im.height // 2)

    def oscurecer(self, alfa):
        self.im.alpha_composite(Image.new("RGBA", self.im.size, (0, 0, 0, alfa)))
