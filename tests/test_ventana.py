"""Logica de la ventana con un Tk falso (corre en cualquier sistema): esconderse junto al reloj despues de
INYECTAR, no dibujar nada escondida, avisos, volver a abrir, la X y el menu del icono del reloj."""

import os
import queue
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

try:
    import tkinter  # noqa: F401
except ImportError:                      # Linux sin Tk: basta un modulo de mentiras
    _tk = types.ModuleType("tkinter")

    class TclError(Exception):
        pass

    _tk.TclError = TclError
    _tk.Tk = _tk.Label = _tk.PhotoImage = object
    sys.modules["tkinter"] = _tk

from clw import config  # noqa: E402
from clw.ui import ventana as V  # noqa: E402
from clw.ui.vistas import Interfaz  # noqa: E402


class Reloj:
    t = 1000.0

    def time(self):
        return self.t

    def __call__(self):
        return self.t


class RaizFalsa:
    def __init__(self):
        self.estado = "normal"
        self.alfa = 1.0
        self.topmost = False
        self.destruida = False
        self.siguiente = None

    def state(self):
        return self.estado

    def withdraw(self):
        self.estado = "withdrawn"

    def deiconify(self):
        self.estado = "normal"

    def iconify(self):
        self.estado = "iconic"

    def attributes(self, nombre, valor=None):
        if nombre == "-alpha":
            if valor is None:
                return self.alfa
            self.alfa = valor
        elif nombre == "-topmost":
            self.topmost = valor

    def lift(self):
        pass

    def focus_force(self):
        pass

    def after(self, ms, fn):
        if getattr(fn, "__name__", "") == "_tick":
            self.siguiente = ms

    def destroy(self):
        self.destruida = True


class FotoFalsa:
    pegadas = 0

    def __init__(self, img):
        self.w, self.h = img.size
        FotoFalsa.pegadas += 1

    def width(self):
        return self.w

    def height(self):
        return self.h

    def paste(self, img):
        FotoFalsa.pegadas += 1


class EtiquetaFalsa:
    def configure(self, **k):
        pass


class BandejaFalsa:
    disponible = True

    def __init__(self):
        self.avisos, self.estados, self.cerrada = [], [], False

    def estado(self, activo):
        self.estados.append(activo)

    def avisar(self, texto, titulo=None):
        self.avisos.append(texto)

    def cerrar(self):
        self.cerrada = True


class BotFalso:
    def __init__(self, con_clave=True):
        self.eventos = queue.Queue()
        self.activo = False
        self.log = []
        self.con_clave = con_clave
        self.hwnd_propio = None

    def iniciar(self):
        self.activo = True
        self.log.append("iniciar")
        self.eventos.put(("estado", "activo"))

    def detener(self):
        self.activo = False
        self.log.append("detener")
        self.eventos.put(("estado", "apagado"))

    def puede_iniciar(self):
        return self.con_clave


def _ventana(con_bandeja=True, con_clave=True):
    reloj = Reloj()
    V.time = types.SimpleNamespace(time=reloj.time)          # el reloj de la ventana
    V.ImageTk = types.SimpleNamespace(PhotoImage=FotoFalsa)
    d = tempfile.mkdtemp()
    c = config.Config(os.path.join(d, "a.json"))
    if con_clave:
        c.poner_clave("claude", "sk-ant-x")
    bot = BotFalso(con_clave)
    v = object.__new__(V.Ventana)
    v.config, v.bot, v.root, v.e = c, bot, RaizFalsa(), 1.0
    v.ui = Interfaz(c, v, 1.0, reloj=reloj)
    v.lbl = EtiquetaFalsa()
    v.cola = queue.Queue()
    v.foto = v._mostrada = None
    v._cursor = "arrow"
    v._cerrado = False
    v.visible = True
    v._avisado = False
    v._fundido = None
    v._activo_bandeja = None
    v._evento = None
    v._hwnd = None
    v.bandeja = BandejaFalsa() if con_bandeja else None
    v._enfocada = lambda: True
    v._pintar()
    return v, bot, reloj


def _correr(v, reloj, seg):
    """Corre el ciclo de la ventana como lo haria Tk (respetando lo que pide cada vuelta)."""
    fin = reloj.t + seg
    vueltas = 0
    while reloj.t < fin and not v._cerrado:
        v._tick()
        vueltas += 1
        reloj.t += (v.root.siguiente or 16) / 1000
    return vueltas


def prueba_inyectar_se_va_junto_al_reloj():
    v, bot, reloj = _ventana()
    _correr(v, reloj, 0.5)
    v.ui.inyectar()
    _correr(v, reloj, 0.6)
    assert bot.activo and v.visible, "primero se ve la animacion"
    _correr(v, reloj, 1.0)
    assert not v.visible and v.root.estado == "withdrawn" and v.root.alfa == 1.0
    assert v.bandeja.estados[-1] is True
    assert len(v.bandeja.avisos) == 1 and "reloj" in v.bandeja.avisos[0]
    # escondida: no dibuja nada y casi no despierta
    antes = FotoFalsa.pegadas
    vueltas = _correr(v, reloj, 5.0)
    assert FotoFalsa.pegadas == antes and vueltas <= 21, vueltas
    assert v.root.siguiente == 250


def prueba_avisos_mientras_esta_escondida():
    v, bot, reloj = _ventana()
    v.ui.inyectar()
    _correr(v, reloj, 2.0)
    assert not v.visible
    bot.eventos.put(("actividad", "Tu cuenta de Claude no tiene saldo.", "error"))
    bot.eventos.put(("actividad", "Marcó: Canberra", "ok"))
    bot.eventos.put(("actividad", "No vi ninguna pregunta ahí", "info"))
    _correr(v, reloj, 0.5)
    assert v.bandeja.avisos[1:] == ["Tu cuenta de Claude no tiene saldo.", "No vi ninguna pregunta ahí"]
    # si falta la clave hay que abrir la ventana
    bot.eventos.put(("falta_clave", "claude"))
    _correr(v, reloj, 0.5)
    assert v.visible and v.root.estado == "normal" and v.ui.pantalla == "clave"


def prueba_abrir_desde_el_reloj_con_fundido():
    v, bot, reloj = _ventana()
    v.ui.inyectar()
    _correr(v, reloj, 2.0)
    v.cola.put(v.mostrar)                  # "Abrir CLW GANG" (llega de otro hilo por la cola)
    v._tick()
    assert v.visible and v.root.estado == "normal" and v.root.alfa < 0.5 and v.root.topmost
    _correr(v, reloj, 0.5)
    assert v.root.alfa == 1.0
    # ya visible y activa: muestra DETENER y no se vuelve a esconder sola
    _correr(v, reloj, 3.0)
    assert v.visible and v.ui.estado == "activo"


def prueba_la_x_esconde_si_esta_activo_y_cierra_si_no():
    v, bot, reloj = _ventana()
    v.ui.inyectar()
    _correr(v, reloj, 0.2)
    v._al_cerrar()
    _correr(v, reloj, 0.5)
    assert not v._cerrado and not v.visible and bot.activo
    # Detener desde el menu del reloj
    v.cola.put(v._alternar)
    _correr(v, reloj, 0.5)
    assert not bot.activo and bot.log[-1] == "detener" and v.bandeja.estados[-1] is False
    v.mostrar()
    _correr(v, reloj, 0.5)
    v._al_cerrar()
    assert v._cerrado and v.root.destruida and v.bandeja.cerrada


def prueba_activar_desde_el_reloj_sin_clave_abre_la_ventana():
    v, bot, reloj = _ventana(con_clave=False)
    v.esconder()
    _correr(v, reloj, 0.5)
    assert not v.visible
    v.cola.put(v._alternar)
    _correr(v, reloj, 0.5)
    assert v.visible and v.ui.pantalla == "clave" and not bot.activo


def prueba_salir_desde_el_reloj():
    v, bot, reloj = _ventana()
    v.ui.inyectar()
    _correr(v, reloj, 2.0)
    v.cola.put(v.salir)
    v._tick()
    assert v._cerrado and not bot.activo and v.bandeja.cerrada and v.root.destruida


def prueba_sin_icono_del_reloj_solo_minimiza():
    v, bot, reloj = _ventana(con_bandeja=False)
    v.ui.inyectar()
    _correr(v, reloj, 2.0)
    assert v.root.estado == "iconic" and bot.activo
    # minimizada tampoco dibuja
    antes = FotoFalsa.pegadas
    _correr(v, reloj, 2.0)
    assert FotoFalsa.pegadas == antes
    # la X sin icono del reloj cierra todo (si no, no habria como volver)
    v.mostrar()
    v._al_cerrar()
    assert v._cerrado and not bot.activo


def prueba_sin_foco_dibuja_poco():
    v, bot, reloj = _ventana()
    v._enfocada = lambda: False
    antes = FotoFalsa.pegadas
    vueltas = _correr(v, reloj, 3.0)
    assert FotoFalsa.pegadas - antes <= 1 and vueltas <= 22, (FotoFalsa.pegadas - antes, vueltas)
    v._enfocada = lambda: True
    antes = FotoFalsa.pegadas
    _correr(v, reloj, 1.0)
    assert FotoFalsa.pegadas - antes >= 20, "con foco la estrella se mueve"
