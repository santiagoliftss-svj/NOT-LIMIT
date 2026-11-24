"""La ventana de Windows (Tk). Muestra lo que dibuja la Interfaz y le pasa el mouse y el teclado.

Cuando NO LIMIT queda activo, la ventana se esconde sin rastro: ni icono junto al reloj ni animacion
(LockDown Browser vigila la bandeja). La respuesta se ve en el panelcito flotante, que no roba el foco
ni sale en capturas. Para volver a abrir la ventana se le da doble clic a NO LIMIT como al principio.

Desde que se toca INYECTAR (como NoLock) la ventana pasa desapercibida: solo se ve en el monitor, pero no
sale en capturas de pantalla, grabaciones ni al compartir pantalla (ver _excluir_de_capturas).
"""

import ctypes
import logging
import os
import queue
import sys
import threading
import time
import webbrowser

from PIL import Image

try:
    import tkinter as tk
    from PIL import ImageTk
    TclError = tk.TclError
except ImportError:                      # (en Mac la ventana es de AppKit: clw.mac.ventana)
    tk = ImageTk = None

    class TclError(Exception):
        pass

from .. import actualizar, entrada, licencia, plataforma, rutas, version
from ..bandeja import Bandeja
from ..proveedores import validar_clave
from .estilo import ALTO
from .vistas import Interfaz

log = logging.getLogger("clw")

EVENTO_MOSTRAR = "CLWGANG_mostrar"   # si abren NO LIMIT otra vez, esa copia avisa por aqui y se cierra
T_IDA, T_VUELTA = 0.36, 0.32         # vuelo hacia el reloj y de regreso
AVISO_BANDEJA = ("Sigue activo junto al reloj (si no ves el icono, está en la flechita ^). "
                 "Mantén presionado el clic 1 segundo sobre cualquier pregunta.")
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
        self.root = raiz or tk.Tk(className="RtkAudio")
        self.root.withdraw()
        self.root.title("Realtek Audio")
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
        self._panel = None                 # panelcito flotante con la respuesta (se crea al usarse)
        self._instalador = None            # actualizacion ya bajada
        self._actualizando = False
        self._calentando = True            # armar Ajustes y la clave en ratos libres (el primer clic no espera)
        self._calentar_desde = time.time() + 1.0
        self._evento = _crear_evento()
        self.bandeja = None                  # sin icono junto al reloj: ni icono ni animacion que delaten
                                            # (LockDown Browser vigila la bandeja); se controla desde el panel

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
        self._excluir_de_capturas()
        self._pintar()
        self.root.after(30, self._tick)
        self.root.after(20000, self._recoger_basura)
        def al_terminar():                 # con la IA incluida: cuantas preguntas le quedan (y registra la compu)
            codigo = self.config.get("licencia")
            if codigo and licencia.servidor() and licencia.estado(self.config).activa:
                ok, datos = licencia.consultar_servidor(codigo)
                if ok and datos.get("restantes") is not None:
                    self.cola.put(lambda: self.ui.evento_bot(("uso", datos["restantes"])))
        licencia.refrescar_en_fondo(al_terminar)
        self.root.after(licencia.REVISAR_CADA * 1000, self._revisar_licencia)
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

    def _excluir_de_capturas(self):
        """Como NoLock al inyectar: la ventana de NO LIMIT pasa desapercibida. Solo se ve en el monitor:
        no sale en capturas de pantalla (PrtScr / Win+Shift+S), ni en grabaciones, ni cuando alguien comparte
        pantalla o graba el examen (Zoom, Teams, Meet, Respondus, Honorlock, Proctorio...). En Windows viejo
        (sin WDA_EXCLUDEFROMCAPTURE) no pasa nada: sigue saliendo como siempre."""
        if entrada.U32 is None or not self._hwnd:
            return
        try:
            entrada.U32.SetWindowDisplayAffinity(ctypes.c_void_p(self._hwnd), 0x11)  # WDA_EXCLUDEFROMCAPTURE
        except Exception:
            pass

    def _es_toolwindow(self, si):
        """Fantasma mientras esta activa: la ventana ni en la barra de tareas ni en Alt+Tab (WS_EX_TOOLWINDOW).
        Solo se ve en el monitor (y con _excluir_de_capturas, ni en capturas ni grabaciones)."""
        if entrada.U32 is None or not self._hwnd:
            return
        try:
            h = ctypes.c_void_p(self._hwnd)
            entrada.U32.GetWindowLongW.restype = ctypes.c_long
            estilo = entrada.U32.GetWindowLongW(h, -20) & 0xFFFFFFFF       # GWL_EXSTYLE
            nuevo = (estilo | 0x80) if si else (estilo & ~0x80)            # WS_EX_TOOLWINDOW
            entrada.U32.SetWindowLongW(h, -20, ctypes.c_long(nuevo))
        except Exception:
            pass

    def _error_tk(self, tipo, valor, tb):
        import traceback
        log.error("error en la ventana: %s", "".join(traceback.format_exception(tipo, valor, tb)))

    def _estado_tk(self):
        try:
            return self.root.state()
        except TclError:
            return "withdrawn"

    def _enfocada(self):
        h = entrada.ventana_al_frente()
        return h is None or h == self._hwnd if entrada.U32 is not None else True

    def _alfa(self, a):
        try:
            self.root.attributes("-alpha", max(0.0, min(1.0, a)))
        except TclError:
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
        except TclError:
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
            except TclError:
                return None

    # ---------------------------------------------------------------- mostrar / esconder
    def esconder(self):
        """Se esconde sin dejar rastro: nada de volar junto al reloj ni icono en la bandeja (LockDown
        Browser vigila esas cosas). La respuesta se ve en el panelcito flotante."""
        if self._cerrado or not self.visible:
            return
        self.visible = False
        self.ui.visible = False
        self.ui.salir()
        self._fundido = None
        self._alfa(1.0)
        try:
            self.root.withdraw()
        except TclError:
            pass
        log.info("ventana escondida")

    def _retirar(self):
        try:
            self.root.withdraw()
        except TclError:
            pass
        if self._origen:
            self._mover_a(*self._origen)
        self._alfa(1.0)

    def mostrar(self):
        if self._cerrado:
            return
        self._fundido = None
        if self._estado_tk() != "normal":
            self._alfa(1.0)
            try:
                self.root.deiconify()
                self._excluir_de_capturas()      # al volver sigue desapercibida
            except TclError:
                return
        else:
            self._alfa(1.0)
        self.visible = True
        self.ui.visible = True
        if self._panel is not None:
            self._panel.esconder()          # la ventana abierta ya enseña todo
        self._poner_alerta(None)
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(300, self._sin_encima)
            self.root.focus_force()
        except TclError:
            pass
        self._mostrada = None
        self._pintar()

    def _sin_encima(self):
        try:
            self.root.attributes("-topmost", False)
        except TclError:
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
        """La X: si esta activo se queda trabajando escondida (se ve en el panel); si no, se cierra."""
        if self.bot.activo:
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
        if self._panel is not None:
            self._panel.cerrar()
        try:
            self.root.destroy()
        except TclError:
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
            except TclError:
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
            except (TclError, ValueError):
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
        """Escondida no aparece nada en pantalla... salvo el panelcito flotante con la respuesta."""
        if self.visible:
            return
        if ev[0] == "estado":
            if ev[1] == "activo":
                self._panel_evento("Activo. Mantén presionado el clic 1 s sobre la pregunta. "
                                   "Toca aquí para cambiar de modo.")
            elif ev[1] == "apagado" and self._panel is not None:
                self._panel.esconder()
        elif ev[0] == "falta_clave":
            self._poner_alerta("Revisa tu clave")
        elif ev[0] == "actividad" and len(ev) > 2:
            if self.bot.activo:
                self._panel_evento(ev[1])
            if ev[2] == "error":
                self._poner_alerta(ev[1])
            elif ev[2] == "ok":
                self._poner_alerta(None)

    def _panel_evento(self, texto):
        """La respuesta (o lo que pasa) en el panelcito flotante junto a la bandeja: no roba el foco ni
        sale en capturas, asi el examen nunca registra que saliste de el."""
        if not self.bot.activo:
            return
        if self._panel is None:
            self._panel = Panel(self.root, al_tocar=lambda: self.bot.alternar_modo(),
                                al_ocultar=lambda: self._panel.esconder())
        self._panel.mostrar(texto)
        if texto.startswith("Modo:"):
            # el aviso del modo no se queda fijo en pantalla: a los 4 segundos se quita solo
            self.root.after(4000, lambda: self._panel and self._panel.esconder())

    def _recoger_basura(self):
        """La basura con cosas de Tk (imagenes, variables) se recoge aqui, en el hilo de Tk. Si la recogiera el hilo
        que contesta (que crea muchos objetos al leer la pantalla), Tcl tronaria y la app se cerraria."""
        if self._cerrado:
            return
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        self.root.after(20000, self._recoger_basura)

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
            if self._calentando and ahora >= self._calentar_desde and espera != 16:
                self._calentando = self.ui.precalentar()
        elif espera is None:
            espera = 250                    # escondida: no dibuja nada, solo revisa avisos
        self.root.after(espera, self._tick)

    # ---------------------------------------------------------------- acciones que pide la interfaz
    def iniciar(self):
        if (plataforma.WINDOWS and getattr(sys, "frozen", False) and not entrada.es_administrador()
                and "--autoprueba" not in sys.argv):
            # como NoLock: al inyectar, Windows pregunta si dejar que NO LIMIT sea administrador (la pantalla
            # de '¿Quiere permitir que esta aplicacion haga cambios?'). Con eso puede contestar hasta dentro
            # de LockDown Browser, que corre como administrador y si no, no acepta los clics.
            if entrada.relanzar_como_administrador(("--inyectada",)):
                self.salir()             # esta copia se cierra: sigue la de administrador, ya inyectandose
                return
        self._excluir_de_capturas()      # al darle INYECTAR ya pasa desapercibida (como NoLock)
        self._es_toolwindow(True)        # y fantasma: ni barra de tareas ni Alt+Tab mientras esta activa
        self.bot.iniciar()

    def detener(self):
        self._es_toolwindow(False)       # al detener vuelve a ser una ventana normal
        self.bot.detener()

    def verificar_clave(self, prov, texto):
        def trabajo():
            error = validar_clave(prov, texto)
            self.cola.put(lambda: self.ui.clave_verificada(prov, texto, error))
        threading.Thread(target=trabajo, name="clave", daemon=True).start()

    def verificar_licencia(self, texto):
        """Revisa en la pagina si el codigo esta pagado (en otro hilo) y avisa a la interfaz."""
        def trabajo():
            try:
                licencia.refrescar()
            except Exception as ex:
                log.info("no se pudo revisar la lista de licencias: %s", ex)
            est = licencia.estado_codigo(texto)
            if est.activa and licencia.servidor():
                ok, datos = licencia.consultar_servidor(texto)     # (registra esta compu)
                if not ok:
                    est = licencia.Estado(False, "servidor", est.numero, est.vence, est.plan)
                    est.propio = datos
                elif datos.get("restantes") is not None:
                    self.cola.put(lambda: self.ui.evento_bot(("uso", datos["restantes"])))
            self.cola.put(lambda: self.ui.licencia_verificada(texto, est))
        threading.Thread(target=trabajo, name="licencia", daemon=True).start()

    def _revisar_licencia(self):
        if self._cerrado:
            return
        def al_terminar():                 # con la IA incluida: cuantas preguntas le quedan (y registra la compu)
            codigo = self.config.get("licencia")
            if codigo and licencia.servidor() and licencia.estado(self.config).activa:
                ok, datos = licencia.consultar_servidor(codigo)
                if ok and datos.get("restantes") is not None:
                    self.cola.put(lambda: self.ui.evento_bot(("uso", datos["restantes"])))
        licencia.refrescar_en_fondo(al_terminar)
        self.root.after(licencia.REVISAR_CADA * 1000, self._revisar_licencia)

    def leer_portapapeles(self):
        try:
            return self.root.clipboard_get()
        except TclError:
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


class Panel:
    """Panelcito flotante con la respuesta (como NoLock). No roba el foco (WS_EX_NOACTIVATE: aunque se le
    de clic, el navegador del examen sigue siendo la ventana activa y no registra que saliste de la prueba) y
    no sale en capturas, grabaciones ni pantalla compartida (WDA_EXCLUDEFROMCAPTURE). Tocarlo cambia entre
    'mostrar la respuesta' y 'contestar solo'."""

    def __init__(self, raiz, al_tocar, al_ocultar=None):
        self.top = tk.Toplevel(raiz)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg="#0A0A0A")
        self.lbl = tk.Label(self.top, text="", bg="#0A0A0A", fg="#FFFFFF", wraplength=280,
                           justify="left", padx=14, pady=9, font=("Segoe UI", 10))
        self.lbl.pack()
        self.lbl.bind("<ButtonRelease-1>", lambda e: al_tocar())
        self.lbl.bind("<Button-3>", lambda e: al_ocultar and al_ocultar())     # clic derecho: se quita
        self.top.withdraw()
        self.visible = False

    def _esquinas(self):
        try:
            r = _RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
                return r.right, r.bottom
        except Exception:
            pass
        return self.top.winfo_screenwidth(), self.top.winfo_screenheight()

    def _estilos(self):
        """Invisible en capturas y sin robar el foco nunca."""
        if entrada.U32 is None:
            return
        try:
            hwnd = entrada.U32.GetAncestor(self.top.winfo_id(), 2)
            entrada.U32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), 0x11)             # WDA_EXCLUDEFROMCAPTURE
            entrada.U32.GetWindowLongW.restype = ctypes.c_long
            estilo = entrada.U32.GetWindowLongW(ctypes.c_void_p(hwnd), -20) & 0xFFFFFFFF  # GWL_EXSTYLE
            entrada.U32.SetWindowLongW(ctypes.c_void_p(hwnd), -20,
                                       ctypes.c_long(estilo | 0x08000000 | 0x80))       # NOACTIVATE | TOOLWINDOW
        except Exception:
            pass

    def mostrar(self, texto):
        try:
            self.lbl.configure(text=texto)
            self.top.update_idletasks()
            derecha, abajo = self._esquinas()
            w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
            self.top.geometry(f"+{max(0, derecha - w - 14)}+{max(0, abajo - h - 14)}")
            if not self.visible:
                self.top.deiconify()
                self.visible = True
                self._estilos()
        except TclError:
            pass

    def esconder(self):
        if self.visible:
            try:
                self.top.withdraw()
            except TclError:
                pass
            self.visible = False

    def cerrar(self):
        try:
            self.top.destroy()
        except TclError:
            pass
        self.visible = False
