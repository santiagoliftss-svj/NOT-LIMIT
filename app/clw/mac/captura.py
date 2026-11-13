"""Leer la pantalla en Mac con 'screencapture' (la herramienta de Apple; necesita el permiso de Grabacion de
pantalla). La imagen sale en pixeles reales (Retina = 2x) y en la misma escala que usan los clics."""

import os
import subprocess
import tempfile

from PIL import Image

from . import entrada


def factor_zoom():
    return entrada.escala_actual()


def pantalla_virtual():
    x, y = entrada.posicion_puntos()
    (bx, by, bw, bh), s = entrada.pantalla_en(x, y)
    return int(bx * s), int(by * s), int(bw * s), int(bh * s)


def zona(x, y, pantalla, tam, arriba):
    """Rectangulo a capturar (puntos) alrededor de (x, y), sin salirse de la pantalla."""
    bx, by, bw, bh = pantalla
    w, h = min(tam[0], bw), min(tam[1], bh)
    left = min(max(x - w / 2, bx), bx + bw - w)
    top = min(max(y - arriba, by), by + bh - h)
    return int(left), int(top), int(w), int(h)


def foto(x, y, w, h):
    fd, ruta = tempfile.mkstemp(suffix=".png", prefix="nolimit_")
    os.close(fd)
    try:
        p = subprocess.run(["/usr/sbin/screencapture", "-x", "-R", f"{x},{y},{w},{h}", "-t", "png", ruta],
                           capture_output=True, timeout=15)
        if p.returncode != 0 or not os.path.getsize(ruta):
            raise RuntimeError("no se pudo leer la pantalla: " +
                               ((p.stderr or b"").decode("utf-8", "ignore").strip()[:200] or "sin permiso"))
        img = Image.open(ruta)
        img.load()
        return img.convert("RGB")
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


def capturar_zona(left, top, w, h):
    """Foto de un rectangulo en pixeles (como lo maneja el motor)."""
    import math
    s = entrada.escala_actual()
    x, y = int(math.floor(left / s)), int(math.floor(top / s))
    ww, hh = int(math.ceil((left + w) / s)) - x, int(math.ceil((top + h) / s)) - y
    img = foto(x, y, max(1, ww), max(1, hh))
    W, H = max(1, round(ww * s)), max(1, round(hh * s))
    if img.size != (W, H):
        img = img.resize((W, H), Image.LANCZOS)
    dx, dy = int(round(left - x * s)), int(round(top - y * s))
    return img.crop((dx, dy, dx + int(w), dy + int(h)))


def capturar(px, py, tam, arriba):
    """(imagen, left, top) en pixeles, como en Windows."""
    s = entrada.escala_actual()
    x, y = px / s, py / s
    pantalla, _ = entrada.pantalla_en(x, y)
    left, top, w, h = zona(x, y, pantalla, tam, arriba)
    img = foto(left, top, w, h)
    W, H = max(1, round(w * s)), max(1, round(h * s))
    if img.size != (W, H):
        img = img.resize((W, H), Image.LANCZOS)
    return img, round(left * s), round(top * s)
