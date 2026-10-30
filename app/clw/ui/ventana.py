"""La ventana de Windows (Tk). Muestra lo que dibuja la Interfaz y le pasa el mouse y el teclado.

Cuando NO LIMIT queda activo, la ventana se va volando junto al reloj (icono en la bandeja): asi no dibuja nada
ni estorba. Desde ese icono se vuelve a abrir, se detiene o se cierra. Mientras contesta no aparece nada en
pantalla: si algo falla, el icono del reloj lo marca y el detalle queda en la app.
"""

import ctypes
import logging
import os
import queue
import threading
import time
import webbrowser

import tkinter as tk
from PIL import Image, ImageTk

from .. import actualizar, entrada, rutas, version
from ..bandeja import Bandeja
from ..proveedores import validar_clave
from .estilo import ALTO
from .vistas import Interfaz

log = logging.getLogger("clw")

EVENTO_MOSTRAR = "CLWGANG_mostrar"   # si abren NO LIMIT otra vez, esa copia avisa por aqui y se cierra
T_IDA, T_VUELTA = 0.36, 0.32         # vuelo hacia el reloj y de regreso
AVISO_BANDEJA = ("Sigue activo junto al reloj (si no ves el icono, está en la flechita ^). "
                 "Ctrl + clic sobre cualquier pregunta.")
CADA_REVISION = 6 * 3600             # cada cuanto se busca una version nueva


def _ver(texto):
    return actualizar.numero(texto)


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


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _acelera(p):
    return p * p * p


def _frena(p):
    return 1 - (1 - p) ** 3


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
        self._chicas = {}                  # fotos chicas para repintar solo pedazos
        self._mostrada = None
        self._cursor = "arrow"
        self._cerrado = False
        self.visible = True                # False = escondida junto al reloj
        self._fundido = None               # vuelo / fundido en curso
        self._origen = None                # donde estaba la ventana antes de irse al reloj
        self._activo_bandeja = None
        self._alerta = None                # texto del ultimo problema mientras estaba escondida
        self._instalador = None            # actualizacion ya bajada
        self._actualizando = False
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
        self._revisar_version()

    # ---------------------------------------------------------------- ventana
    def hwnd(self):
        try:
            return entrada.U32.GetAncestor(self.root.winfo_id(), 2)
        except Exception:
            return None

    def _crear_bandeja(self):
        try:
            imagenes, icos = {}, {}
            for nombre, archivo in (("activo", "bandeja"), ("apagado", "bandeja_apagado"), ("alerta", "bandeja_alerta")):
                imagenes[nombre] = Image.open(rutas.asset(archivo + ".png")).convert("RGBA")
                icos[nombre] = rutas.asset(archivo + ".ico")
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

    def _posicion(self):
        try:
            g = self.root.geometry()            # "380x600+120+80"
            partes = g.replace("-", "+-").split("+")
            return int(partes[-2]), int(partes[-1])
        except Exception:
            return None

    def _mover_a(self, x, y):
        try:
            self.root.geometry(f"+{int(x)}+{int(y)}")
        except tk.TclError:
            pass

    def _junto_al_reloj(self):
        """Hacia donde vuela la ventana: la esquina de la barra de tareas donde esta el reloj."""
        W = self.root.winfo_width() or self.ui.ancho_px
        H = self.root.winfo_height() or self.ui.alto_px
        try:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            r = _RECT()
            if not ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
                raise OSError
            if r.top > 0:                       # barra arriba
                return r.right - W // 2 - 90, r.top - H * 2 // 3
            if r.right < sw:                    # barra a la derecha
                return r.right - W // 3, r.bottom - H // 2 - 40
            if r.left > 0:                      # barra a la izquierda
                return r.left - W * 2 // 3, r.bottom - H // 2 - 40
            return r.right - W // 2 - 90, r.bottom - H // 3
        except Exception:
            try:
                return self.root.winfo_screenwidth() - W // 2 - 90, self.root.winfo_screenheight() - H // 3
            except tk.TclError:
                return None

    # ---------------------------------------------------------------- mostrar / esconder
    def esconder(self):
        """Se va volando junto al reloj (si no hay icono en la bandeja, solo se minimiza)."""
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
        self._origen = self._posicion()
        self._fundido = {"t0": time.time(), "dur": T_IDA, "a0": 1.0, "a1": 0.0, "de": self._origen,
                         "a": self._junto_al_reloj(), "curva": _acelera, "fin": self._retirar}
        if not self.config.get("aviso_bandeja"):
            self.config["aviso_bandeja"] = True
            self.bandeja.avisar(AVISO_BANDEJA)
        log.info("ventana escondida junto al reloj")

    def _retirar(self):
        try:
            self.root.withdraw()
        except tk.TclError:
            pass
        if self._origen:
            self._mover_a(*self._origen)
        self._alfa(1.0)

    def mostrar(self):
        if self._cerrado:
            return
        self._fundido = None
        if self._estado_tk() != "normal":
            destino = self._origen or self._posicion()
            salida = self._junto_al_reloj() if (self._origen and self.en_bandeja()) else None
            self._alfa(0.0)
            if salida:
                self._mover_a(*salida)
            try:
                self.root.deiconify()
            except tk.TclError:
                return
            self._fundido = {"t0": time.time(), "dur": T_VUELTA, "a0": 0.0, "a1": 1.0, "de": salida,
                             "a": destino if salida else None, "curva": _frena, "fin": None}
        else:
            self._alfa(1.0)
        self.visible = True
        self.ui.visible = True
        self._poner_alerta(None)
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
        f = self._fundido
        if not f:
            return None
        p = min(1.0, (ahora - f["t0"]) / f["dur"])
        k = f["curva"](p)
        self._alfa(f["a0"] + (f["a1"] - f["a0"]) * k)
        if f["de"] and f["a"]:
            self._mover_a(f["de"][0] + (f["a"][0] - f["de"][0]) * k, f["de"][1] + (f["a"][1] - f["de"][1]) * k)
        if p >= 1:
            self._fundido = None
            if f["fin"]:
                f["fin"]()
            return None
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
        if self._instalador and not self._actualizando:
            # la version nueva ya estaba bajada: se instala callada al cerrar (la proxima vez abre actualizada)
            self._actualizando = actualizar.instalar(self._instalador, relanzar=False)
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

    def _poner_alerta(self, texto):
        if texto == self._alerta:
            return
        self._alerta = texto
        if self.bandeja is not None:
            self.bandeja.estado(bool(self.bot.activo), alerta=texto)

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
        pedazos = self.ui.sucio
        if (self.foto is None or self._mostrada is None or pedazos is None
                or self.foto.width() != img.width or self.foto.height() != img.height
                or sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in pedazos) > img.width * img.height * .55):
            self._pintar_todo(img)
        else:
            try:
                for caja in pedazos:
                    self._pintar_pedazo(img, caja)
            except (tk.TclError, ValueError):
                self._pintar_todo(img)
        self._mostrada = img

    def _pintar_todo(self, img):
        if self.foto is None or self.foto.width() != img.width or self.foto.height() != img.height:
            self.foto = ImageTk.PhotoImage(img)
            self.lbl.configure(image=self.foto)
        else:
            self.foto.paste(img)

    def _pintar_pedazo(self, img, caja):
        """Solo copia un rectangulo a la ventana (mucho mas rapido que la imagen entera)."""
        x0, y0, x1, y1 = caja
        trozo = img.crop(caja)
        llave = (x1 - x0, y1 - y0)
        chica = self._chicas.get(llave)
        if chica is None:
            if len(self._chicas) > 24:
                self._chicas.clear()
            chica = self._chicas[llave] = ImageTk.PhotoImage(trozo)
        else:
            chica.paste(trozo)
        self.root.tk.call(str(self.foto), "copy", str(chica), "-to", x0, y0, "-compositingrule", "set")

    def _evento_aparte(self, ev):
        """Escondida no aparece nada: los problemas solo marcan el icono del reloj."""
        if self.visible:
            return
        if ev[0] == "falta_clave":
            self._poner_alerta("Revisa tu clave")
        elif ev[0] == "actividad" and len(ev) > 2:
            if ev[2] == "error":
                self._poner_alerta(ev[1])
            elif ev[2] == "ok":
                self._poner_alerta(None)

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
            self.bandeja.estado(self._activo_bandeja, alerta=self._alerta)
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
        # en otro hilo: abrir el navegador puede tardar y no debe trabar la ventana
        threading.Thread(target=lambda: _sin_error(webbrowser.open, url), name="url", daemon=True).start()

    def abrir_carpeta(self):
        carpeta = os.path.join(rutas.carpeta_datos(), "revision")
        os.makedirs(carpeta, exist_ok=True)
        threading.Thread(target=lambda: _sin_error(os.startfile, carpeta), name="carpeta", daemon=True).start()

    def actualizar(self):
        """Instala la version nueva ya bajada y vuelve a abrir NO LIMIT (tarda unos segundos)."""
        if not self._instalador:
            self.abrir_url(version.PAGINA)
            return
        if actualizar.instalar(self._instalador, relanzar=True):
            self._actualizando = True
            self.salir()

    # ---------------------------------------------------------------- version nueva
    def _revisar_version(self):
        if self._cerrado or self._instalador:
            return
        threading.Thread(target=self._buscar_actualizacion, name="version", daemon=True).start()
        self.root.after(CADA_REVISION * 1000, self._revisar_version)

    def _buscar_actualizacion(self):
        eventos = self.bot.eventos
        try:
            info = actualizar.buscar()
        except Exception:
            return
        if not info:
            return
        v, url, tam = info
        eventos.put(("nueva_version", v))
        if not url:
            return
        try:
            ruta = actualizar.descargar(v, url, tam, al_avance=lambda p: eventos.put(("descarga", p)),
                                        cancelar=lambda: self._cerrado)
        except Exception as ex:
            log.warning("no se pudo bajar la actualizacion: %s", ex)
            eventos.put(("actualizacion_error", str(ex)))
            return
        if ruta:
            self._instalador = ruta
            eventos.put(("actualizacion_lista", v))
        else:
            eventos.put(("actualizacion_error", "incompleta"))


def _sin_error(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass
