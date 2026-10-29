"""Colores, letras y piezas de dibujo de la interfaz. Todo se dibuja con PIL en pixeles reales."""

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import rutas

ANCHO, ALTO = 380, 600          # tamano logico de la ventana

NEGRO = (0, 0, 0)
BLANCO = (255, 255, 255)
TEXTO = (244, 244, 244)
SUAVE = (150, 150, 150)
TENUE = (96, 96, 96)
ERROR = (255, 104, 104)
LINEA = (255, 255, 255, 38)
LINEA_FUERTE = (255, 255, 255, 105)
SS = 4                           # supermuestreo para bordes suaves

# rol: (tamano, peso, ancho, tracking)
TIPOS = {
    "boton":       (16.5, 800, 125, 2.6),
    "boton_chico": (11.5, 750, 125, 1.6),
    "titulo":      (20, 720, 112, 0.2),
    "subtitulo":   (15.5, 700, 108, 0.1),
    "nombre":      (14.5, 560, 100, 0.0),
    "cuerpo":      (13.2, 430, 100, 0.0),
    "chico":       (11.6, 470, 100, 0.1),
    "mini":        (10.4, 520, 104, 0.3),
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
    """Parte el texto en lineas que quepan en ancho_max."""
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


# ---------------------------------------------------------------- piezas en cache

@lru_cache(maxsize=256)
def pieza_redonda(w, h, r, relleno, borde, grosor):
    """Rectangulo redondeado suave (RGBA). Medidas en pixeles reales."""
    W, H = max(1, w) * SS, max(1, h) * SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rr = min(r * SS, W // 2, H // 2)
    if relleno:
        d.rounded_rectangle((0, 0, W - 1, H - 1), rr, fill=relleno)
    if borde and grosor:
        g = max(1, round(grosor * SS))
        d.rounded_rectangle((g / 2, g / 2, W - 1 - g / 2, H - 1 - g / 2), rr, outline=borde, width=g)
    return im.resize((max(1, w), max(1, h)), Image.LANCZOS)


@lru_cache(maxsize=32)
def resplandor(w, h, r, radio, nivel):
    """Brillo difuso alrededor de una pastilla (para cuando esta activo). nivel 0..10."""
    pad = int(radio * 3)
    im = Image.new("L", (w + pad * 2, h + pad * 2), 0)
    ImageDraw.Draw(im).rounded_rectangle((pad, pad, pad + w, pad + h), r, outline=255, width=max(2, int(radio * 0.6)))
    im = im.filter(ImageFilter.GaussianBlur(radio))
    alfa = im.point(lambda v: int(v * (0.25 + nivel * 0.06)))
    capa = Image.new("RGBA", im.size, (255, 255, 255, 0))
    capa.putalpha(alfa)
    return capa, pad


@lru_cache(maxsize=64)
def icono(nombre, tam, color):
    """Iconos de linea dibujados a mano (supermuestreados)."""
    T = tam * SS
    im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    g = max(SS, int(T * 0.09))
    c = color + (255,) if len(color) == 3 else color
    if nombre == "abajo":
        d.line([(T * 0.22, T * 0.38), (T * 0.5, T * 0.64), (T * 0.78, T * 0.38)], fill=c, width=g, joint="curve")
    elif nombre == "atras":
        d.line([(T * 0.62, T * 0.2), (T * 0.34, T * 0.5), (T * 0.62, T * 0.8)], fill=c, width=g, joint="curve")
    elif nombre == "palomita":
        d.line([(T * 0.2, T * 0.52), (T * 0.42, T * 0.72), (T * 0.8, T * 0.3)], fill=c, width=g, joint="curve")
    elif nombre == "tache":
        d.line([(T * 0.25, T * 0.25), (T * 0.75, T * 0.75)], fill=c, width=g)
        d.line([(T * 0.75, T * 0.25), (T * 0.25, T * 0.75)], fill=c, width=g)
    elif nombre == "engrane":
        cx = cy = T / 2
        for i in range(8):
            a = math.pi * 2 * i / 8
            x1, y1 = cx + math.cos(a) * T * 0.30, cy + math.sin(a) * T * 0.30
            x2, y2 = cx + math.cos(a) * T * 0.44, cy + math.sin(a) * T * 0.44
            d.line([(x1, y1), (x2, y2)], fill=c, width=int(g * 1.5))
        d.ellipse((cx - T * 0.31, cy - T * 0.31, cx + T * 0.31, cy + T * 0.31), outline=c, width=g)
        d.ellipse((cx - T * 0.11, cy - T * 0.11, cx + T * 0.11, cy + T * 0.11), outline=c, width=g)
    elif nombre == "afuera":
        d.line([(T * 0.3, T * 0.7), (T * 0.72, T * 0.28)], fill=c, width=g)
        d.line([(T * 0.4, T * 0.28), (T * 0.72, T * 0.28), (T * 0.72, T * 0.6)], fill=c, width=g, joint="curve")
    return im.resize((tam, tam), Image.LANCZOS)


@lru_cache(maxsize=4)
def logo(ancho_px):
    wm = Image.open(rutas.asset("wordmark.png")).convert("RGBA")
    alto = int(wm.height * ancho_px / wm.width)
    return wm.resize((ancho_px, alto), Image.LANCZOS)


@lru_cache(maxsize=4)
def fondo_estrellas(w, h, escala):
    """Negro total con estrellas que se van apagando hacia abajo y un brillo leve arriba."""
    rnd = random.Random(7)
    im = Image.new("RGBA", (w, h), NEGRO + (255,))
    capa = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    n = int(ANCHO * ALTO / 900)
    for _ in range(n):
        x, y = rnd.random(), rnd.random()
        if rnd.random() < y * 0.85:
            continue
        r = rnd.choice([0.45, 0.55, 0.65, 0.8, 1.0]) * escala * 2
        a = int(rnd.uniform(45, 210) * (1 - y * 0.55))
        d.ellipse((x * w * 2 - r, y * h * 2 - r, x * w * 2 + r, y * h * 2 + r), fill=(255, 255, 255, a))
    im.alpha_composite(capa.resize((w, h), Image.LANCZOS))
    brillo = Image.new("L", (w, h), 0)
    ImageDraw.Draw(brillo).ellipse((w * 0.05, -h * 0.10, w * 0.95, h * 0.30), fill=26)
    im.paste((255, 255, 255, 255), (0, 0), brillo.filter(ImageFilter.GaussianBlur(w * 0.16)))
    for fx, fy, fr in ((0.13, 0.055, 7), (0.88, 0.27, 5)):
        _destello(im, fx * w, fy * h, fr * escala)
    return im


def _destello(im, x, y, r):
    capa = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    for ang, largo in ((0, r), (90, r), (45, r * 0.4), (135, r * 0.4)):
        a = math.radians(ang)
        pasos = max(4, int(largo * 4))
        for i in range(pasos + 1):
            t = -largo + 2 * largo * i / pasos
            k = 1 - abs(t) / largo
            px, py = x + math.cos(a) * t, y + math.sin(a) * t
            gr = 0.35 + 0.45 * k
            d.ellipse((px - gr, py - gr, px + gr, py + gr), fill=(255, 255, 255, int(230 * k ** 1.7)))
    im.alpha_composite(capa)


# ---------------------------------------------------------------- lienzo

class Lienzo:
    """Superficie de dibujo en coordenadas logicas (se multiplican por la escala)."""

    def __init__(self, escala, base=None):
        self.e = escala
        self.w, self.h = round(ANCHO * escala), round(ALTO * escala)
        self.im = base.copy() if base is not None else Image.new("RGBA", (self.w, self.h), NEGRO + (255,))
        self.zonas = []           # (id, (x, y, w, h), cursor)

    def px(self, v):
        return round(v * self.e)

    def zona(self, ident, x, y, w, h, cursor="hand2"):
        self.zonas.append((ident, (x, y, w, h), cursor))

    def pegar(self, pieza, x, y):
        self.im.alpha_composite(pieza, (self.px(x), self.px(y)))

    def pegar_px(self, pieza, X, Y):
        if X < 0 or Y < 0:
            recorte = pieza.crop((max(0, -X), max(0, -Y), pieza.width, pieza.height))
            self.im.alpha_composite(recorte, (max(0, X), max(0, Y)))
        else:
            self.im.alpha_composite(pieza, (X, Y))

    def caja(self, x, y, w, h, r, relleno=None, borde=None, grosor=1.0):
        X, Y = self.px(x), self.px(y)
        W, H = self.px(x + w) - X, self.px(y + h) - Y
        self.im.alpha_composite(pieza_redonda(W, H, round(r * self.e), relleno, borde, grosor * self.e), (X, Y))

    def linea_h(self, x, y, w, color=LINEA):
        capa = Image.new("RGBA", (self.px(w), max(1, round(self.e))), color)
        self.im.alpha_composite(capa, (self.px(x), self.px(y)))

    def texto(self, x, y, txt, rol, color=TEXTO, ancla="la", alfa=255, contorno=True):
        """Dibuja texto. ancla: 'la' izquierda, 'ma' centro, 'ra' derecha (y = arriba de las letras).
        contorno: borde negro fino para que las estrellas no se metan entre las letras."""
        f = fuente(rol, self.e)
        tr = tracking(rol) * self.e
        ancho = medir(txt, rol, self.e)
        X = self.px(x)
        if ancla[0] == "m":
            X -= ancho / 2
        elif ancla[0] == "r":
            X -= ancho
        asc, desc = f.getmetrics()
        sw = max(1, round(1.6 * self.e)) if contorno else 0
        m = 2 + sw
        capa = Image.new("RGBA", (int(ancho) + 2 * m + 2, asc + desc + 2 * m), (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)
        col = tuple(color[:3]) + (alfa,)
        extra = {"stroke_width": sw, "stroke_fill": (0, 0, 0, 255)} if sw else {}
        if tr:
            if sw:  # primero todos los contornos, luego las letras (para que no se tapen entre si)
                cx = 0.0
                for ch in txt:
                    d.text((cx + m, m - 1), ch, font=f, fill=(0, 0, 0, 255), **extra)
                    cx += f.getlength(ch) + tr
            cx = 0.0
            for ch in txt:
                d.text((cx + m, m - 1), ch, font=f, fill=col)
                cx += f.getlength(ch) + tr
        else:
            d.text((m, m - 1), txt, font=f, fill=col, **extra)
        self.im.alpha_composite(capa, (int(round(X)) - m, self.px(y) - m))
        return ancho / self.e

    def texto_centrado_v(self, x, y_centro, txt, rol, color=TEXTO, ancla="la", alfa=255, contorno=True):
        """Texto centrado verticalmente en y_centro (usa la altura de las mayusculas)."""
        f = fuente(rol, self.e)
        bb = f.getbbox("H")
        alto_cap = (bb[3] - bb[1]) / self.e
        arriba = bb[1] / self.e
        return self.texto(x, y_centro - alto_cap / 2 - arriba, txt, rol, color, ancla, alfa, contorno)

    def icono(self, nombre, x, y, tam, color=TEXTO):
        self.im.alpha_composite(icono(nombre, self.px(tam), color), (self.px(x), self.px(y)))

    def punto(self, cx, cy, r, color=BLANCO, alfa=255):
        T = max(2, self.px(r * 2)) * SS
        im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((0, 0, T - 1, T - 1), fill=tuple(color[:3]) + (alfa,))
        im = im.resize((T // SS, T // SS), Image.LANCZOS)
        self.im.alpha_composite(im, (self.px(cx) - im.width // 2, self.px(cy) - im.height // 2))

    def pegar_forma(self, origen, x, y, w, h, r):
        """Copia de 'origen' solo la forma de pastilla (sin las esquinas)."""
        X, Y = self.px(x), self.px(y)
        W, H = self.px(x + w) - X, self.px(y + h) - Y
        forma = pieza_redonda(W, H, round(r * self.e), (255, 255, 255, 255), None, 0).getchannel("A")
        self.im.paste(origen.crop((X, Y, X + W, Y + H)), (X, Y), forma)

    def oscurecer(self, alfa):
        self.im.alpha_composite(Image.new("RGBA", self.im.size, (0, 0, 0, alfa)))
