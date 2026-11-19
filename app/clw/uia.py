"""Windows UI Automation (lo mismo que usan los lectores de pantalla), con ctypes y sin librerias extra.

Sirve para saber, como en la Mac:
  - que hay en un punto de la pantalla (un campo para escribir, un enlace, un boton, texto...),
  - donde esta el cursor del teclado (el elemento con el foco) y si ahi se puede escribir.

Asi NO LIMIT solo escribe cuando de verdad el cursor quedo en la casilla correcta (y nunca hace Ctrl + A en la pagina).
Si algo no cuadra (Windows viejo, una app sin accesibilidad), todo regresa None = "no se sabe" y se usa la vista.
"""

import ctypes
import logging
import threading

log = logging.getLogger("clw.uia")

# tipos de control (UIA_*ControlTypeId)
BOTON, CALENDARIO, CASILLA, COMBO, EDITAR, ENLACE, IMAGEN = 50000, 50001, 50002, 50003, 50004, 50005, 50006
ELEMENTO_LISTA, LISTA, MENU, BARRA_MENU, ELEMENTO_MENU, PROGRESO, CIRCULO = 50007, 50008, 50009, 50010, 50011, 50012, 50013
TEXTO, DOCUMENTO, GRUPO, PERSONALIZADO, PANEL, VENTANA = 50020, 50030, 50026, 50025, 50033, 50032

NOMBRES = {BOTON: "boton", CASILLA: "casilla", COMBO: "menu", EDITAR: "campo", ENLACE: "enlace", IMAGEN: "imagen",
           ELEMENTO_LISTA: "elemento", LISTA: "lista", CIRCULO: "circulo", TEXTO: "texto", DOCUMENTO: "documento",
           GRUPO: "grupo", PERSONALIZADO: "otro", PANEL: "panel", VENTANA: "ventana", ELEMENTO_MENU: "opcion"}
NO_SE_ESCRIBE = {BOTON, CASILLA, ENLACE, IMAGEN, CIRCULO, TEXTO, ELEMENTO_LISTA, ELEMENTO_MENU}
# (el documento de la pagina tampoco se sabe: los juegos en canvas reciben las teclas en la pagina misma)
NO_SE_SABE = {GRUPO, PERSONALIZADO, PANEL, VENTANA, LISTA, MENU, DOCUMENTO}


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


def _guid(texto):
    import uuid
    u = uuid.UUID(texto)
    g = _GUID()
    g.a, g.b, g.c = u.fields[0], u.fields[1], u.fields[2]
    for i, v in enumerate(u.bytes[8:]):
        g.d[i] = v
    return g


class _PUNTO(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_CLSID = "ff48dba4-60ef-4201-aa87-54103eef594e"     # CUIAutomation
_IID = "30cbe57d-d9d0-452a-ab13-7ac5ac4825ee"       # IUIAutomation

# posiciones en la tabla de metodos (UIAutomationClient.h)
_U_RAIZ, _U_EN_PUNTO, _U_FOCO, _U_CAMINANTE = 5, 7, 8, 14
_E_TIPO, _E_TIENE_FOCO, _E_ENFOCABLE, _E_HABILITADO, _E_CAJA = 21, 26, 27, 28, 43
_C_PADRE = 3

_local = threading.local()
_apagado = [False]          # si algo no cuadro una vez, ya no se usa (nunca arriesgarse)


def _metodo(ptr, indice, *tipos):
    tabla = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *tipos)(tabla[indice])
    return lambda *args: fn(ptr, *args)


def _soltar(ptr):
    if ptr:
        try:
            _metodo(ptr, 2)()
        except Exception:
            pass


def _uia():
    """El objeto de UI Automation de este hilo (o None)."""
    if _apagado[0]:
        return None
    u = getattr(_local, "uia", None)
    if u is not None:
        return u or None
    _local.uia = False
    try:
        ole = ctypes.windll.ole32
        ole.CoInitializeEx(None, 0x0)                       # COINIT_MULTITHREADED (si ya estaba iniciado, da igual)
        p = ctypes.c_void_p()
        hr = ole.CoCreateInstance(ctypes.byref(_guid(_CLSID)), None, 1, ctypes.byref(_guid(_IID)), ctypes.byref(p))
        if hr != 0 or not p.value:
            return None
        if not _revisar(p.value):
            log.info("uia: la raiz no cuadra, no se usa")
            _apagado[0] = True
            return None
        _local.uia = p.value
        return p.value
    except Exception as e:
        log.info("uia no disponible: %s", e)
        return None


def _revisar(uia):
    """Que la tabla de metodos sea la que creemos: la raiz del escritorio es un panel del tamano de la pantalla."""
    raiz = ctypes.c_void_p()
    if _metodo(uia, _U_RAIZ, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(raiz)) != 0 or not raiz.value:
        return False
    try:
        tipo = _tipo(raiz.value)
        caja = _caja(raiz.value)
        return tipo == PANEL and caja is not None and caja[2] - caja[0] > 200 and caja[3] - caja[1] > 200
    finally:
        _soltar(raiz.value)


def _tipo(el):
    v = ctypes.c_longlong(0)                                # (8 bytes: aunque la tabla estuviera mal, no se rompe)
    if _metodo(el, _E_TIPO, ctypes.POINTER(ctypes.c_longlong))(ctypes.byref(v)) != 0:
        return None
    return int(v.value & 0xFFFFFFFF)


def _bool(el, indice):
    v = ctypes.c_longlong(0)
    if _metodo(el, indice, ctypes.POINTER(ctypes.c_longlong))(ctypes.byref(v)) != 0:
        return None
    return bool(v.value & 0xFFFFFFFF)


class _RECTL(ctypes.Structure):
    _fields_ = [("izq", ctypes.c_long), ("arriba", ctypes.c_long), ("der", ctypes.c_long), ("abajo", ctypes.c_long),
                ("_extra", ctypes.c_long * 4)]


def _caja(el):
    """(x0, y0, x1, y1) en pixeles de pantalla."""
    r = _RECTL()
    if _metodo(el, _E_CAJA, ctypes.POINTER(_RECTL))(ctypes.byref(r)) != 0:
        return None
    if r.der <= r.izq or r.abajo <= r.arriba:
        return None
    return (r.izq, r.arriba, r.der, r.abajo)


def _padre(uia, el):
    cam = ctypes.c_void_p()
    if _metodo(uia, _U_CAMINANTE, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(cam)) != 0 or not cam.value:
        return None
    try:
        p = ctypes.c_void_p()
        if _metodo(cam.value, _C_PADRE, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(el, ctypes.byref(p)) != 0:
            return None
        return p.value or None
    finally:
        _soltar(cam.value)


def _en_punto(uia, x, y):
    el = ctypes.c_void_p()
    if _metodo(uia, _U_EN_PUNTO, _PUNTO, ctypes.POINTER(ctypes.c_void_p))(_PUNTO(int(x), int(y)), ctypes.byref(el)) != 0:
        return None
    return el.value or None


def preparar(x, y):
    """Le pregunta una vez al navegador que hay en ese punto: Chrome y Edge prenden su accesibilidad al recibirla."""
    uia = _uia()
    if not uia:
        return False
    try:
        el = _en_punto(uia, x, y)
        _soltar(el)
        return bool(el)
    except Exception:
        return False


def que_hay_en(x, y):
    """{'rol', 'campo': True/False/None, 'enlace': bool, 'caja'} del elemento en ese punto, o None si no se sabe."""
    uia = _uia()
    if not uia:
        return None
    try:
        el = _en_punto(uia, x, y)
        if not el:
            return None
        tipo0 = _tipo(el)
        caja0 = _caja(el)
        campo, enlace, actual = None, False, el
        for nivel in range(4):
            t = _tipo(actual) if nivel else tipo0
            if t == ENLACE:
                enlace = True
            if t == EDITAR:
                campo = True
                break
            if t in (DOCUMENTO, VENTANA, PANEL):
                break
            padre = _padre(uia, actual)
            if actual is not el:
                _soltar(actual)
            if not padre:
                actual = None
                break
            actual = padre
        if actual is not None and actual is not el:
            _soltar(actual)
        _soltar(el)
        if campo is None and tipo0 in NO_SE_ESCRIBE:
            campo = False
        return {"rol": NOMBRES.get(tipo0, str(tipo0)), "campo": campo, "enlace": enlace, "caja": caja0}
    except Exception as e:
        log.info("uia que_hay_en: %s", e)
        return None


def foco():
    """El elemento con el cursor del teclado: {'rol', 'editable': True/False/None, 'caja'} o None si no se sabe."""
    uia = _uia()
    if not uia:
        return None
    try:
        el = ctypes.c_void_p()
        if _metodo(uia, _U_FOCO, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(el)) != 0 or not el.value:
            return None
        try:
            tipo = _tipo(el.value)
            caja = _caja(el.value)
        finally:
            _soltar(el.value)
        if tipo == EDITAR:
            editable = True
        elif tipo in NO_SE_SABE or tipo is None:
            editable = None
        else:
            editable = False                 # la pagina (documento), un boton, una casilla...: ahi no se escribe
        return {"rol": NOMBRES.get(tipo, str(tipo)), "editable": editable, "caja": caja}
    except Exception as e:
        log.info("uia foco: %s", e)
        return None
