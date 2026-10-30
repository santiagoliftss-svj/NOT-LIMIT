"""Logica de la ventana con un Tk falso (corre en cualquier sistema): irse volando junto al reloj despues de
INYECTAR, no dibujar nada escondida, que no aparezca nada mientras contesta, volver a abrir, la X, el menu del
icono del reloj, repintar solo pedazos y la actualizacion sola."""

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


class TkFalso:
    def __init__(self):
        self.copias = []

    def call(self, *args):
        self.copias.append(args)


class RaizFalsa:
    def __init__(self):
        self.estado = "normal"
        self.alfa = 1.0
        self.topmost = False
        self.destruida = False
        self.siguiente = None
        self.pos = (700, 200)
        self.recorrido = []
        self.tk = TkFalso()

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

    def geometry(self, valor=None):
        if valor is None:
            return f"380x600+{self.pos[0]}+{self.pos[1]}"
        x, y = valor.lstrip("+").split("+")
        self.pos = (int(x), int(y))
        self.recorrido.append(self.pos)

    def winfo_width(self):
        return 380

    def winfo_height(self):
        return 600

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

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
    completas = 0                       # la ventana entera (380 x 600)

    def __init__(self, img):
        self.w, self.h = img.size
        if img.size == (380, 600):
            FotoFalsa.completas += 1

    def __str__(self):
        return "foto%d" % id(self)

    def width(self):
        return self.w

    def height(self):
        return self.h

    def paste(self, img):
        if img.size == (380, 600):
            FotoFalsa.completas += 1


class EtiquetaFalsa:
    def configure(self, **k):
        pass


class BandejaFalsa:
    disponible = True

    def __init__(self):
        self.avisos, self.estados, self.cerrada = [], [], False

    def estado(self, activo, alerta=None):
        self.estados.append((activo, alerta))

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
    v._chicas = {}
    v._cursor = "arrow"
    v._cerrado = False
    v.visible = True
    v._fundido = None
    v._origen = None
    v._activo_bandeja = None
    v._alerta = None
    v._instalador = None
    v._actualizando = False
    v._calentando = True
    v._calentar_desde = reloj.t + 1.0
    v._evento = None
    v._hwnd = None
    v.bandeja = BandejaFalsa() if con_bandeja else None
    v._enfocada = lambda: True
    # cuenta los cuadros que de verdad llegan a la pantalla
    v.cuadros = 0
    pintar = v._pintar

    def contar():
        antes = v._mostrada
        pintar()
        if v._mostrada is not antes:
            v.cuadros += 1
    v._pintar = contar
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


def prueba_inyectar_se_va_volando_junto_al_reloj():
    v, bot, reloj = _ventana()
    _correr(v, reloj, 0.5)
    v.ui.inyectar()
    _correr(v, reloj, 0.6)
    assert bot.activo and v.visible, "primero se ve la animacion"
    _correr(v, reloj, 1.0)
    assert not v.visible and v.root.estado == "withdrawn" and v.root.alfa == 1.0
    # se fue volando hacia la esquina del reloj y regreso a su lugar ya escondida
    reloj_xy = v._junto_al_reloj()             # (en Windows sale de la barra de tareas de verdad)
    assert reloj_xy in v.root.recorrido and reloj_xy != (700, 200), (reloj_xy, v.root.recorrido[-3:])
    assert v.root.pos == (700, 200)
    assert v.bandeja.estados[-1] == (True, None)
    assert len(v.bandeja.avisos) == 1 and "reloj" in v.bandeja.avisos[0]
    # escondida: no dibuja nada y casi no despierta
    antes = v.cuadros
    vueltas = _correr(v, reloj, 5.0)
    assert v.cuadros == antes and vueltas <= 21, vueltas
    assert v.root.siguiente == 250
    # el aviso del reloj sale una sola vez en la vida
    v.mostrar()
    _correr(v, reloj, 0.5)
    assert v.visible and v.root.pos == (700, 200) and v.root.alfa == 1.0
    v.esconder()
    _correr(v, reloj, 0.6)
    assert not v.visible and len(v.bandeja.avisos) == 1


def prueba_mientras_contesta_no_aparece_nada():
    v, bot, reloj = _ventana()
    v.ui.inyectar()
    _correr(v, reloj, 2.0)
    assert not v.visible
    bot.eventos.put(("actividad", "Tu cuenta de Claude no tiene saldo.", "error"))
    bot.eventos.put(("actividad", "No vi ninguna pregunta ahí", "info"))
    _correr(v, reloj, 0.5)
    assert len(v.bandeja.avisos) == 1, "ni una notificacion mientras contesta"
    assert v.bandeja.estados[-1] == (True, "Tu cuenta de Claude no tiene saldo."), "solo lo marca el icono del reloj"
    bot.eventos.put(("actividad", "Marcó: Canberra", "ok"))
    _correr(v, reloj, 0.3)
    assert v.bandeja.estados[-1] == (True, None)
    # si falta la clave tampoco se abre sola: solo marca el icono
    bot.eventos.put(("falta_clave", "claude"))
    _correr(v, reloj, 0.5)
    assert not v.visible and v.root.estado == "withdrawn"
    assert v.bandeja.estados[-1] == (True, "Revisa tu clave")
    v.mostrar()
    assert v.visible and v.ui.pantalla == "clave" and v.bandeja.estados[-1] == (True, None)


def prueba_abrir_desde_el_reloj_con_fundido():
    v, bot, reloj = _ventana()
    v.ui.inyectar()
    _correr(v, reloj, 2.0)
    v.cola.put(v.mostrar)                  # "Abrir NO LIMIT" (llega de otro hilo por la cola)
    v._tick()
    assert v.visible and v.root.estado == "normal" and v.root.alfa < 0.5 and v.root.topmost
    _correr(v, reloj, 0.5)
    assert v.root.alfa == 1.0 and v.root.pos == (700, 200)
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
    assert not bot.activo and bot.log[-1] == "detener" and v.bandeja.estados[-1] == (False, None)
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
    antes = v.cuadros
    _correr(v, reloj, 2.0)
    assert v.cuadros == antes
    # la X sin icono del reloj cierra todo (si no, no habria como volver)
    v.mostrar()
    v._al_cerrar()
    assert v._cerrado and not bot.activo


def prueba_sin_foco_dibuja_poco():
    v, bot, reloj = _ventana()
    v._enfocada = lambda: False
    antes = v.cuadros
    vueltas = _correr(v, reloj, 3.0)
    assert v.cuadros - antes <= 1 and vueltas <= 22, (v.cuadros - antes, vueltas)
    v._enfocada = lambda: True
    antes = v.cuadros
    _correr(v, reloj, 1.0)
    assert v.cuadros - antes >= 20, "con foco el borde del boton brilla"


def prueba_repinta_solo_pedazos():
    v, bot, reloj = _ventana()
    _correr(v, reloj, 0.3)
    completas, copias = FotoFalsa.completas, len(v.root.tk.copias)
    _correr(v, reloj, 1.0)                    # el borde del boton brilla y el logo refleja: solo pedazos
    assert FotoFalsa.completas == completas, "sin cambios grandes no repinta la ventana entera"
    assert len(v.root.tk.copias) > copias + 15
    # pasar el mouse por los botones tambien es un pedazo
    v._raton(v.ui.mover(190, 295))
    v._raton(v.ui.mover(190, 205))
    v._raton(v.ui.salir())
    assert FotoFalsa.completas == completas
    # cambiar de pantalla si repinta todo
    v.ui._accion("ajustes")
    _correr(v, reloj, 0.1)
    assert FotoFalsa.completas > completas


def _actualizador_falso(llamadas):
    viejo = (V.actualizar.buscar, V.actualizar.descargar, V.actualizar.instalar)

    def descargar(ver, url, tam=0, al_avance=None, cancelar=None):
        for p in (12, 57, 99):
            al_avance(p)
        return "C:/datos/actualizacion/NO-LIMIT-Setup-%s.exe" % ver

    V.actualizar.buscar = lambda timeout=8: ("9.9.9", "https://x/NO-LIMIT-Setup.exe", 10)
    V.actualizar.descargar = descargar
    V.actualizar.instalar = lambda ruta, relanzar=True: llamadas.append((ruta, relanzar)) or True
    return viejo


def prueba_se_actualiza_sola():
    v, bot, reloj = _ventana()
    llamadas = []
    viejo = _actualizador_falso(llamadas)
    try:
        v._buscar_actualizacion()               # (en la app corre en otro hilo)
        _correr(v, reloj, 0.2)
        assert v.ui.actualizacion_lista and v.ui.nueva_version == "9.9.9" and v.ui.descarga is None
        assert v._instalador.endswith("9.9.9.exe") and llamadas == []
        # tocar "Actualizar": instala sin ventanas y se vuelve a abrir sola
        v.ui._accion("actualizar")
        assert llamadas == [(v._instalador, True)] and v._cerrado and not bot.activo
    finally:
        V.actualizar.buscar, V.actualizar.descargar, V.actualizar.instalar = viejo


def prueba_al_salir_instala_callada():
    v, bot, reloj = _ventana()
    llamadas = []
    viejo = _actualizador_falso(llamadas)
    try:
        v._buscar_actualizacion()
        _correr(v, reloj, 0.2)
        v.salir()                              # cerrar NO LIMIT con la version nueva ya bajada
        assert llamadas == [(v._instalador, False)], llamadas
    finally:
        V.actualizar.buscar, V.actualizar.descargar, V.actualizar.instalar = viejo


def prueba_arma_las_otras_pantallas_en_ratos_libres():
    v, bot, reloj = _ventana()
    _correr(v, reloj, 0.5)
    assert v.ui._por_calentar is None, "al abrir no se pone a armar nada"
    _correr(v, reloj, 1.5)
    assert v.ui._por_calentar == [] and not v._calentando
    # y no cambio nada de lo que se ve
    assert v.ui.pantalla == "principal" and v.visible

