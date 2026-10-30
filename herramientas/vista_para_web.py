"""Dibuja la app como se ve de verdad (con la misma interfaz) para la pagina de descarga.

Uso (desde la raiz del repo):  python herramientas/vista_para_web.py
"""

import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "app"))

from clw import config  # noqa: E402
from clw.ui.vistas import Interfaz  # noqa: E402


class _App:
    def __init__(self):
        self.ui = None

    def iniciar(self):
        self.ui.evento_bot(("estado", "activo"))

    def detener(self):
        self.ui.evento_bot(("estado", "apagado"))

    def __getattr__(self, nombre):
        return lambda *a, **k: ""


class _Reloj:
    t = 100.0

    def __call__(self):
        return self.t


def main():
    c = config.Config(os.path.join(tempfile.mkdtemp(), "a.json"))
    c.poner_clave("claude", "sk-ant-x")
    reloj, app = _Reloj(), _App()
    ui = Interfaz(c, app, 2.0, reloj=reloj)
    app.ui = ui
    ui.enfocado = False                       # imagen quieta (estrella en su lugar)
    ui.inyectar()
    reloj.t += 3
    for hora, texto in (("21:09", "Escribió: Simón Bolívar"), ("21:12", "Marcó: 8,848 m"), ("21:14", "Marcó: Canberra")):
        ui.actividad.appendleft((hora, texto, "ok"))
    reloj.t += 3
    im = ui.render().convert("RGB")
    destino = os.path.join(RAIZ, "docs", "assets", "app.png")
    im.save(destino, optimize=True)
    print("listo", destino, im.size, os.path.getsize(destino) // 1024, "KB")


if __name__ == "__main__":
    main()
