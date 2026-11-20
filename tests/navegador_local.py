"""Las mismas paginas de prueba_navegador (ALEKS, juego, Kahoot, menus, flechas, casillas, completar, grafica), pero
en un Chromium sin ventana manejado con Playwright: la "pantalla" es la pagina, los clics y las teclas van a la
pagina y el OCR es el de verdad (tesseract). Sirve para probar rapido en Linux antes de mandarlo a Windows y Mac.

    python tests/navegador_local.py                 # todas
    python tests/navegador_local.py aleks menus     # solo esas
    CLW_FOCO=no python tests/navegador_local.py     # como si la compu NO dijera donde esta el cursor

Deja las fotos en /tmp/nl_nav/.
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

from clw import autoprueba, cerebro, config, licencia, motor  # noqa: E402
from clw import prueba_navegador as pn  # noqa: E402
from clw.bot import Bot  # noqa: E402

SALIDA = "/tmp/nl_nav"
W, H = 1000, 700


class Pantalla:
    """Mouse, teclado y 'donde esta el cursor' de la pagina (como UI Automation en Windows o AX en Mac)."""
    VK_ESCAPE = 0x1B
    VK_ATAJO = 0x11

    class Cancelado(Exception):
        pass

    def __init__(self, page, sabe_foco=True):
        self.page = page
        self.sabe_foco = sabe_foco
        self.log = []

    def tecla_abajo(self, vk):
        return False

    def mover(self, x, y):
        self.page.mouse.move(x, y)

    def clic(self, x, y, lento=False):
        self.log.append(("clic", round(x), round(y), lento))
        self.page.mouse.move(x, y)
        time.sleep(0.14 if lento else 0.05)
        self.page.mouse.down()
        time.sleep(0.09 if lento else 0.03)
        self.page.mouse.up()

    def arrastrar(self, x0, y0, x1, y1, pasos=24, cancelar=None, lento=False):
        self.log.append(("arrastrar", round(x0), round(y0), round(x1), round(y1)) + (("lento",) if lento else ()))
        self.page.mouse.move(x0, y0)
        self.page.mouse.down()
        if lento:
            time.sleep(0.4)
        self.page.mouse.move(x1, y1, steps=pasos)
        if lento:
            time.sleep(0.3)
        self.page.mouse.up()

    def escribir(self, texto, cancelar=None):
        self.log.append(("escribe", texto))
        self.page.keyboard.type(texto, delay=18)
        return True

    def seleccionar_todo(self):
        self.log.append(("ctrl+a",))
        self.page.keyboard.press("Control+A")

    def deshacer(self):
        self.log.append(("ctrl+z",))
        self.page.keyboard.press("Control+Z")

    def tecla(self, nombre, veces=1):
        mapa = {"derecha": "ArrowRight", "izquierda": "ArrowLeft", "arriba": "ArrowUp", "abajo": "ArrowDown",
                "retroceso": "Backspace", "escape": "Escape", "enter": "Enter"}
        for _ in range(max(1, int(veces))):
            self.page.keyboard.press(mapa[nombre])

    def foco_caja(self):
        if not self.sabe_foco:
            return None
        f = self.page.evaluate("""() => { const e = document.activeElement;
            if (!e || e === document.body) return {editable: null, caja: null};
            const b = e.getBoundingClientRect();
            const ed = e.isContentEditable || e.tagName === 'INPUT' || e.tagName === 'TEXTAREA';
            return {editable: ed, caja: [b.left, b.top, b.right, b.bottom]}; }""")
        return {"editable": f["editable"], "caja": tuple(f["caja"]) if f["caja"] else None}


def _foto(page, left, top, w, h):
    png = page.screenshot(clip={"x": left, "y": top, "width": max(1, w), "height": max(1, h)})
    return Image.open(io.BytesIO(png)).convert("RGB")


def correr(solo=None, sabe_foco=True):
    from playwright.sync_api import sync_playwright
    os.makedirs(SALIDA, exist_ok=True)
    licencia.PRUEBA = True
    srv_ia = autoprueba._servidor_ia()
    from clw.servidor_local import abrir
    srv = abrir(pn._Paginas)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    d = os.path.join(SALIDA, "datos")
    os.makedirs(d, exist_ok=True)
    os.environ["CLW_DATOS"] = d
    c = config.Config(os.path.join(d, "ajustes.json"))
    c["guardar_capturas"] = True
    c.poner_clave("claude", "sk-ant-prueba")
    resultados = {}
    with sync_playwright() as p:
        nav = p.chromium.launch()
        page = nav.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pant = Pantalla(page, sabe_foco)
        motor.capturar_zona = lambda left, top, w, h: _foto(page, left, top, w, h)
        bot = Bot(c, queue.Queue(), acciones=pant)
        for nombre, contestar, tipo, enfoque, disparo, revisar in pn.PRUEBAS:
            if solo and nombre not in solo:
                continue
            t0 = time.time()
            pn._Estado.prueba = nombre
            page.goto(base + "/p/" + nombre)
            time.sleep(1.0)
            lay = pn._Estado.layout.get(nombre)
            r = lay["r"]

            def punto(clave, fx, fy, r=r):
                x, y, w, h = r[clave]
                if 0 < fx < 1 or 0 < fy < 1:
                    return x + w * fx, y + h * fy
                return x + fx, y + fy
            if enfoque:
                pant.clic(*punto(enfoque, 0.5, 0.5), lento=True)
                time.sleep(0.4)
            x, y, w, h = r["pregunta"]
            pn._Ahora.caja = (x - 14, y - 14, x + w + 14, y + h + 14)
            X, Y = punto(*disparo)
            pn._Ahora.zona = (0, 0, W, H)
            _f = pn._fases(contestar, tipo)
            def _grabar(t, _f=_f, nombre=nombre):
                with open(os.path.join(SALIDA, f"{nombre}_ia.txt"), "a", encoding="utf-8") as fh:
                    fh.write(t + "\n----\n")
                s = _f(t)
                with open(os.path.join(SALIDA, f"{nombre}_ia.txt"), "a", encoding="utf-8") as fh:
                    fh.write("=> " + s + "\n=========\n")
                return s
            try:
                os.remove(os.path.join(SALIDA, f"{nombre}_ia.txt"))
            except OSError:
                pass
            autoprueba._IAFalsa.elegir = _grabar
            pant.log = []
            page.mouse.move(X, Y)
            img = _foto(page, 0, 0, W, H)
            pedidos0 = autoprueba._IAFalsa.pedidos
            try:
                res = bot.contestar(img, 0, 0, X, Y, 1.0)
                error = None
            except Exception as e:
                import traceback
                res, error = None, traceback.format_exc()[-1200:]
            time.sleep(0.8)
            v = page.evaluate("() => window.valores ? window.valores() : {}")
            ok = bool(revisar(v))
            plan, ej = res if res else (None, None)
            resultados[nombre] = {
                "ok": ok, "valores": v, "seg": round(time.time() - t0, 1),
                "pedidos_ia": autoprueba._IAFalsa.pedidos - pedidos0,
                "pasos": [(s["hacer"], s.get("texto") or s.get("opcion") or "") for s in plan.pasos] if plan else None,
                "rechazadas": [m for _, m in plan.rechazadas] if plan else None,
                "fallas": [m for _, m in ej.fallas] if ej else None,
                "acciones": pant.log[-40:], "error": error}
            _foto(page, 0, 0, W, H).save(os.path.join(SALIDA, f"{nombre}.png"))
            for f in ("ultima_revision.png",):
                ruta = os.path.join(d, "revision", f)
                if os.path.exists(ruta):
                    os.replace(ruta, os.path.join(SALIDA, f"{nombre}_revision.png"))
            print(("OK   " if ok else "FALLA") + f" {nombre}: {json.dumps(v, ensure_ascii=False)}  "
                  f"fallas={resultados[nombre]['fallas']} rechazadas={resultados[nombre]['rechazadas']}", flush=True)
            if not ok:
                print("      pasos:", resultados[nombre]["pasos"])
                print("      acciones:", pant.log[-25:])
                if error:
                    print(error)
        nav.close()
    srv.shutdown()
    srv_ia.shutdown()
    with open(os.path.join(SALIDA, "resultado.json"), "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2, default=str)
    return resultados


if __name__ == "__main__":
    r = correr(sys.argv[1:] or None, sabe_foco=os.environ.get("CLW_FOCO") != "no")
    malas = [n for n, x in r.items() if not x["ok"]]
    print(f"\n{len(r) - len(malas)}/{len(r)} bien" + (f" | fallaron: {malas}" if malas else ""))
    sys.exit(1 if malas else 0)
