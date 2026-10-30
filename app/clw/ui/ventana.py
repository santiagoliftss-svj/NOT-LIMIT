"""La ventana de Windows (Tk). Muestra lo que dibuja la Interfaz y le pasa el mouse y el teclado.

Cuando NO LIMIT queda activo, la ventana se esconde junto al reloj (icono en la bandeja): asi no dibuja nada
ni estorba mientras juegas. Desde ese icono se vuelve a abrir, se detiene o se cierra.
"""

import ctypes
import json
import logging
import os
import queue
import threading
import time
import urllib.request
import webbrowser

import tkinter as tk
from PIL import Image, ImageTk

from .. import entrada, rutas, version
from ..bandeja import Bandeja
from ..proveedores import validar_clave
from .estilo import ALTO
from .vistas import Interfaz

log = logging.getLogger("clw")

EVENTO_MOSTRAR = "CLWGANG_mostrar"   # si abren NO LIMIT otra vez, esa copia avisa por aqui y se cierra
T_FUNDIDO = 0.16
AVISO_BANDEJA = ("Sigue activo junto al reloj (si no ves el icono, está en la flechita ^). "
                 "Ctrl + clic sobre cualquier pregunta.")


def _ver(texto):
    partes = []
    for p in texto.strip().lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        partes.append(int(num) if num else 0)
    return tuple(partes + [0] * (3 - len(partes)))


def _crear_evento():
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateEventW.restype = ctypes.c_void_p
        return k32.CreateEventW(None, False, False, EVENTO_MOSTRAR)
    except Exception:
        return None


def _hay_aviso(evento):
    if not evento:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(evento), 0) == 0
    except Exception:
        return False


class Ventana:
    def __init__(self, config, bot, escala=1.0, raiz=None, con_bandeja=True):
        self.config = config
        self.bot = bot
        self.root = raiz or tk.Tk(className="NO LIMIT")
        self.root.withdraw()
        self.root.title("NO LIMIT")
        self.root.configure(bg="#000000")
        self.root.resizable(False, False)
        self.root.report_callback_exception = self._error_tk
        try:
            self.root.iconbitmap(default=rutas.asset("icono.ico"))
        except Exception:
            pass

        # que quepa en pantallas chicas con zoom grande
        alto_pantalla = self.root.winfo_screenheight()
        escala = max(0.8, min(escala, (alto_pantalla - 110) / ALTO))
        self.e = escala
        self.ui = Interfaz(config, self, escala)
        W, H = self.ui.ancho_px, self.ui.alto_px
        x = max(0, (self.root.winfo_screenwidth() - W) // 2)
        y = max(0, (alto_pantalla - H) // 2 - 30)
        self.root.geometry(f"{W}x{H}+{x}+{y}")

        self.lbl = tk.Label(self.root, bd=0, highlightthickness=0, bg="#000000", cursor="arrow")
        self.lbl.place(x=0, y=0, width=W, height=H)
        self.lbl.bind("<Motion>", lambda e: self._raton(self.ui.mover(e.x / self.e, e.y / self.e)))
        self.lbl.bind("<Leave>", lambda e: self._raton(self.ui.salir()))
        self.lbl.bind("<ButtonPress-1>", lambda e: self._raton(self.ui.presionar(e.x / self.e, e.y / self.e)))
        self.lbl.bind("<ButtonRelease-1>", lambda e: self._raton(self.ui.soltar(e.x / self.e, e.y / self.e)))
        self.root.bind("<Key>", self._tecla)
        self.root.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        self.cola = queue.Queue()          # funciones que deben correr en el hilo de la ventana
        self.foto = None
        self._mostrada = None
        self._cursor = "arrow"
        self._cerrado = False
        self.visible = True                # False = escondida junto al reloj
        self._avisado = False              # ya se dijo una vez que sigue activo junto al reloj
        self._fundido = None               # (desde, hasta, t0, al_terminar)
        self._activo_bandeja = None
        self._evento = _crear_evento()
        self.bandeja = self._crear_bandeja() if con_bandeja else None

        self.root.update_idletasks()
        self._barra_oscura()
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass
        self._hwnd = self.hwnd()
        self.bot.hwnd_propio = self._hwnd
        self._pintar()
        self.root.after(30, self._tick)
        threading.Thread(target=self._buscar_actualizacion, name="version", daemon=True).start()

    # ---------------------------------------------------------------- ventana
    def hwnd(self):
        try:
            return entrada.U32.GetAncestor(self.root.winfo_id(), 2)
        except Exception:
            return None

    def _crear_bandeja(self):
        try:
            imagenes = {"activo": Image.open(rutas.asset("bandeja.png")).convert("RGBA"),
                        "apagado": Image.open(rutas.asset("bandeja_apagado.png")).convert("RGBA")}
            icos = {"activo": rutas.asset("bandeja.ico"), "apagado": rutas.asset("bandeja_apagado.ico")}
            b = Bandeja(imagenes,
                        al_abrir=lambda: self.cola.put(self.mostrar),
                        al_alternar=lambda: self.cola.put(self._alternar),
                        al_salir=lambda: self.cola.put(self.salir),
                        esta_activo=lambda: bool(self.bot.activo),
                        icos=icos)
            return b if b.icono is not None else None
        except Exception as ex:
            log.warning("sin icono junto al reloj: %s", ex)
            return None

    def en_bandeja(self):
        return self.bandeja is not None and self.bandeja.disponible

    def _barra_oscura(self):
        """Barra de titulo negra (Windows 10/11)."""
        try:
            h = ctypes.c_void_p(self.hwnd())
            dwm = ctypes.windll.dwmapi
            uno = ctypes.c_int(1)
            for atributo in (20, 19):  # modo oscuro
                if dwm.DwmSetWindowAttribute(h, atributo, ctypes.byref(uno), 4) == 0:
                    break
            for atributo, valor in ((35, 0x000000), (36, 0xFFFFFF), (34, 0x262626)):  # titulo, texto, borde
                v = ctypes.c_int(valor)
                dwm.DwmSetWindowAttribute(h, atributo, ctypes.byref(v), 4)
        except Exception:
            pass

    def _error_tk(self, tipo, valor, tb):
        import traceback
        log.error("error en la ventana: %s", "".join(traceback.format_exception(tipo, valor, tb)))

    def _estado_tk(self):
        try:
            return self.root.state()
        except tk.TclError:
            return "withdrawn"

    def _enfocada(self):
        h = entrada.ventana_al_frente()
        return h is None or h == self._hwnd if entrada.U32 is not None else True

    def _alfa(self, a):
        try:
            self.root.attributes("-alpha", max(0.0, min(1.0, a)))
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- mostrar / esconder
    def esconder(self):
        """Se va junto al reloj (si no hay icono en la bandeja, solo se minimiza)."""
        if self._cerrado or not self.visible:
            return
        self.visible = False
        self.ui.visible = False
        self.ui.salir()
        if not self.en_bandeja():
            try:
                self.root.iconify()
            except tk.TclError:
                pass
            return
        self._fundido = (1.0, 0.0, time.time(), self._retirar)
        if not self._avisado:
            self._avisado = True
            self.bandeja.avisar(AVISO_BANDEJA)
        log.info("ventana escondida junto al reloj")

    def _retirar(self):
        try:
            self.root.withdraw()
        except tk.TclError:
            pass
        self._alfa(1.0)

    def mostrar(self):
        if self._cerrado:
            return
        self._fundido = None
        if self._estado_tk() != "normal":
            self._alfa(0.0)
            try:
                self.root.deiconify()
            except tk.TclError:
                return
            self._fundido = (0.0, 1.0, time.time(), None)
        else:
            self._alfa(1.0)
        self.visible = True
        self.ui.visible = True
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(300, self._sin_encima)
            self.root.focus_force()
        except tk.TclError:
            pass
        self._mostrada = None
        self._pintar()

    def _sin_encima(self):
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _fundir(self, ahora):
        if not self._fundido:
            return None
        desde, hasta, t0, al_terminar = self._fundido
        p = (ahora - t0) / T_FUNDIDO
        if p >= 1:
            self._fundido = None
            self._alfa(hasta)
            if al_terminar:
                al_terminar()
            return None
        k = 1 - (1 - p) ** 3
        self._alfa(desde + (hasta - desde) * k)
        return 16

    def _al_cerrar(self):
        """La X: si esta activo se queda trabajando junto al reloj; si no, se cierra."""
        if self.bot.activo and self.en_bandeja():
            self.esconder()
        else:
            self.salir()

    def salir(self):
        if self._cerrado:
            return
        self._cerrado = True
        try:
            self.bot.detener()
        except Exception:
            pass
        if self.bandeja is not None:
            self.bandeja.cerrar()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    cerrar = salir

    def _alternar(self):
        """Activar / Detener desde el icono del reloj."""
        if not self.bot.activo and not self.bot.puede_iniciar():
            self.mostrar()          # falta la clave: hay que pedirla en la ventana
        self.ui.inyectar()

    # ---------------------------------------------------------------- dibujo y eventos
    def _raton(self, cambio):
        if self.ui.cursor != self._cursor:
            self._cursor = self.ui.cursor
            try:
                self.lbl.configure(cursor=self._cursor)
            except tk.TclError:
                pass
        if cambio:
            self._pintar()

    def _tecla(self, e):
        ctrl = bool(e.state & 0x0004)
        if self.ui.tecla(e.char or "", e.keysym or "", ctrl):
            self._pintar()

    def _pintar(self):
        if not self.visible or self._cerrado:
            return
        img = self.ui.render()
        if img is self._mostrada:
            return
        if self.foto is None or self.foto.width() != img.width or self.foto.height() != img.height:
            self.foto = ImageTk.PhotoImage(img)
            self.lbl.configure(image=self.foto)
        else:
            self.foto.paste(img)
        self._mostrada = img

    def _evento_aparte(self, ev):
        """Lo que hace falta ademas de la interfaz: abrir la ventana o avisar junto al reloj."""
        if ev[0] == "falta_clave":
            self.mostrar()
        elif ev[0] == "actividad" and not self.visible and len(ev) > 2 and ev[2] in ("error", "info"):
            if self.en_bandeja():
                self.bandeja.avisar(ev[1])

    def _tick(self):
        if self._cerrado:
            return
        ahora = time.time()
        try:
            while True:
                ev = self.bot.eventos.get_nowait()
                self.ui.evento_bot(ev)
                self._evento_aparte(ev)
        except queue.Empty:
            pass
        try:
            while True:
                self.cola.get_nowait()()
        except queue.Empty:
            pass
        except Exception as ex:
            log.error("cola: %s", ex)
        if self._cerrado:
            return
        if _hay_aviso(self._evento):
            self.mostrar()
        if self.bandeja is not None and bool(self.bot.activo) != self._activo_bandeja:
            self._activo_bandeja = bool(self.bot.activo)
            self.bandeja.estado(self._activo_bandeja)
        if self.ui.debe_esconder(ahora):
            self.esconder()

        espera = self._fundir(ahora)
        en_pantalla = self.visible and self._estado_tk() == "normal"
        self.ui.visible = en_pantalla
        if en_pantalla:
            self.ui.enfocado = self._enfocada()
            self._pintar()
            if espera is None:
                espera = self.ui.ritmo(ahora) or 150
        elif espera is None:
            espera = 250                    # escondida: no dibuja nada, solo revisa avisos
        self.root.after(espera, self._tick)

    # ---------------------------------------------------------------- acciones que pide la interfaz
    def iniciar(self):
        self.bot.iniciar()

    def detener(self):
        self.bot.detener()

    def verificar_clave(self, prov, texto):
        def trabajo():
            error = validar_clave(prov, texto)
            self.cola.put(lambda: self.ui.clave_verificada(prov, texto, error))
        threading.Thread(target=trabajo, name="clave", daemon=True).start()

    def leer_portapapeles(self):
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return ""

    def abrir_url(self, url):
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def abrir_carpeta(self):
        carpeta = os.path.join(rutas.carpeta_datos(), "revision")
        os.makedirs(carpeta, exist_ok=True)
        try:
            os.startfile(carpeta)
        except Exception:
            pass

    def _buscar_actualizacion(self):
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{version.REPO}/releases/latest",
                                         headers={"accept": "application/vnd.github+json", "user-agent": "clw-gang"})
            with urllib.request.urlopen(req, timeout=8) as r:
                tag = json.load(r).get("tag_name", "")
            if tag and _ver(tag) > _ver(version.VERSION):
                self.bot.eventos.put(("nueva_version", tag.lstrip("vV")))
        except Exception:
            pass
