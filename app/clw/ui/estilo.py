"""Colores, letras y piezas de la interfaz (total black, vidrio y blanco). Todo se dibuja con PIL."""

import math
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .. import rutas

ANCHO, ALTO = 380, 600          # tamano logico de la ventana

NEGRO = (0, 0, 0)
BLANCO = (255, 255, 255)
TEXTO = (255, 255, 255)
SUAVE = (196, 196, 196)
TENUE = (128, 128, 128)
ERROR = (255, 107, 107)
SS = 4                           # supermuestreo para bordes suaves

# rol: (tamano, peso, ancho, tracking)
TIPOS = {
    "boton":       (13.5, 760, 125, 3.0),
    "boton_chico": (10.8, 740, 125, 1.7),
    "titulo":      (18.5, 860, 125, 0.8),
    "subtitulo":   (14.5, 780, 118, 0.4),
    "nombre":      (15, 620, 104, 0.0),
    "cuerpo":      (13, 440, 100, 0.0),
    "chico":       (11.5, 480, 100, 0.0),
    "mini":        (10.2, 600, 112, 0.5),
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


def medir(texto, rol, escala):
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
    """Curva de animacion (sale rapido y llega lento, estilo Apple)."""
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def ida_y_vuelta(p):
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


# ---------------------------------------------------------------- piezas en cache

def _forma(W, H, r):
    m = Image.new("L", (W * SS, H * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, W * SS - 1, H * SS - 1), min(r * SS, W * SS // 2, H * SS // 2), fill=255)
    return m.resize((W, H), Image.LANCZOS)


@lru_cache(maxsize=128)
def forma(W, H, r):
    return _forma(max(1, W), max(1, H), r)


@lru_cache(maxsize=128)
def anillo(W, H, r, grosor):
    """Solo el borde de un rectangulo redondeado (mascara L)."""
    W, H = max(1, W), max(1, H)
    m = Image.new("L", (W * SS, H * SS), 0)
    g = max(1, round(grosor * SS))
    rr = min(r * SS, W * SS // 2, H * SS // 2)
    ImageDraw.Draw(m).rounded_rectangle((g / 2, g / 2, W * SS - 1 - g / 2, H * SS - 1 - g / 2), rr, outline=255, width=g)
    return m.resize((W, H), Image.LANCZOS)


@lru_cache(maxsize=16)
def _degradado_v(H, arriba, abajo):
    col = Image.new("L", (1, max(1, H)))
    for y in range(max(1, H)):
        t = y / max(1, H - 1)
        col.putpixel((0, y), int(round(arriba + (abajo - arriba) * t)))
    return col


def _alfa_degradado(mascara, arriba, abajo):
    """Multiplica una mascara por un degradado vertical (0..255)."""
    deg = _degradado_v(mascara.height, arriba, abajo).resize(mascara.size)
    return ImageChops.multiply(mascara, deg)


@lru_cache(maxsize=128)
def vidrio(W, H, r, borde=(110, 30), relleno=(12, 4), grosor=1.0):
    """Pieza de vidrio: relleno blanco casi transparente + borde que brilla mas arriba que abajo."""
    W, H = max(1, W), max(1, H)
    im = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    if relleno[0] or relleno[1]:
        im.putalpha(_alfa_degradado(forma(W, H, r), relleno[0], relleno[1]))
    capa = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    capa.putalpha(_alfa_degradado(anillo(W, H, r, grosor), borde[0], borde[1]))
    im.alpha_composite(capa)
    return im


@lru_cache(maxsize=128)
def solido(W, H, r, color):
    im = Image.new("RGBA", (max(1, W), max(1, H)), tuple(color[:3]) + (0,))
    a = forma(W, H, r)
    if len(color) == 4:
        a = a.point(lambda v: v * color[3] // 255)
    im.putalpha(a)
    return im


@lru_cache(maxsize=24)
def resplandor(W, H, r, radio, nivel):
    """Brillo difuso alrededor de una pastilla. nivel 0..10."""
    pad = int(radio * 3)
    m = Image.new("L", (W + pad * 2, H + pad * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle((pad, pad, pad + W, pad + H), r, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(radio))
    capa = Image.new("RGBA", m.size, (255, 255, 255, 0))
    capa.putalpha(m.point(lambda v: int(v * (0.10 + nivel * 0.035))))
    return capa, pad


@lru_cache(maxsize=96)
def haz_borde(W, H, r, grosor, paso, pasos=72):
    """Luz que recorre el borde de una pastilla (paso de 0 a pasos-1)."""
    W, H = max(1, W), max(1, H)
    # punto sobre el perimetro (aprox. rectangulo con puntas redondas)
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
    return im.resize((tam, tam), Image.LANCZOS)


@lru_cache(maxsize=4)
def marca(ancho_px):
    """Logo NO LIMIT (3D, sin fondo) al ancho pedido."""
    im = Image.open(rutas.asset("marca.png")).convert("RGBA")
    k = ancho_px / im.width
    return im.resize((ancho_px, max(1, int(im.height * k))), Image.LANCZOS)


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
            recorte = pieza.crop((max(0, -X), max(0, -Y), pieza.width, pieza.height))
            self.im.alpha_composite(recorte, (max(0, X), max(0, Y)))
        else:
            self.im.alpha_composite(pieza, (X, Y))

    def vidrio(self, x, y, w, h, r, borde=(110, 30), relleno=(12, 4), grosor=1.0):
        X, Y, W, H = self.caja_px(x, y, w, h)
        self.im.alpha_composite(vidrio(W, H, round(r * self.e), borde, relleno, grosor * self.e), (X, Y))

    def solido(self, x, y, w, h, r, color):
        X, Y, W, H = self.caja_px(x, y, w, h)
        self.im.alpha_composite(solido(W, H, round(r * self.e), tuple(color)), (X, Y))

    def linea_h(self, x, y, w, color=(255, 255, 255, 40)):
        capa = Image.new("RGBA", (max(1, self.px(w)), max(1, round(self.e))), color)
        self.im.alpha_composite(capa, (self.px(x), self.px(y)))

    def texto(self, x, y, txt, rol, color=TEXTO, ancla="la", alfa=255):
        """ancla: 'la' izquierda, 'ma' centro, 'ra' derecha (y = arriba de las letras)."""
        f = fuente(rol, self.e)
        tr = tracking(rol) * self.e
        ancho = medir(txt, rol, self.e)
        X = self.px(x)
        if ancla[0] == "m":
            X -= ancho / 2
        elif ancla[0] == "r":
            X -= ancho
        asc, desc = f.getmetrics()
        m = 2
        capa = Image.new("RGBA", (int(ancho) + 2 * m + 2, asc + desc + 2 * m), (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)
        col = tuple(color[:3]) + (alfa,)
        if tr:
            cx = 0.0
            for ch in txt:
                d.text((cx + m, m - 1), ch, font=f, fill=col)
                cx += f.getlength(ch) + tr
        else:
            d.text((m, m - 1), txt, font=f, fill=col)
        self.im.alpha_composite(capa, (int(round(X)) - m, self.px(y) - m))
        return ancho / self.e

    def texto_centrado_v(self, x, y_centro, txt, rol, color=TEXTO, ancla="la", alfa=255):
        f = fuente(rol, self.e)
        bb = f.getbbox("H")
        alto_cap = (bb[3] - bb[1]) / self.e
        arriba = bb[1] / self.e
        return self.texto(x, y_centro - alto_cap / 2 - arriba, txt, rol, color, ancla, alfa)

    def icono(self, nombre, x, y, tam, color=TEXTO):
        self.im.alpha_composite(icono(nombre, self.px(tam), tuple(color[:3])), (self.px(x), self.px(y)))

    def punto(self, cx, cy, r, color=BLANCO, alfa=255, anillo_solo=False):
        T = max(2, self.px(r * 2)) * SS
        im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if anillo_solo:
            d.ellipse((SS, SS, T - 1 - SS, T - 1 - SS), outline=tuple(color[:3]) + (alfa,), width=max(SS, int(T * 0.14)))
        else:
            d.ellipse((0, 0, T - 1, T - 1), fill=tuple(color[:3]) + (alfa,))
        im = im.resize((T // SS, T // SS), Image.LANCZOS)
        self.im.alpha_composite(im, (self.px(cx) - im.width // 2, self.px(cy) - im.height // 2))

    def oscurecer(self, alfa):
        self.im.alpha_composite(Image.new("RGBA", self.im.size, (0, 0, 0, alfa)))
