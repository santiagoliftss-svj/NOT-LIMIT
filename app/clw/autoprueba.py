"""Autoprueba del .exe ya armado: 'CLW GANG.exe --autoprueba <carpeta>'.

Revisa OCR, motor, proveedores (con un servidor falso), cifrado, interfaz y, si hay escritorio,
una prueba de punta a punta: Ctrl + clic de verdad, captura, IA falsa, clic y escritura en ventanas de prueba.
Guarda resultado.json y capturas PNG. Sale con 0 si todo lo obligatorio salio bien.
"""

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RESULTADOS = {}
OBLIGATORIAS = ("ocr", "motor", "proveedores", "cifrado", "interfaz", "ventana")


def _paso(nombre, fn):
    t = time.time()
    try:
        detalle = fn()
        RESULTADOS[nombre] = {"ok": True, "seg": round(time.time() - t, 2), "detalle": detalle}
    except Exception as e:
        RESULTADOS[nombre] = {"ok": False, "seg": round(time.time() - t, 2), "error": f"{type(e).__name__}: {e}",
                              "traza": traceback.format_exc()[-1500:]}


# ---------------------------------------------------------------- IA falsa local

class _IAFalsa(BaseHTTPRequestHandler):
    elegir = None   # funcion(texto_del_pedido) -> str JSON de respuesta

    def log_message(self, *a):
        pass

    def do_GET(self):
        self._enviar(200, {"data": [], "models": []})

    def do_POST(self):
        largo = int(self.headers.get("content-length") or 0)
        cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        texto = ""
        try:
            if "messages" in cuerpo and isinstance(cuerpo["messages"][0].get("content"), list):
                texto = cuerpo["messages"][0]["content"][1]["text"]
            elif "contents" in cuerpo:
                texto = cuerpo["contents"][0]["parts"][1]["text"]
            else:
                texto = cuerpo["messages"][1]["content"][0]["text"]
        except Exception:
            pass
        if (cuerpo.get("thinking") or {}).get("type") == "disabled" and cuerpo.get("model") == "modelo-terco":
            return self._enviar(400, {"type": "error", "error": {"type": "invalid_request_error",
                                                                 "message": "thinking.type.disabled is not supported"}})
        salida = _IAFalsa.elegir(texto) if _IAFalsa.elegir else '{"tipo":"ninguna"}'
        if "contents" in cuerpo:
            return self._enviar(200, {"candidates": [{"content": {"parts": [{"text": salida}]}, "finishReason": "STOP"}]})
        if "max_completion_tokens" in cuerpo:
            return self._enviar(200, {"choices": [{"message": {"content": salida}, "finish_reason": "stop"}]})
        return self._enviar(200, {"content": [{"type": "text", "text": salida}], "stop_reason": "end_turn"})

    def _enviar(self, estado, datos):
        crudo = json.dumps(datos).encode()
        self.send_response(estado)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)


def _servidor_ia():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _IAFalsa)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    for p in ("CLAUDE", "GEMINI", "OPENAI"):
        os.environ[f"CLW_API_{p}"] = base
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    return srv


def _lineas(texto):
    out = []
    for l in texto.splitlines():
        if l.startswith("[") and "]" in l and "(" in l:
            ident = l[1:l.index("]")]
            x, y = l.split("(")[1].split(")")[0].split(",")
            out.append((ident, int(x), int(y), l[l.index(")") + 2:]))
    return out


def _buscar(texto, fragmento, campos=False):
    for ident, x, y, t in _lineas(texto):
        if ident.startswith("C") == campos and fragmento.lower() in t.lower():
            return ident
    return None


# ---------------------------------------------------------------- pruebas

class _Acciones:
    VK_ESCAPE = 0x1B

    class Cancelado(Exception):
        pass

    def __init__(self):
        self.log = []

    def tecla_abajo(self, vk):
        return False

    def clic(self, x, y):
        self.log.append(("clic", round(x), round(y)))

    def seleccionar_todo(self):
        pass

    def escribir(self, texto, cancelar=None):
        self.log.append(("escribe", texto))
        return True


def p_ocr():
    from .ocr import OCR
    o = OCR()
    assert o.disponible, "no se encontro tesseract"
    idiomas = o.idiomas()
    assert "spa" in idiomas, f"falta espanol: {idiomas}"
    return {"exe": o.exe, "tessdata": o.tessdata, "idiomas": idiomas}


def p_motor():
    from . import motor, muestras
    from .ocr import OCR
    o = OCR()
    det = {}
    img, tarjetas, (px, py) = muestras.quiz_oscuro()
    res = motor.procesar(img, px, py, lambda b, m, t: (json.dumps({"tipo": "opcion", "ids": [int(_buscar(t, "París"))]}), False), 1.0, o)
    acc = _Acciones()
    motor.ejecutar(res, 0, 0, acciones=acc)
    c = tarjetas["París"]
    assert acc.log and c[0] <= acc.log[0][1] <= c[2] and c[1] <= acc.log[0][2] <= c[3], acc.log
    det["quiz"] = acc.log

    img, cajitas, (px, py) = muestras.cajitas_mate()
    res = motor.procesar(img, px, py, lambda b, m, t: (json.dumps({"tipo": "abierta", "respuestas": [
        {"campo": "C0", "texto": "13/12"}, {"campo": "C1", "texto": "5/13"}, {"campo": "C2", "texto": "√3/2"}]}), False), 1.0, o)
    acc = _Acciones()
    motor.ejecutar(res, 0, 0, acciones=acc)
    clics = [a for a in acc.log if a[0] == "clic"]
    assert len(clics) == 3, acc.log
    for a, caja in zip(clics, cajitas):
        assert caja[0] <= a[1] <= caja[2] and caja[1] <= a[2] <= caja[3], (a, caja)
    det["cajitas"] = acc.log
    return det


def p_proveedores():
    from .proveedores import ClienteIA, validar_clave
    _IAFalsa.elegir = lambda t: '{"tipo":"opcion","ids":[0]}'
    cli = ClienteIA()
    out = {}
    for prov, modelo in (("claude", "modelo-terco"), ("gemini", "gemini-flash-latest"), ("openai", "gpt-6-luna")):
        texto, cortado = cli.preguntar(prov, modelo, "clave", "sis", "QUJD", "image/png", "hola")
        assert '"ids"' in texto, (prov, texto)
        out[prov] = texto
        assert validar_clave(prov, "clave") is None
    return out


def p_cifrado():
    from . import config
    v = config.proteger("sk-ant-prueba")
    assert config.desproteger(v) == "sk-ant-prueba"
    if sys.platform == "win32":
        assert v.startswith("dpapi:"), v[:10]
    return v[:6]


def p_interfaz(salida):
    from . import config
    from .ui.vistas import Interfaz

    class App:
        def __getattr__(self, n):
            return lambda *a, **k: ""

    d = tempfile.mkdtemp()
    hechas = []
    for escala in (1.0, 1.5):
        c = config.Config(os.path.join(d, f"a{escala}.json"))
        ui = Interfaz(c, App(), escala)
        ui.render(0).convert("RGB").save(os.path.join(salida, f"ui_{escala}_inicio.png"))
        c.poner_clave("claude", "sk-ant-x")
        ui.evento_bot(("estado", "activo"))
        ui.evento_bot(("actividad", "Marcó: París", "ok"))
        ui.render(0.6).convert("RGB").save(os.path.join(salida, f"ui_{escala}_activo.png"))
        ui.capa = "modelos"
        ui.render(0).convert("RGB").save(os.path.join(salida, f"ui_{escala}_modelos.png"))
        ui.capa = None
        ui.pantalla = "ajustes"
        ui.render(0).convert("RGB").save(os.path.join(salida, f"ui_{escala}_ajustes.png"))
        ui.abrir_clave("gemini")
        ui.render(0).convert("RGB").save(os.path.join(salida, f"ui_{escala}_clave.png"))
        hechas.append(escala)
    return hechas


def _ventana_y_e2e(salida):
    """Abre la ventana real y hace la prueba de punta a punta en el mismo hilo de Tk."""
    import queue
    import tkinter as tk
    from PIL import Image, ImageGrab, ImageTk

    from . import config, entrada, motor, muestras
    from .bot import Bot
    from .ui.ventana import Ventana

    d = tempfile.mkdtemp()
    os.environ["CLW_DATOS"] = d
    c = config.Config(os.path.join(d, "ajustes.json"))
    c.poner_clave("claude", "sk-ant-prueba")
    bot = Bot(c, queue.Queue())
    v = Ventana(c, bot, motor.factor_zoom())
    root = v.root
    estado = {"fase": "ventana", "fin": False}
    pruebas = {}

    def grab_ventana(nombre, w=None):
        w = w or root
        w.update()
        x, y = w.winfo_rootx(), w.winfo_rooty()
        im = ImageGrab.grab(bbox=(x, y, x + w.winfo_width(), y + w.winfo_height()), all_screens=True)
        im.save(os.path.join(salida, nombre + ".png"))
        return im

    def paso_ventana():
        try:
            im = grab_ventana("ventana_inicio")
            claros = sum(1 for p in im.convert("L").getdata() if p > 200)
            RESULTADOS["ventana"] = {"ok": claros > 500, "detalle": {"tam": im.size, "pixeles_claros": claros,
                                                                     "escala": v.e}}
            v.iniciar()
            root.after(700, paso_ventana_activa)
        except Exception as e:
            RESULTADOS["ventana"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            terminar()

    def paso_ventana_activa():
        try:
            grab_ventana("ventana_activa")
        except Exception:
            pass
        root.after(400, e2e_opcion)

    # -------- E2E 1: opcion multiple
    def e2e_opcion():
        try:
            img, tarjetas, (qx, qy) = muestras.quiz_oscuro()
            top = tk.Toplevel(root)
            top.title("Prueba opcion")
            top.geometry(f"{img.width}x{img.height}+0+0")
            top.attributes("-topmost", True)
            foto = ImageTk.PhotoImage(img)
            lbl = tk.Label(top, image=foto, bd=0)
            lbl.image = foto
            lbl.place(x=0, y=0)
            clics = []
            lbl.bind("<Button-1>", lambda e: clics.append((e.x, e.y)))
            top.update()
            _IAFalsa.elegir = lambda t: json.dumps({"tipo": "opcion", "ids": [int(_buscar(t, "París") or 0)]})
            ox, oy = lbl.winfo_rootx(), lbl.winfo_rooty()
            threading.Thread(target=_ctrl_clic, args=(ox + qx, oy + qy), daemon=True).start()
            inicio = time.time()

            def revisar():
                c = tarjetas["París"]
                buenos = [p for p in clics if c[0] <= p[0] <= c[2] and c[1] <= p[1] <= c[3]]
                if buenos or time.time() - inicio > 25:
                    pruebas["opcion"] = {"ok": bool(buenos), "clics": clics, "esperado": c,
                                         "actividad": list(v.ui.actividad)}
                    try:
                        grab_ventana("e2e_opcion", top)
                    except Exception:
                        pass
                    top.destroy()
                    root.after(300, e2e_escribir)
                else:
                    root.after(200, revisar)
            root.after(500, revisar)
        except Exception as e:
            pruebas["opcion"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, e2e_escribir)

    # -------- E2E 2: escribir en un campo de texto (con acentos)
    def e2e_escribir():
        try:
            top = tk.Toplevel(root)
            top.title("Prueba escribir")
            top.geometry("820x360+0+0")
            top.configure(bg="white")
            top.attributes("-topmost", True)
            tk.Label(top, text="1. ¿Cuánto es dos más dos?", font=("Arial", 20), bg="white", fg="#222").place(x=40, y=40)
            ent = tk.Entry(top, font=("Arial", 18), relief="solid", bd=1, fg="#888")
            ent.insert(0, "Escriba su respuesta")
            ent.place(x=40, y=110, width=600, height=44)
            top.update()
            esperado = "Cuatro, señor ¿sí?"

            def elegir(t):
                campo = _buscar(t, "", campos=True) or _buscar(t, "Escriba")
                obj = campo if (campo or "").startswith("C") else int(campo or 0)
                return json.dumps({"tipo": "abierta", "respuestas": [{"campo": obj, "texto": esperado}]})
            _IAFalsa.elegir = elegir
            lx, ly = top.winfo_rootx(), top.winfo_rooty()
            threading.Thread(target=_ctrl_clic, args=(lx + 120, ly + 55), daemon=True).start()
            inicio = time.time()

            def revisar():
                if ent.get() == esperado or time.time() - inicio > 25:
                    pruebas["escribir"] = {"ok": ent.get() == esperado, "texto": ent.get(), "actividad": list(v.ui.actividad)}
                    try:
                        grab_ventana("e2e_escribir", top)
                    except Exception:
                        pass
                    top.destroy()
                    root.after(200, terminar)
                else:
                    root.after(200, revisar)
            root.after(500, revisar)
        except Exception as e:
            pruebas["escribir"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, terminar)

    def terminar():
        RESULTADOS["e2e"] = {"ok": all(p.get("ok") for p in pruebas.values()) and len(pruebas) == 2,
                             "detalle": pruebas}
        try:
            for f in os.listdir(os.path.join(d, "revision")):
                Image.open(os.path.join(d, "revision", f)).save(os.path.join(salida, "revision_" + f))
        except Exception:
            pass
        estado["fin"] = True
        try:
            bot.detener()
        except Exception:
            pass
        root.after(100, root.destroy)

    root.after(900, paso_ventana)
    root.after(120000, lambda: (not estado["fin"]) and terminar())
    root.mainloop()


def _ctrl_clic(x, y):
    """Ctrl + clic de verdad (como si lo hiciera el usuario)."""
    from . import entrada
    time.sleep(0.4)
    entrada.U32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    entrada._enviar([(entrada.VK_CONTROL, 0, 0)])
    time.sleep(0.08)
    entrada.U32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.08)
    entrada.U32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.08)
    entrada._enviar([(entrada.VK_CONTROL, 0, 2)])


def main(salida):
    os.makedirs(salida, exist_ok=True)
    srv = _servidor_ia()
    _paso("ocr", p_ocr)
    _paso("motor", p_motor)
    _paso("proveedores", p_proveedores)
    _paso("cifrado", p_cifrado)
    _paso("interfaz", lambda: p_interfaz(salida))
    try:
        _ventana_y_e2e(salida)
    except Exception as e:
        RESULTADOS.setdefault("ventana", {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]})
    srv.shutdown()
    RESULTADOS["_version"] = __import__("clw.version", fromlist=["VERSION"]).VERSION
    with open(os.path.join(salida, "resultado.json"), "w", encoding="utf-8") as f:
        json.dump(RESULTADOS, f, ensure_ascii=False, indent=2, default=str)
    malas = [n for n in OBLIGATORIAS if not RESULTADOS.get(n, {}).get("ok")]
    return 1 if malas else 0
