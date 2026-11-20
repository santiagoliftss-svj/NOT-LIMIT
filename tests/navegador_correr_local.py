"""Corre prueba_navegador.correr() tal cual (la que usa la autoprueba en Windows y Mac), pero en Linux: la
"pantalla" es una imagen de 1024x768 con la pagina de un Chromium sin ventana pegada en (12, 40), como si fuera una
ventana con su barra de titulo. Asi se prueba toda la logica de la prueba (buscar la pagina en la pantalla, medir,
disparar el bot en otro hilo, leer lo que quedo) antes de mandarla a GitHub.

    python tests/navegador_correr_local.py [aleks menus ...]
"""

import io
import json
import os
import queue
import sys
import threading
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "app"))

from PIL import Image  # noqa: E402

from clw import autoprueba, entrada, licencia, motor  # noqa: E402
from clw import prueba_navegador as pn  # noqa: E402

PANTALLA = (1024, 768)
VENTANA = (12, 40)          # donde queda la pagina en la "pantalla"
SALIDA = "/tmp/nl_nav_correr"


class Navegador(threading.Thread):
    """Chromium (Playwright) en su propio hilo: los demas hilos le mandan ordenes por una cola."""

    def __init__(self):
        super().__init__(daemon=True)
        self.ordenes = queue.Queue()
        self.url = None
        self.listo = threading.Event()

    def pedir(self, *orden):
        r = queue.Queue()
        self.ordenes.put((orden, r))
        ok, v = r.get(timeout=30)
        if not ok:
            raise v
        return v

    def run(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            nav = p.chromium.launch()
            page = nav.new_page(viewport={"width": 1000, "height": 700}, device_scale_factor=1)
            self.listo.set()
            while True:
                orden, r = self.ordenes.get()
                try:
                    r.put((True, self._hacer(page, *orden)))
                except Exception as e:
                    r.put((False, e))
                if orden[0] == "fin":
                    break
            nav.close()

    def _hacer(self, page, que, *a):
        if que == "ir":
            page.goto(a[0])
        elif que == "foto":
            return page.screenshot()
        elif que == "mover":
            page.mouse.move(*a)
        elif que == "abajo":
            page.mouse.down()
        elif que == "arriba":
            page.mouse.up()
        elif que == "teclas":
            page.keyboard.type(a[0], delay=18)
        elif que == "tecla":
            page.keyboard.press(a[0])
        elif que == "js":
            return page.evaluate(a[0])
        elif que == "url":
            return page.url
        return None


NAV = Navegador()


def pantalla():
    png = NAV.pedir("foto")
    img = Image.new("RGB", PANTALLA, (30, 30, 30))
    img.paste(Image.open(io.BytesIO(png)).convert("RGB"), VENTANA)
    return img


def a_pagina(x, y):
    return x - VENTANA[0], y - VENTANA[1]


def instalar():
    """Cambia la pantalla, el mouse y el teclado de verdad por los del Chromium sin ventana."""
    motor.pantalla_virtual = lambda: (0, 0) + PANTALLA
    motor.factor_zoom = lambda: 1.0

    def capturar_zona(left, top, w, h):
        return pantalla().crop((int(left), int(top), int(left + w), int(top + h)))

    def capturar(px, py):
        left, top, w, h = motor.calcular_zona(px, py, motor.pantalla_virtual(), 1.0)
        return capturar_zona(left, top, w, h), left, top

    motor.capturar_zona = capturar_zona
    motor.capturar = capturar

    def clic(x, y, lento=False):
        NAV.pedir("mover", *a_pagina(x, y))
        time.sleep(0.14 if lento else 0.05)
        NAV.pedir("abajo")
        time.sleep(0.09 if lento else 0.03)
        NAV.pedir("arriba")

    def foco_caja():
        f = NAV.pedir("js", """() => { const e = document.activeElement;
            if (!e || e === document.body) return {editable: null, caja: null};
            const b = e.getBoundingClientRect();
            const ed = e.isContentEditable || e.tagName === 'INPUT' || e.tagName === 'TEXTAREA';
            return {editable: ed, caja: [b.left, b.top, b.right, b.bottom]}; }""")
        if f["caja"]:
            x0, y0, x1, y1 = f["caja"]
            f["caja"] = (x0 + VENTANA[0], y0 + VENTANA[1], x1 + VENTANA[0], y1 + VENTANA[1])
        return f

    def arrastrar(x0, y0, x1, y1, pasos=24, cancelar=None, lento=False):
        NAV.pedir("mover", *a_pagina(x0, y0))
        time.sleep(0.25 if lento else 0.08)
        NAV.pedir("abajo")
        time.sleep(0.45 if lento else 0.15)
        for i in range(1, pasos + 1):
            t = i / pasos
            NAV.pedir("mover", *a_pagina(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            time.sleep(0.016)
        time.sleep(0.3 if lento else 0.12)
        NAV.pedir("arriba")

    mapa = {"derecha": "ArrowRight", "izquierda": "ArrowLeft", "arriba": "ArrowUp", "abajo": "ArrowDown",
            "retroceso": "Backspace", "escape": "Escape", "enter": "Enter"}
    nuevos = {
        "clic": clic, "arrastrar": arrastrar, "mover": lambda x, y: NAV.pedir("mover", *a_pagina(x, y)),
        "escribir": lambda texto, cancelar=None: NAV.pedir("teclas", texto) or True,
        "seleccionar_todo": lambda: NAV.pedir("tecla", "Control+A"),
        "deshacer": lambda: NAV.pedir("tecla", "Control+Z"),
        "tecla": lambda nombre, veces=1: [NAV.pedir("tecla", mapa[nombre]) for _ in range(veces)],
        "foco_caja": foco_caja, "tecla_abajo": lambda vk: False, "bajar_prioridad_hilo": lambda: None,
        "que_hay_en": lambda x, y: None, "forma_cursor": lambda: None, "preparar_accesibilidad": lambda x, y: None,
        "controles_en": lambda *a, **k: [], "ventana_raiz_en": lambda x, y: 0, "foco_editable": lambda: None,
        "soltar_ctrl_si_hace_falta": lambda: None,
    }
    for k, v in nuevos.items():
        setattr(entrada, k, v)

    def abrir(url, perfil):
        NAV.pedir("ir", url)
        return type("Proc", (), {"terminate": lambda self: None})(), "chromium-sin-ventana"
    pn._abrir = abrir


def main(solo=None):
    os.makedirs(SALIDA, exist_ok=True)
    licencia.PRUEBA = True
    NAV.start()
    NAV.listo.wait(30)
    instalar()
    srv = autoprueba._servidor_ia()
    res = {}
    t = time.time()
    pn.correr(SALIDA, autoprueba._IAFalsa, res, guardar=None, solo=solo)
    srv.shutdown()
    NAV.pedir("fin")
    r = res["navegador"]
    for nombre, d in (r.get("detalle") or {}).items():
        print(("OK   " if d.get("ok") else "FALLA") + f" {nombre}: {json.dumps(d.get('valores'), ensure_ascii=False)} "
              f"{d.get('actividad')} {d.get('error') or ''}")
        if d.get("traza"):
            print(d["traza"])
    print(f"\n{r.get('bien')} bien en {round(time.time() - t)}s | ok={r.get('ok')} | {r.get('error') or ''}")
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
