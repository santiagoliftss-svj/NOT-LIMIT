"""Autoprueba del .exe ya armado: 'NO LIMIT.exe --autoprueba <carpeta>'.

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
# se reportan aparte (dependen de la barra de tareas y del escritorio de la maquina de pruebas):
# bandeja, juego, reabrir, e2e, cpu


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
    pedidos = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        self._enviar(200, {"data": [], "models": []})

    def do_POST(self):
        _IAFalsa.pedidos += 1
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
        def __init__(self):
            self.ui = None

        def iniciar(self):
            self.ui.evento_bot(("estado", "activo"))

        def detener(self):
            self.ui.evento_bot(("estado", "apagado"))

        def __getattr__(self, n):
            return lambda *a, **k: ""

    class Reloj:
        t = 100.0

        def __call__(self):
            return self.t

    def foto(ui, reloj, nombre, seg=0.0):
        fin = reloj.t + seg
        while reloj.t < fin:
            reloj.t = min(fin, reloj.t + 1 / 30)
            ui.render()
        ui.render().convert("RGB").save(os.path.join(salida, nombre + ".png"))

    d = tempfile.mkdtemp()
    hechas = []
    for escala in (1.0, 1.5):
        c = config.Config(os.path.join(d, f"a{escala}.json"))
        reloj = Reloj()
        app = App()
        ui = Interfaz(c, app, escala, reloj=reloj)
        app.ui = ui
        foto(ui, reloj, f"ui_{escala}_inicio")
        c.poner_clave("claude", "sk-ant-x")
        ui.inyectar()
        foto(ui, reloj, f"ui_{escala}_encendiendo", 0.3)
        foto(ui, reloj, f"ui_{escala}_anillo", 0.35)
        foto(ui, reloj, "_", 0.6)
        assert ui.debe_esconder(), "despues de INYECTAR la ventana debe irse junto al reloj"
        ui.evento_bot(("actividad", "Marcó: Canberra", "ok"))
        foto(ui, reloj, f"ui_{escala}_activo", 0.6)
        ui.capa = "modelos"
        foto(ui, reloj, f"ui_{escala}_modelos", 0.3)
        ui.capa = None
        ui.pantalla = "ajustes"
        foto(ui, reloj, f"ui_{escala}_ajustes")
        ui.abrir_clave("gemini")
        foto(ui, reloj, f"ui_{escala}_clave", 0.4)
        hechas.append(escala)
    try:
        os.remove(os.path.join(salida, "_.png"))
    except OSError:
        pass
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

    def copiar_revision(nombre):
        import shutil
        for f in ("ultima_captura.png", "ultima_revision.png"):
            origen = os.path.join(d, "revision", f)
            if os.path.exists(origen):
                shutil.copy(origen, os.path.join(salida, f"{nombre}_{f}"))

    def grab_ventana(nombre, w=None):
        w = w or root
        w.update()
        x, y = w.winfo_rootx(), w.winfo_rooty()
        im = ImageGrab.grab(bbox=(x, y, x + w.winfo_width(), y + w.winfo_height()), all_screens=True)
        im.save(os.path.join(salida, nombre + ".png"))
        return im

    cpu = {}

    def grab_seguro(nombre, w=None):
        try:
            grab_ventana(nombre, w)
        except Exception:
            pass

    def medir_cpu(nombre, seg, despues):
        """% de un nucleo que usa NO LIMIT (todos sus hilos) durante 'seg' segundos."""
        t0, c0 = time.time(), time.process_time()

        def fin():
            cpu[nombre] = round(100 * (time.process_time() - c0) / max(0.001, time.time() - t0), 2)
            despues()
        root.after(int(seg * 1000), fin)

    def paso_ventana():
        try:
            im = grab_ventana("ventana_inicio")
            claros = sum(1 for p in im.convert("L").getdata() if p > 200)
            RESULTADOS["ventana"] = {"ok": claros > 500, "detalle": {"tam": im.size, "pixeles_claros": claros,
                                                                     "escala": v.e, "bandeja": v.en_bandeja()}}
            medir_cpu("ventana_al_frente", 2.0, paso_inyectar)
        except Exception as e:
            RESULTADOS["ventana"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            terminar()

    def paso_inyectar():
        v.ui.inyectar()                     # como tocar el boton
        root.after(300, lambda: grab_seguro("ventana_encendiendo"))
        root.after(1800, paso_escondida)

    def paso_escondida():
        try:
            det = {"activo": bot.activo, "visible": v.visible, "estado_tk": root.state(), "bandeja": v.en_bandeja()}
            RESULTADOS["bandeja"] = {"ok": bool(bot.activo and not v.visible and det["estado_tk"] == "withdrawn"
                                                and det["bandeja"]), "detalle": det}
        except Exception as e:
            RESULTADOS["bandeja"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
        medir_cpu("escondida_y_activa", 3.0, e2e_opcion)

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
                    copiar_revision("opcion")
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

    # -------- E2E 2: escribir en un campo de texto de Tk (con acentos)
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
            diag = {"teclas": [], "foco": [], "clics": []}
            top.bind("<Key>", lambda e: diag["teclas"].append((e.keysym, e.char)) if len(diag["teclas"]) < 60 else None)
            ent.bind("<FocusIn>", lambda e: diag["foco"].append("entry"), add="+")
            ent.bind("<Button-1>", lambda e: diag["clics"].append((e.x, e.y)), add="+")
            top.update()

            def elegir(t):
                campo = _buscar(t, "", campos=True) or _buscar(t, "Escriba")
                obj = campo if (campo or "").startswith("C") else int(campo or 0)
                diag["ia_campo"] = obj
                return json.dumps({"tipo": "abierta", "respuestas": [{"campo": obj, "texto": ESPERADO}]})
            _IAFalsa.elegir = elegir
            lx, ly = top.winfo_rootx(), top.winfo_rooty()
            diag["entry_pantalla"] = (ent.winfo_rootx(), ent.winfo_rooty(), ent.winfo_width(), ent.winfo_height())
            threading.Thread(target=_ctrl_clic, args=(lx + 120, ly + 55), daemon=True).start()
            inicio = time.time()

            def revisar():
                if ESPERADO in ent.get() or time.time() - inicio > 25:
                    time.sleep(0.3)
                    pruebas["escribir_tk"] = {"ok": ESPERADO in ent.get(), "exacto": ent.get() == ESPERADO,
                                              "texto": ent.get(), "diag": diag, "actividad": list(v.ui.actividad)[:2]}
                    copiar_revision("escribir_tk")
                    try:
                        grab_ventana("e2e_escribir_tk", top)
                    except Exception:
                        pass
                    top.destroy()
                    root.after(300, e2e_nativo)
                else:
                    root.after(200, revisar)
            root.after(500, revisar)
        except Exception as e:
            pruebas["escribir_tk"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, e2e_nativo)

    # -------- E2E 3: escribir en un campo nativo de Windows (como los de los navegadores)
    def e2e_nativo():
        try:
            top = tk.Toplevel(root)
            top.title("Prueba nativo")
            top.geometry("820x360+0+0")
            top.configure(bg="white")
            top.attributes("-topmost", True)
            tk.Label(top, text="2. ¿Cómo se dice hola en inglés?", font=("Arial", 20), bg="white", fg="#222").place(x=40, y=40)
            top.update()
            lx, ly = top.winfo_rootx(), top.winfo_rooty()
            hwnd = _edit_nativo(lx + 40, ly + 110, 600, 44, "Escriba su respuesta")
            diag = {"hwnd": hwnd}

            def elegir(t):
                campo = _buscar(t, "", campos=True) or _buscar(t, "Escriba")
                obj = campo if (campo or "").startswith("C") else int(campo or 0)
                diag["ia_campo"] = obj
                return json.dumps({"tipo": "abierta", "respuestas": [{"campo": obj, "texto": ESPERADO}]})
            _IAFalsa.elegir = elegir
            # el Ctrl + clic va sobre la caja nativa (si se pica la ventana de Tk, esa se pone encima)
            threading.Thread(target=_ctrl_clic, args=(lx + 500, ly + 132), daemon=True).start()
            inicio = time.time()

            def revisar():
                texto = _texto_nativo(hwnd)
                if ESPERADO in texto or time.time() - inicio > 25:
                    pruebas["escribir_nativo"] = {"ok": ESPERADO in texto, "exacto": texto == ESPERADO, "texto": texto,
                                                  "diag": diag, "actividad": list(v.ui.actividad)[:2]}
                    copiar_revision("escribir_nativo")
                    try:
                        grab_ventana("e2e_escribir_nativo", top)
                    except Exception:
                        pass
                    _cerrar_nativo(hwnd)
                    top.destroy()
                    root.after(300, juego_pantalla_completa)
                else:
                    root.after(200, revisar)
            root.after(500, revisar)
        except Exception as e:
            pruebas["escribir_nativo"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, juego_pantalla_completa)

    # -------- un "juego" en pantalla completa: Ctrl + clic ahi NO debe hacer nada
    juego = {}

    def juego_pantalla_completa():
        try:
            antes, pedidos = bot.ignorados.get("pantalla_completa", 0), _IAFalsa.pedidos
            W, H = root.winfo_screenwidth(), root.winfo_screenheight()
            top = tk.Toplevel(root)
            top.overrideredirect(True)
            top.geometry(f"{W}x{H}+0+0")
            top.configure(bg="#0b2a12")
            tk.Label(top, text="1. ¿Capital de Francia?   París   Roma", font=("Arial", 28), bg="#0b2a12",
                     fg="white").place(x=80, y=80)
            top.attributes("-topmost", True)
            top.update()
            top.lift()
            top.focus_force()
            _IAFalsa.elegir = lambda t: json.dumps({"tipo": "ninguna"})

            def clic():
                time.sleep(0.6)
                juego["al_frente"] = entrada.clase_ventana(entrada.ventana_al_frente())
                juego["detecta_juego"] = entrada.juego_en_pantalla_completa()
                _ctrl_clic(260, 100)
            threading.Thread(target=clic, daemon=True).start()

            def revisar():
                juego["ignorados"] = bot.ignorados.get("pantalla_completa", 0) - antes
                juego["pedidos_ia"] = _IAFalsa.pedidos - pedidos
                juego["ok_pantalla_completa"] = juego["ignorados"] >= 1 and juego["pedidos_ia"] == 0
                top.destroy()
                root.after(300, ctrl_sostenido)
            root.after(2800, revisar)
        except Exception as e:
            juego["error"] = repr(e)
            root.after(100, ctrl_sostenido)

    # -------- Ctrl apretado mucho rato (como en juegos para agacharse) + clic: tampoco hace nada
    def ctrl_sostenido():
        try:
            antes, pedidos = bot.ignorados.get("ctrl_sostenido", 0), _IAFalsa.pedidos
            top = tk.Toplevel(root)
            top.title("Prueba ctrl")
            top.geometry("700x240+0+0")
            top.configure(bg="white")
            tk.Label(top, text="3. ¿Cuánto es 5 x 5?", font=("Arial", 22), bg="white", fg="#222").place(x=40, y=60)
            top.attributes("-topmost", True)
            top.update()
            lx, ly = top.winfo_rootx(), top.winfo_rooty()

            def hilo():
                entrada._enviar([(entrada.VK_CONTROL, 0, 0)])
                time.sleep(3.3)
                entrada.U32.SetCursorPos(int(lx + 150), int(ly + 80))
                time.sleep(0.1)
                entrada.U32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.08)
                entrada.U32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(0.1)
                entrada._enviar([(entrada.VK_CONTROL, 0, 2)])
            threading.Thread(target=hilo, daemon=True).start()

            def revisar():
                juego["ignorados_ctrl"] = bot.ignorados.get("ctrl_sostenido", 0) - antes
                juego["pedidos_ia_ctrl"] = _IAFalsa.pedidos - pedidos
                juego["ok_ctrl_sostenido"] = juego["ignorados_ctrl"] >= 1 and juego["pedidos_ia_ctrl"] == 0
                top.destroy()
                RESULTADOS["juego"] = {"ok": bool(juego.get("ok_pantalla_completa") and juego.get("ok_ctrl_sostenido")),
                                       "detalle": juego}
                root.after(300, reabrir)
            root.after(5200, revisar)
        except Exception as e:
            juego["error_ctrl"] = repr(e)
            RESULTADOS["juego"] = {"ok": False, "detalle": juego}
            root.after(100, reabrir)

    # -------- abrir NO LIMIT otra vez (como doble clic al icono): la ventana escondida vuelve
    def reabrir():
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.OpenEventW.restype = ctypes.c_void_p
            h = k32.OpenEventW(0x0002, False, "CLWGANG_mostrar")
            if h:
                k32.SetEvent(ctypes.c_void_p(h))
                k32.CloseHandle(ctypes.c_void_p(h))

            def revisar():
                det = {"evento": bool(h), "visible": v.visible, "estado_tk": root.state(), "activo": bot.activo}
                RESULTADOS["reabrir"] = {"ok": bool(h and v.visible and det["estado_tk"] == "normal"), "detalle": det}
                grab_seguro("ventana_reabierta")
                root.after(200, terminar)
            root.after(1500, revisar)
        except Exception as e:
            RESULTADOS["reabrir"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, terminar)

    def terminar():
        if estado["fin"]:
            return
        RESULTADOS["e2e"] = {"ok": all(p.get("ok") for p in pruebas.values()) and len(pruebas) == 3,
                             "detalle": pruebas}
        RESULTADOS["cpu"] = {"ok": cpu.get("escondida_y_activa", 99) < 5, "detalle": cpu}
        try:
            for f in os.listdir(os.path.join(d, "revision")):
                Image.open(os.path.join(d, "revision", f)).save(os.path.join(salida, "revision_" + f))
        except Exception:
            pass
        estado["fin"] = True
        root.after(100, v.salir)

    root.after(900, paso_ventana)
    root.after(150000, terminar)
    root.mainloop()


ESPERADO = "Cuatro, señor ¿sí?"


def _edit_nativo(x, y, w, h, texto):
    """Caja de texto nativa de Windows (EDIT) en su propio hilo con su bucle de mensajes."""
    import ctypes
    from ctypes import wintypes
    u32, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    u32.CreateWindowExW.restype = ctypes.c_void_p
    u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    gdi.CreateFontW.restype = ctypes.c_void_p
    datos = {}
    listo = threading.Event()

    def hilo():
        h_ = u32.CreateWindowExW(0x8, "EDIT", texto, 0x80000000 | 0x10000000 | 0x00800000 | 0x80,
                                 int(x), int(y), int(w), int(h), None, None, None, None)
        fuente = gdi.CreateFontW(-24, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, "Arial")
        u32.SendMessageW(h_, 0x0030, fuente, 1)
        datos["hwnd"] = h_
        listo.set()
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))

    threading.Thread(target=hilo, daemon=True).start()
    listo.wait(5)
    return datos.get("hwnd")


def _texto_nativo(hwnd):
    import ctypes
    u32 = ctypes.windll.user32
    u32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    buf = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _cerrar_nativo(hwnd):
    import ctypes
    u32 = ctypes.windll.user32
    u32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    u32.PostMessageW(hwnd, 0x0010, None, None)


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
    import logging
    h = logging.FileHandler(os.path.join(salida, "registro.txt"), encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger("clw").addHandler(h)
    logging.getLogger("clw").setLevel(logging.INFO)
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
