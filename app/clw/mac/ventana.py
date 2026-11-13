"""La ventana de Mac (AppKit nativo): se ve nitida en Retina y vive en la barra de arriba.

La logica es la misma que la de Windows (clw.ui.ventana.Ventana): irse volando al icono al INYECTAR, no dibujar
nada escondida, alertas en el icono, abrir / activar / salir desde su menu. Aqui solo cambia como se hace cada
cosa en Mac: 'RaizMac' tiene lo poquito de Tk que usa esa logica, hecho con AppKit.
"""

import logging
import os
import queue
import re
import subprocess
import threading
import time

import objc
from AppKit import (NSAppearance, NSAppearanceNameDarkAqua, NSApplication, NSApplicationActivationPolicyAccessory,
                    NSApplicationActivationPolicyRegular, NSBackingStoreBuffered, NSColor, NSCompositingOperationCopy,
                    NSCursor, NSEvent, NSEventModifierFlagCommand, NSEventTypeApplicationDefined,
                    NSFloatingWindowLevel, NSImage, NSMenu, NSMenuItem, NSNormalWindowLevel, NSPasteboard,
                    NSPasteboardTypeString, NSRectFill, NSScreen, NSStatusBar, NSTerminateNow, NSTrackingActiveAlways,
                    NSTrackingArea, NSTrackingInVisibleRect, NSTrackingMouseEnteredAndExited, NSTrackingMouseMoved,
                    NSVariableStatusItemLength, NSView, NSWindow, NSWindowCollectionBehaviorMoveToActiveSpace,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskTitled,
                    NSWindowTitleHidden)
from Foundation import (NSActivityLatencyCritical, NSActivityUserInitiatedAllowingIdleSystemSleep, NSData,
                        NSMakePoint, NSMakeRect, NSMakeSize, NSObject, NSProcessInfo, NSRunLoop, NSRunLoopCommonModes,
                        NSTimer, NSZeroRect)
import Quartz as Q

from .. import licencia, rutas, version
from ..ui.estilo import ALTO, ANCHO
from ..ui.ventana import Ventana
from ..ui.vistas import Interfaz
from . import actualizar_mac, permisos

log = logging.getLogger("clw")

_TECLAS = {53: "Escape", 51: "BackSpace", 117: "Delete", 36: "Return", 76: "Return", 48: "Tab"}
_CURSORES = {"hand2": "pointingHandCursor", "xterm": "IBeamCursor"}
_ESPACIO = Q.CGColorSpaceCreateDeviceRGB()


def _cgimagen(img):
    """PIL (RGBA, opaca) -> CGImage sin copiar dos veces."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    crudo = img.tobytes()
    datos = NSData.dataWithBytes_length_(crudo, len(crudo))
    proveedor = Q.CGDataProviderCreateWithCFData(datos)
    return Q.CGImageCreate(img.width, img.height, 8, 32, img.width * 4, _ESPACIO, Q.kCGImageAlphaNoneSkipLast,
                           proveedor, None, False, Q.kCGRenderingIntentDefault)


def _alto_principal():
    pantallas = NSScreen.screens()
    return pantallas[0].frame().size.height if pantallas else 900


# ---------------------------------------------------------------- piezas de AppKit

class _VistaNL(NSView):
    """Muestra el cuadro que dibuja la Interfaz y le pasa mouse y teclado."""

    def initWithFrame_(self, marco):
        self = objc.super(_VistaNL, self).initWithFrame_(marco)
        if self is None:
            return None
        self.dueno = None
        self.imagen = None
        self.area = None
        return self

    def isFlipped(self):
        return True                      # (0, 0) arriba a la izquierda, como la Interfaz

    def isOpaque(self):
        return True

    def acceptsFirstResponder(self):
        return True

    def acceptsFirstMouse_(self, evento):
        return True

    def drawRect_(self, rect):
        NSColor.blackColor().set()
        NSRectFill(rect)
        if self.imagen is not None:
            self.imagen.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                self.bounds(), NSZeroRect, NSCompositingOperationCopy, 1.0, True, None)

    def updateTrackingAreas(self):
        if self.area is not None:
            self.removeTrackingArea_(self.area)
        opciones = (NSTrackingMouseMoved | NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways |
                    NSTrackingInVisibleRect)
        self.area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(self.bounds(), opciones, self, None)
        self.addTrackingArea_(self.area)
        objc.super(_VistaNL, self).updateTrackingAreas()

    @objc.python_method
    def _punto(self, evento):
        p = self.convertPoint_fromView_(evento.locationInWindow(), None)
        return p.x, p.y

    def mouseMoved_(self, evento):
        self.dueno._mouse("mover", *self._punto(evento))

    def mouseDragged_(self, evento):
        self.dueno._mouse("mover", *self._punto(evento))

    def mouseExited_(self, evento):
        self.dueno._mouse("salir")

    def mouseDown_(self, evento):
        self.dueno._mouse("presionar", *self._punto(evento))

    def mouseUp_(self, evento):
        self.dueno._mouse("soltar", *self._punto(evento))

    def keyDown_(self, evento):
        if not self.dueno._tecla_mac(evento):
            objc.super(_VistaNL, self).keyDown_(evento)

    def paste_(self, remitente):
        self.dueno._pegar()


class _DelegadoNL(NSObject):
    """Recibe lo que manda macOS (cerrar, volver a abrir, salir) y los botones del menu del icono."""

    def init(self):
        self = objc.super(_DelegadoNL, self).init()
        if self is None:
            return None
        self.dueno = None
        return self

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visibles):
        if self.dueno is not None:       # abrieron NO LIMIT otra vez (Dock, Launchpad, Finder)
            self.dueno.cola.put(self.dueno.mostrar)
        return True

    def applicationShouldTerminate_(self, app):
        if self.dueno is not None and not self.dueno._cerrado:
            self.dueno.salir()
        return NSTerminateNow

    def windowShouldClose_(self, ventana):
        if self.dueno is not None:
            self.dueno._al_cerrar()
        return False

    def abrir_(self, remitente):
        self.dueno.cola.put(self.dueno.mostrar)

    def alternar_(self, remitente):
        self.dueno.cola.put(self.dueno._alternar)

    def salirApp_(self, remitente):
        self.dueno.cola.put(self.dueno.salir)


def _imagen_barra(ruta):
    im = NSImage.alloc().initWithContentsOfFile_(ruta)
    if im is None:
        return None
    rep = im.representations()
    if rep:
        im.setSize_(NSMakeSize(rep[0].pixelsWide() / 2, rep[0].pixelsHigh() / 2))   # archivos @2x
    im.setTemplate_(True)                # macOS la pinta blanca o negra segun la barra
    return im


class BandejaMac:
    """El icono de NO LIMIT en la barra de arriba, con su menu (Abrir / Activar o Detener / Salir)."""

    def __init__(self, delegado, archivos):
        self.imagenes = {k: _imagen_barra(r) for k, r in archivos.items()}
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        boton = self.item.button()
        if self.imagenes.get("apagado") is not None:
            boton.setImage_(self.imagenes["apagado"])
        else:
            boton.setTitle_("NL")
        boton.setToolTip_("NO LIMIT")
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        self.i_aviso = menu.addItemWithTitle_action_keyEquivalent_("", None, "")
        self.i_aviso.setEnabled_(False)
        self.i_aviso.setHidden_(True)
        self.i_abrir = menu.addItemWithTitle_action_keyEquivalent_("Abrir NO LIMIT", "abrir:", "")
        self.i_alternar = menu.addItemWithTitle_action_keyEquivalent_("Activar", "alternar:", "")
        menu.addItem_(NSMenuItem.separatorItem())
        self.i_salir = menu.addItemWithTitle_action_keyEquivalent_("Salir", "salirApp:", "")
        for i in (self.i_abrir, self.i_alternar, self.i_salir):
            i.setTarget_(delegado)
        self.item.setMenu_(menu)
        self.icono = self.item

    @property
    def disponible(self):
        return self.item is not None

    def estado(self, activo, alerta=None):
        if self.item is None:
            return
        clave = "alerta" if alerta else "activo" if activo else "apagado"
        imagen = self.imagenes.get(clave) or self.imagenes.get("activo")
        if imagen is not None:
            self.item.button().setImage_(imagen)
        detalle = alerta or ("Activo" if activo else "Apagado")
        self.item.button().setToolTip_(f"NO LIMIT · {detalle}"[:120])
        self.i_alternar.setTitle_("Detener" if activo else "Activar")
        self.i_aviso.setTitle_((alerta or "")[:70])
        self.i_aviso.setHidden_(not alerta)

    def avisar(self, texto, titulo=None):
        pass                             # en Mac no se mandan notificaciones: el icono ya esta a la vista

    def marco(self):
        try:
            return self.item.button().window().frame()
        except Exception:
            return None

    def cerrar(self):
        if self.item is not None:
            try:
                NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
            except Exception:
                pass
        self.item = None


class RaizMac:
    """Lo poquito de Tk que usa la logica de la ventana, hecho con AppKit (coordenadas como Tk: desde arriba)."""

    def __init__(self, nsapp, ventana):
        self.nsapp = nsapp
        self.w = ventana
        self._muerta = False

    def state(self):
        if self.w.isMiniaturized():
            return "iconic"
        if not self.w.isVisible():
            return "withdrawn"
        return "normal"

    def withdraw(self):
        self.w.orderOut_(None)
        self.nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # sin icono en el Dock

    def deiconify(self):
        self.nsapp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        if self.w.isMiniaturized():
            self.w.deminiaturize_(None)
        self.w.makeKeyAndOrderFront_(None)

    def iconify(self):
        self.w.miniaturize_(None)

    def attributes(self, nombre, valor=None):
        if nombre == "-alpha":
            if valor is None:
                return self.w.alphaValue()
            self.w.setAlphaValue_(float(valor))
        elif nombre == "-topmost":
            self.w.setLevel_(NSFloatingWindowLevel if valor else NSNormalWindowLevel)

    def geometry(self, valor=None):
        f = self.w.frame()
        alto = _alto_principal()
        if valor is None:
            x, y = f.origin.x, alto - (f.origin.y + f.size.height)
            return f"{int(f.size.width)}x{int(f.size.height)}+{int(round(x))}+{int(round(y))}"
        numeros = re.findall(r"-?\d+", valor.split("x")[-1] if "x" in valor else valor)
        if len(numeros) >= 2:
            x, y = float(numeros[-2]), float(numeros[-1])
            self.w.setFrameOrigin_(NSMakePoint(x, alto - y - f.size.height))

    def winfo_width(self):
        return int(self.w.frame().size.width)

    def winfo_height(self):
        return int(self.w.frame().size.height)

    def winfo_screenwidth(self):
        return int(NSScreen.mainScreen().frame().size.width)

    def winfo_screenheight(self):
        return int(NSScreen.mainScreen().frame().size.height)

    def lift(self):
        self.w.orderFrontRegardless()

    def focus_force(self):
        self.nsapp.activateIgnoringOtherApps_(True)
        self.w.makeKeyAndOrderFront_(None)

    def after(self, ms, fn):
        def bloque(reloj):
            if self._muerta:
                return
            try:
                fn()
            except Exception as ex:
                log.error("ventana: %s", ex, exc_info=True)
        # (el ciclo de macOS se queda con el reloj; en 'common modes' sigue aunque haya un menu abierto)
        reloj = NSTimer.timerWithTimeInterval_repeats_block_(max(0.001, ms / 1000.0), False, bloque)
        NSRunLoop.currentRunLoop().addTimer_forMode_(reloj, NSRunLoopCommonModes)
        return reloj

    def destroy(self):
        self._muerta = True
        self.w.orderOut_(None)
        self.nsapp.stop_(None)
        # un evento vacio para que run() regrese ya
        ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            NSEventTypeApplicationDefined, NSMakePoint(0, 0), 0, 0, 0, None, 0, 0, 0)
        self.nsapp.postEvent_atStart_(ev, True)

    def clipboard_get(self):
        return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString) or ""

    def update_idletasks(self):
        pass

    def update(self):
        pass

    def mainloop(self):
        self.nsapp.run()


def _menu_principal(app):
    barra = NSMenu.alloc().init()
    item = NSMenuItem.alloc().init()
    barra.addItem_(item)
    menu = NSMenu.alloc().init()
    menu.addItemWithTitle_action_keyEquivalent_("Salir de NO LIMIT", "terminate:", "q")
    item.setSubmenu_(menu)
    item2 = NSMenuItem.alloc().init()
    barra.addItem_(item2)
    edicion = NSMenu.alloc().initWithTitle_("Edición")
    edicion.addItemWithTitle_action_keyEquivalent_("Pegar", "paste:", "v")
    item2.setSubmenu_(edicion)
    app.setMainMenu_(barra)


# ---------------------------------------------------------------- la ventana

class VentanaMac(Ventana):
    def __init__(self, config, bot, escala=None, con_bandeja=True, mostrar=True):
        self.config = config
        self.bot = bot
        self.nsapp = NSApplication.sharedApplication()
        self.nsapp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self._delegado = _DelegadoNL.alloc().init()
        self._delegado.dueno = self
        self.nsapp.setDelegate_(self._delegado)
        _menu_principal(self.nsapp)

        if escala is None:               # se dibuja a la resolucion real de la pantalla (Retina = 2x): nitida
            escala = max([1.0] + [float(s.backingScaleFactor()) for s in NSScreen.screens()])
        self.e = escala
        self.ui = Interfaz(config, self, escala)

        zona = NSScreen.mainScreen().visibleFrame()
        x = zona.origin.x + (zona.size.width - ANCHO) / 2
        y = zona.origin.y + max(0, (zona.size.height - ALTO) / 2 + 20)
        estilo = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(x, y, ANCHO, ALTO), estilo,
                                                                         NSBackingStoreBuffered, False)
        w.setTitle_("NO LIMIT")
        w.setTitleVisibility_(NSWindowTitleHidden)
        w.setTitlebarAppearsTransparent_(True)
        w.setBackgroundColor_(NSColor.blackColor())
        try:
            w.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        except Exception:
            pass
        w.setReleasedWhenClosed_(False)
        w.setAcceptsMouseMovedEvents_(True)
        w.setCollectionBehavior_(NSWindowCollectionBehaviorMoveToActiveSpace)
        w.setDelegate_(self._delegado)
        self.vista = _VistaNL.alloc().initWithFrame_(NSMakeRect(0, 0, ANCHO, ALTO))
        self.vista.dueno = self
        w.setContentView_(self.vista)
        w.makeFirstResponder_(self.vista)
        self.ventana = w
        self.root = RaizMac(self.nsapp, w)

        self.cola = queue.Queue()
        self.foto = None
        self._chicas = {}
        self._mostrada = None
        self._cursor = "arrow"
        self._cerrado = False
        self.visible = True
        self._fundido = None
        self._origen = None
        self._activo_bandeja = None
        self._alerta = None
        self._instalador = None
        self._actualizando = False
        self._calentando = True
        self._calentar_desde = time.time() + 1.0
        self._evento = None
        self._actividad = None
        self.bandeja = self._crear_bandeja() if con_bandeja else None

        if mostrar:
            self.nsapp.activateIgnoringOtherApps_(True)
            w.makeKeyAndOrderFront_(None)
        self._hwnd = self.hwnd()
        self.bot.hwnd_propio = self._hwnd
        self._pintar()
        self.root.after(30, self._tick)
        licencia.refrescar_en_fondo()
        self.root.after(licencia.REVISAR_CADA * 1000, self._revisar_licencia)
        self.root.after(4000, self._revisar_version)

    # ---------------------------------------------------------------- lo que cambia en Mac
    def hwnd(self):
        try:
            return int(self.ventana.windowNumber())
        except Exception:
            return None

    def _crear_bandeja(self):
        try:
            archivos = {k: rutas.asset(f"barra_mac{s}.png")
                        for k, s in (("activo", ""), ("apagado", "_apagado"), ("alerta", "_alerta"))}
            return BandejaMac(self._delegado, archivos)
        except Exception as ex:
            log.warning("sin icono en la barra de arriba: %s", ex)
            return None

    def _barra_oscura(self):
        pass

    def _enfocada(self):
        try:
            return bool(self.nsapp.isActive() and self.ventana.isKeyWindow())
        except Exception:
            return True

    def _junto_al_reloj(self):
        """En Mac se va hacia su icono en la barra de arriba."""
        W, H = self.root.winfo_width(), self.root.winfo_height()
        marco = self.bandeja.marco() if self.bandeja is not None else None
        if marco is not None:
            cx = marco.origin.x + marco.size.width / 2
            return cx - W / 2, 0
        return self.root.winfo_screenwidth() - W / 2 - 160, 0

    def _pintar(self):
        if not self.visible or self._cerrado:
            return
        img = self.ui.render()
        if img is self._mostrada:
            return
        pedazos = self.ui.sucio if self._mostrada is not None else None
        nueva = NSImage.alloc().initWithCGImage_size_(_cgimagen(img), NSMakeSize(ANCHO, ALTO))
        self.vista.imagen = nueva
        k = img.width / float(ANCHO)
        if pedazos is None:
            self.vista.setNeedsDisplay_(True)
        else:
            for x0, y0, x1, y1 in pedazos:
                self.vista.setNeedsDisplayInRect_(NSMakeRect(x0 / k - 1, y0 / k - 1, (x1 - x0) / k + 2,
                                                             (y1 - y0) / k + 2))
        self._mostrada = img

    def _mouse(self, que, x=0.0, y=0.0):
        if que == "mover":
            cambio = self.ui.mover(x, y)
        elif que == "presionar":
            cambio = self.ui.presionar(x, y)
        elif que == "soltar":
            cambio = self.ui.soltar(x, y)
        else:
            cambio = self.ui.salir()
        self._raton(cambio)

    def _raton(self, cambio):
        self._cursor = self.ui.cursor
        try:
            getattr(NSCursor, _CURSORES.get(self._cursor, "arrowCursor"))().set()
        except Exception:
            pass
        if cambio:
            self._pintar()

    def _tecla_mac(self, evento):
        codigo = evento.keyCode()
        cmd = bool(evento.modifierFlags() & NSEventModifierFlagCommand)
        simbolo = _TECLAS.get(codigo)
        if cmd:
            letra = (evento.charactersIgnoringModifiers() or "").lower()
            if letra == "q":
                self.salir()
                return True
            if letra == "w":
                self._al_cerrar()
                return True
            if letra == "v":
                self._pegar()
                return True
            cambio = self.ui.tecla("", simbolo or letra, True)
        else:
            texto = evento.characters() or ""
            cambio = self.ui.tecla("" if simbolo else texto, simbolo or texto, False)
        if cambio:
            self._pintar()
        return True

    def _pegar(self):
        if self.ui.tecla("v", "v", True):
            self._pintar()

    def leer_portapapeles(self):
        return self.root.clipboard_get()

    def abrir_url(self, url):
        threading.Thread(target=lambda: _sin_error(subprocess.Popen, ["/usr/bin/open", url]),
                         name="url", daemon=True).start()

    def abrir_carpeta(self):
        carpeta = os.path.join(rutas.carpeta_datos(), "revision")
        os.makedirs(carpeta, exist_ok=True)
        self.abrir_url(carpeta)

    # version nueva: se baja sola el DMG y se cambia la app al cerrar (o al tocar Actualizar)
    def _buscar_actualizacion(self):
        eventos = self.bot.eventos
        try:
            info = actualizar_mac.buscar()
        except Exception:
            return
        if not info:
            return
        v, url, tam = info
        eventos.put(("nueva_version", v))
        if not url or not actualizar_mac.app_actual():
            return
        try:
            ruta = actualizar_mac.descargar(v, url, tam, al_avance=lambda p: eventos.put(("descarga", p)),
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

    def actualizar(self):
        if not self._instalador:
            self.abrir_url(version.PAGINA)
            return
        if actualizar_mac.instalar(self._instalador, relanzar=True):
            self._actualizando = True
            self._instalador = None
            self.salir()

    def salir(self):
        if not self._cerrado and self._instalador and not self._actualizando:
            # ya estaba bajada: se cambia callada al cerrar (la proxima vez abre la nueva)
            self._actualizando = actualizar_mac.instalar(self._instalador, relanzar=False)
        self._instalador = None          # (que no corra el instalador de Windows)
        Ventana.salir(self)

    cerrar = salir

    # permisos de macOS (los pide la Interfaz antes de INYECTAR)
    def faltan_permisos(self):
        return permisos.faltan()

    def permisos(self):
        return permisos.estado()

    def pedir_permiso(self, cual):
        permisos.pedir(cual)

    def _alternar(self):
        if not self.bot.activo and (not self.bot.puede_iniciar() or permisos.faltan()):
            self.mostrar()               # falta la clave o un permiso: se pide en la ventana
        self.ui.inyectar()

    # que macOS no la duerma mientras escucha (App Nap)
    def iniciar(self):
        self.bot.iniciar()
        if self.bot.activo and self._actividad is None:
            try:
                self._actividad = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
                    NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityLatencyCritical,
                    "Escuchando Option + clic")
            except Exception:
                self._actividad = None

    def detener(self):
        self.bot.detener()
        if self._actividad is not None:
            try:
                NSProcessInfo.processInfo().endActivity_(self._actividad)
            except Exception:
                pass
            self._actividad = None


def _sin_error(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass
