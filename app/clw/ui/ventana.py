"""La ventana de Windows (Tk). Solo muestra lo que dibuja la Interfaz y le pasa el mouse y el teclado."""

import ctypes
import json
import logging
import os
import queue
import threading
import urllib.request
import webbrowser

import tkinter as tk
from PIL import ImageTk

from .. import entrada, rutas, version
from ..proveedores import validar_clave
from .estilo import ALTO
from .vistas import Interfaz

log = logging.getLogger("clw")


def _ver(texto):
    partes = []
    for p in texto.strip().lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        partes.append(int(num) if num else 0)
    return tuple(partes + [0] * (3 - len(partes)))


class Ventana:
    def __init__(self, config, bot, escala=1.0, raiz=None):
        self.config = config
        self.bot = bot
        self.root = raiz or tk.Tk(className="CLW GANG")
        self.root.withdraw()
        self.root.title("CLW GANG")
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
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

        self.cola = queue.Queue()          # funciones que deben correr en el hilo de la ventana
        self.foto = None
        self._mostrada = None
        self._cursor = "arrow"
        self._cerrado = False

        self.root.update_idletasks()
        self._barra_oscura()
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass
        self.bot.hwnd_propio = self.hwnd()
        self._pintar()
        self.root.after(30, self._tick)
        threading.Thread(target=self._buscar_actualizacion, name="version", daemon=True).start()

    # ---------------------------------------------------------------- ventana
    def hwnd(self):
        try:
            return entrada.U32.GetAncestor(self.root.winfo_id(), 2)
        except Exception:
            return None

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
        img = self.ui.render()
        if img is self._mostrada:
            return
        if self.foto is None or self.foto.width() != img.width or self.foto.height() != img.height:
            self.foto = ImageTk.PhotoImage(img)
            self.lbl.configure(image=self.foto)
        else:
            self.foto.paste(img)
        self._mostrada = img

    def _tick(self):
        if self._cerrado:
            return
        try:
            while True:
                self.ui.evento_bot(self.bot.eventos.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                self.cola.get_nowait()()
        except queue.Empty:
            pass
        except Exception as ex:
            log.error("cola: %s", ex)
        self._pintar()
        self.root.after(50 if self.ui.animando() else 120, self._tick)

    def cerrar(self):
        self._cerrado = True
        try:
            self.bot.detener()
        except Exception:
            pass
        self.root.destroy()

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
