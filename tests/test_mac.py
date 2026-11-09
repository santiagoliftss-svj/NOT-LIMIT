"""Partes de Mac que se pueden probar sin Mac (con un Quartz de mentiras): Llavero y cifrado, la escucha de
Option + clic, coordenadas, escribir texto y la pantalla de permisos."""

import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from clw import config  # noqa: E402
from clw.mac import entrada as ME  # noqa: E402
from clw.mac import escucha as MS  # noqa: E402
from clw.mac import llavero  # noqa: E402
from clw.ui.vistas import Interfaz  # noqa: E402


# ---------------------------------------------------------------- Quartz de mentiras

class Punto:
    def __init__(self, x, y):
        self.x, self.y = x, y


class Evento:
    def __init__(self, tipo=0, x=0, y=0, banderas=0, tecla=0, marca=0):
        self.tipo, self.p, self.banderas, self.tecla, self.marca = tipo, Punto(x, y), banderas, tecla, marca
        self.unicode = None


def _quartz():
    q = types.SimpleNamespace(
        kCGEventLeftMouseDown=1, kCGEventLeftMouseUp=2, kCGEventMouseMoved=5, kCGEventKeyDown=10, kCGEventKeyUp=11,
        kCGEventFlagMaskAlternate=0x80000, kCGEventFlagMaskCommand=0x100000, kCGEventFlagMaskControl=0x40000,
        kCGEventFlagMaskShift=0x20000, kCGEventSourceUserData=42, kCGKeyboardEventKeycode=9,
        kCGMouseEventClickState=1, kCGHIDEventTap=0, kCGMouseButtonLeft=0, kCGMouseButtonRight=1,
        kCGEventSourceStateCombinedSessionState=0)
    q.mandados = []
    q.reactivada = []

    def campo(ev, cual):
        return ev.tecla if cual == 9 else ev.marca if cual == 42 else 0

    def poner_campo(ev, cual, v):
        if cual == 42:
            ev.marca = v

    def crear_tecla(fuente, codigo, abajo):
        return Evento(q.kCGEventKeyDown if abajo else q.kCGEventKeyUp, tecla=codigo)

    def crear_mouse(fuente, tipo, p, boton):
        return Evento(tipo, p.x, p.y)

    def unicode(ev, n, texto):
        assert n == len(texto.encode("utf-16-le")) // 2
        ev.unicode = texto

    q.CGEventGetIntegerValueField = campo
    q.CGEventSetIntegerValueField = poner_campo
    q.CGEventGetFlags = lambda ev: ev.banderas
    q.CGEventSetFlags = lambda ev, b: setattr(ev, "banderas", b)
    q.CGEventGetLocation = lambda ev: ev.p
    q.CGEventTapEnable = lambda tap, si: q.reactivada.append(si)
    q.CGEventCreateKeyboardEvent = crear_tecla
    q.CGEventCreateMouseEvent = crear_mouse
    q.CGEventKeyboardSetUnicodeString = unicode
    q.CGEventPost = lambda donde, ev: q.mandados.append(ev)
    q.CGPointMake = Punto
    q.CGEventSourceKeyState = lambda estado, tecla: False
    q.CGEventSourceFlagsState = lambda estado: 0
    return q


def _con_quartz():
    q = _quartz()
    ME.Q = MS.Q = q
    ME.pantalla_en = lambda x, y: ((0, 0, 1440, 900), 2.0)
    return q


# ---------------------------------------------------------------- Llavero

def prueba_cifrado_con_llave():
    k = os.urandom(32)
    for texto in ("sk-ant-api03-ñ¿√", "", "AIza" + "x" * 300):
        c = llavero.cifrar(texto.encode("utf-8"), k)
        assert not texto or texto not in c
        assert llavero.descifrar(c, k).decode("utf-8") == texto
    # con otra llave (otro Mac) o si alguien la cambia: no se acepta
    c = llavero.cifrar(b"sk-ant-x", k)
    for malo in (lambda: llavero.descifrar(c, os.urandom(32)),
                 lambda: llavero.descifrar(c[:-4] + ("AAAA" if c[-4:] != "AAAA" else "BBBB"), k)):
        try:
            malo()
            assert False, "debio fallar"
        except ValueError:
            pass


def prueba_llave_en_el_llavero():
    guardado = {}
    llamadas = []

    class P:
        def __init__(self, codigo, salida=b""):
            self.returncode, self.stdout, self.stderr = codigo, salida, b""

    def correr(args, entrada=None):
        llamadas.append((list(args), entrada))
        if args[0] == "find-generic-password":
            return P(0, (guardado["w"] + "\n").encode()) if "w" in guardado else P(44)
        if args[0] == "-i":
            texto = entrada.decode()
            assert texto.startswith("add-generic-password -U -s \"NO LIMIT\"")
            guardado["w"] = texto.split('-w "')[1].split('"')[0]
            return P(0)
        return P(1)

    viejo = llavero._correr
    llavero._correr, llavero._cache = correr, {}
    try:
        k = llavero.llave()
        assert len(k) == 32 and k.hex() == guardado["w"]
        # la llave nunca va en los argumentos (se veria en la lista de procesos)
        assert all(guardado["w"] not in " ".join(a) for a, _ in llamadas)
        assert llavero.llave() is k, "se lee una sola vez"
        # config usa el Llavero en Mac
        viejo = (config.rutas.MAC, config.rutas.WINDOWS)
        config.rutas.MAC, config.rutas.WINDOWS = True, False      # (como si fuera una Mac)
        try:
            v = config.proteger("sk-ant-prueba")
            assert v.startswith("mac:") and config.desproteger(v) == "sk-ant-prueba"
        finally:
            config.rutas.MAC, config.rutas.WINDOWS = viejo
    finally:
        llavero._correr, llavero._cache = viejo, {}


# ---------------------------------------------------------------- Option + clic

def prueba_option_clic_dispara_y_no_le_llega_a_la_pagina():
    q = _con_quartz()
    disparos = []
    e = MS.EscuchaCtrlClic(lambda x, y: disparos.append((x, y)), es_propia=lambda x, y: x < 100)
    e._disparar = lambda x, y: disparos.append((x, y))       # (sin hilo en la prueba)
    abajo = Evento(q.kCGEventLeftMouseDown, 400, 300, q.kCGEventFlagMaskAlternate)
    assert e._decidir(abajo.tipo, abajo) is None, "el clic no le llega a la pagina"
    arriba = Evento(q.kCGEventLeftMouseUp, 400, 300)
    assert e._decidir(arriba.tipo, arriba) is None, "ni cuando se suelta"
    assert disparos == [(800.0, 600.0)], disparos           # pixeles Retina (2x)
    assert ME.escala_actual() == 2.0
    # el siguiente clic normal si pasa
    for ev in (Evento(q.kCGEventLeftMouseDown, 400, 300), Evento(q.kCGEventLeftMouseUp, 400, 300)):
        assert e._decidir(ev.tipo, ev) is ev
    # Option + Cmd, Option + Shift, Ctrl + clic (= clic derecho en Mac): no
    for b in (q.kCGEventFlagMaskAlternate | q.kCGEventFlagMaskCommand,
              q.kCGEventFlagMaskAlternate | q.kCGEventFlagMaskShift, q.kCGEventFlagMaskControl):
        ev = Evento(q.kCGEventLeftMouseDown, 400, 300, b)
        assert e._decidir(ev.tipo, ev) is ev
    # sobre la ventana de NO LIMIT: clic normal
    ev = Evento(q.kCGEventLeftMouseDown, 20, 300, q.kCGEventFlagMaskAlternate)
    assert e._decidir(ev.tipo, ev) is ev
    # los clics que manda NO LIMIT pasan sin tocarse
    ev = Evento(q.kCGEventLeftMouseDown, 400, 300, q.kCGEventFlagMaskAlternate, marca=ME.MARCA)
    assert e._decidir(ev.tipo, ev) is ev
    assert len(disparos) == 1
    # si macOS apaga la escucha, se vuelve a prender
    e._tap = object()
    assert e._decidir(0xFFFFFFFE, abajo) is abajo and q.reactivada == [True]


def prueba_esc_se_ve_desde_la_escucha():
    q = _con_quartz()
    e = MS.EscuchaCtrlClic(lambda x, y: None)
    ME._esc.update(abajo=False, t=0.0)
    assert not ME.tecla_abajo(ME.VK_ESCAPE)
    ev = Evento(q.kCGEventKeyDown, tecla=ME.K_ESC)
    assert e._decidir(ev.tipo, ev) is ev, "Esc le sigue llegando a la pagina"
    assert ME.tecla_abajo(ME.VK_ESCAPE)
    ev = Evento(q.kCGEventKeyUp, tecla=ME.K_ESC)
    e._decidir(ev.tipo, ev)
    assert ME.tecla_abajo(ME.VK_ESCAPE), "un toque rapido de Esc tambien cuenta"
    ME._esc["t"] = 0.0
    assert not ME.tecla_abajo(ME.VK_ESCAPE)


def prueba_clic_y_texto_en_puntos():
    q = _con_quartz()
    ME.poner_escala(2.0)
    ME.clic(800, 600)
    movs = [ev for ev in q.mandados]
    assert [ev.tipo for ev in movs] == [q.kCGEventMouseMoved, q.kCGEventLeftMouseDown, q.kCGEventLeftMouseUp]
    assert all((ev.p.x, ev.p.y) == (400, 300) and ev.marca == ME.MARCA and ev.banderas == 0 for ev in movs)
    q.mandados.clear()
    ME.seleccionar_todo()
    assert [(ev.tecla, ev.banderas) for ev in q.mandados] == [(ME.K_A, q.kCGEventFlagMaskCommand)] * 2
    q.mandados.clear()
    texto = "Cuatro, señor ¿sí? √3 🙂"
    assert ME.escribir(texto)
    assert "".join(ev.unicode for ev in q.mandados if ev.tipo == q.kCGEventKeyDown) == texto
    assert len(q.mandados) == 2 * len(texto)
    # Esc a media escritura: se detiene
    q.mandados.clear()
    ME.nota_esc(True)
    try:
        ME.escribir("hola")
        assert False
    except ME.Cancelado:
        pass
    ME.nota_esc(False)
    ME._esc["t"] = 0.0


def prueba_ventana_bajo_el_mouse():
    _con_quartz()
    ME.poner_escala(2.0)
    lista = [(7, 111, 0, (100, 100, 380, 628)), (3, 222, 0, (0, 0, 1440, 900))]
    viejo = ME.ventanas
    ME.ventanas = lambda fresca=False: lista
    try:
        assert ME.ventana_raiz_en(400, 400) == 7          # (200, 200) pt: encima esta NO LIMIT
        assert ME.ventana_raiz_en(1200, 400) == 3
        assert ME.rect_ventana(7) == (200, 200, 960, 1456)
        assert ME.rect_ventana(9) is None
    finally:
        ME.ventanas = viejo


# ---------------------------------------------------------------- pantalla de permisos

class AppMac:
    def __init__(self):
        self.ui = None
        self.estado = {"accesibilidad": False, "pantalla": False}
        self.pedidos = []
        self.log = []

    def faltan_permisos(self):
        return [k for k, v in self.estado.items() if not v]

    def permisos(self):
        return dict(self.estado)

    def pedir_permiso(self, cual):
        self.pedidos.append(cual)

    def iniciar(self):
        self.log.append("iniciar")
        self.ui.evento_bot(("estado", "activo"))

    def detener(self):
        self.log.append("detener")
        self.ui.evento_bot(("estado", "apagado"))

    def __getattr__(self, n):
        return lambda *a, **k: ""


def _clic(ui, zid):
    ui.render()
    for z, (x, y, w, h), _ in reversed(ui.zonas):
        if z == zid:
            ui.mover(x + w / 2, y + h / 2)
            ui.presionar(x + w / 2, y + h / 2)
            ui.soltar(x + w / 2, y + h / 2)
            return
    raise AssertionError(f"no hay zona {zid}: {[z[0] for z in ui.zonas]}")


def prueba_permisos_antes_de_inyectar():
    t = [100.0]
    c = config.Config(os.path.join(tempfile.mkdtemp(), "a.json"))
    c.poner_clave("claude", "sk-ant-x")
    app = AppMac()
    ui = Interfaz(c, app, 2.0, reloj=lambda: t[0])
    app.ui = ui
    ui.render()
    _clic(ui, "inyectar")
    assert ui.pantalla == "permisos" and app.log == [], "sin permisos no arranca"
    t[0] += 1
    _clic(ui, "permiso:accesibilidad")
    assert app.pedidos == ["accesibilidad"]
    _clic(ui, "permisos_listo")
    assert ui.pantalla == "permisos" and "Accesibilidad y Grabación de pantalla" in ui.msg_permisos
    # los da en Ajustes del Sistema: la pantalla se entera sola
    app.estado = {"accesibilidad": True, "pantalla": True}
    img = ui.render()
    assert img.size == (760, 1200)
    if os.environ.get("CLW_CAPTURAS"):
        os.makedirs(os.environ["CLW_CAPTURAS"], exist_ok=True)
        img.convert("RGB").save(os.path.join(os.environ["CLW_CAPTURAS"], "mac_permisos_listos.png"))
    _clic(ui, "permisos_listo")
    assert ui.pantalla == "principal" and app.log == ["iniciar"]
    # (y sin clave, primero la clave y luego arranca)
    app.estado = {"accesibilidad": True, "pantalla": False}
    _clic(ui, "inyectar")             # apagar
    c.poner_clave("claude", "")
    t[0] += 1
    _clic(ui, "inyectar")
    assert ui.pantalla == "clave"
    if os.environ.get("CLW_CAPTURAS"):
        app.estado = {"accesibilidad": False, "pantalla": False}
        ui._ir("permisos")
        t[0] += 1
        ui.render().convert("RGB").save(os.path.join(os.environ["CLW_CAPTURAS"], "mac_permisos.png"))
