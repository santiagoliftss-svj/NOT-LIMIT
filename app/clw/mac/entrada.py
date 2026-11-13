"""Mouse y teclado en Mac (Quartz): clics, escribir texto y leer teclas. Misma interfaz que clw.entrada.

Coordenadas: el motor trabaja en pixeles de la captura. En Mac la captura sale en pixeles reales (Retina = 2x)
y el sistema trabaja en puntos, asi que aqui se guarda la escala de la pantalla donde se dio el Option + clic
y todo se convierte con ella (puntos x escala = pixeles).
"""

import os
import threading
import time

try:
    import Quartz as Q
except ImportError:          # en Linux (pruebas) se pone uno falso
    Q = None

U32 = None                   # (solo existe en Windows)

VK_LBUTTON, VK_RBUTTON, VK_CONTROL, VK_ESCAPE = 0x01, 0x02, 0x11, 0x1B
VK_MENU = 0x12               # Alt de Windows = Option de Mac
VK_ATAJO = VK_MENU           # la tecla que va con el clic: Option + clic
MARCA = 0x4E4F4C4D           # eventos que manda NO LIMIT (la escucha los deja pasar)
K_ESC, K_A = 53, 0           # codigos de tecla de Mac


class Cancelado(Exception):
    pass


# ---------------------------------------------------------------- escala (puntos <-> pixeles)

_escala = 2.0


def escala_actual():
    return _escala


def poner_escala(s):
    global _escala
    try:
        s = float(s)
    except (TypeError, ValueError):
        s = 1.0
    _escala = s if s > 0 else 1.0


def pantalla_en(x, y):
    """((x, y, w, h) en puntos, escala) de la pantalla donde esta ese punto."""
    try:
        err, ids, n = Q.CGGetDisplaysWithPoint(Q.CGPointMake(x, y), 1, None, None)
        d = ids[0] if (not err and n) else Q.CGMainDisplayID()
    except Exception:
        d = Q.CGMainDisplayID()
    b = Q.CGDisplayBounds(d)
    escala = 1.0
    try:
        modo = Q.CGDisplayCopyDisplayMode(d)
        ancho, ancho_px = Q.CGDisplayModeGetWidth(modo), Q.CGDisplayModeGetPixelWidth(modo)
        if ancho:
            escala = ancho_px / ancho
    except Exception:
        pass
    return (b.origin.x, b.origin.y, b.size.width, b.size.height), max(1.0, escala)


# ---------------------------------------------------------------- teclas y mouse

_esc = {"abajo": False, "t": 0.0}


def nota_esc(abajo):
    """La escucha avisa cuando se presiona o suelta Esc (asi no hace falta el permiso de 'monitoreo')."""
    _esc["abajo"] = bool(abajo)
    if abajo:
        _esc["t"] = time.time()


def _banderas():
    try:
        return int(Q.CGEventSourceFlagsState(Q.kCGEventSourceStateCombinedSessionState))
    except Exception:
        return 0


def tecla_abajo(vk):
    try:
        if vk == VK_ESCAPE:
            if _esc["abajo"] or time.time() - _esc["t"] < 0.25:
                return True
            return bool(Q.CGEventSourceKeyState(Q.kCGEventSourceStateCombinedSessionState, K_ESC))
        if vk == VK_MENU:
            return bool(_banderas() & Q.kCGEventFlagMaskAlternate)
        if vk == VK_CONTROL:
            return bool(_banderas() & Q.kCGEventFlagMaskControl)
        if vk in (VK_LBUTTON, VK_RBUTTON):
            boton = Q.kCGMouseButtonLeft if vk == VK_LBUTTON else Q.kCGMouseButtonRight
            return bool(Q.CGEventSourceButtonState(Q.kCGEventSourceStateCombinedSessionState, boton))
    except Exception:
        return False
    return False


def boton_izquierdo():
    return VK_LBUTTON


def posicion_puntos():
    p = Q.CGEventGetLocation(Q.CGEventCreate(None))
    return p.x, p.y


def posicion_mouse():
    x, y = posicion_puntos()
    return x * _escala, y * _escala


def bajar_prioridad_hilo():
    pass


def juego_en_pantalla_completa():
    return False


def soltar_ctrl_si_hace_falta():
    pass


def ventana_al_frente():
    return None


def clase_ventana(h):
    return ""


# ---------------------------------------------------------------- ventanas en pantalla

_lista = {"t": 0.0, "ventanas": []}
_candado = threading.Lock()


def ventanas(fresca=False):
    """[(numero, pid, capa, (x, y, w, h) en puntos)] de adelante hacia atras (solo ventanas normales)."""
    with _candado:
        if not fresca and time.time() - _lista["t"] < 0.4:
            return _lista["ventanas"]
        out = []
        try:
            info = Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements,
                                                Q.kCGNullWindowID) or []
            for w in info:
                capa = int(w.get("kCGWindowLayer", 0))
                if capa < 0 or capa > 19 or float(w.get("kCGWindowAlpha", 1.0)) < 0.02:
                    continue
                b = w.get("kCGWindowBounds") or {}
                caja = (float(b.get("X", 0)), float(b.get("Y", 0)), float(b.get("Width", 0)), float(b.get("Height", 0)))
                if caja[2] < 4 or caja[3] < 4:
                    continue
                out.append((int(w.get("kCGWindowNumber", 0)), int(w.get("kCGWindowOwnerPID", 0)), capa, caja))
        except Exception:
            out = []
        _lista["t"], _lista["ventanas"] = time.time(), out
        return out


def ventana_raiz_en(x, y):
    """Numero de la ventana que se ve en ese punto (pixeles)."""
    px, py = x / _escala, y / _escala
    for numero, pid, capa, (wx, wy, ww, wh) in ventanas():
        if wx <= px < wx + ww and wy <= py < wy + wh:
            return numero
    return None


def rect_ventana(numero):
    """(x0, y0, x1, y1) en pixeles de una ventana visible, o None."""
    for n, pid, capa, (wx, wy, ww, wh) in ventanas(fresca=True):
        if n == numero:
            s = _escala
            return int(wx * s), int(wy * s), int((wx + ww) * s), int((wy + wh) * s)
    return None


def es_de_esta_app(numero):
    for n, pid, capa, caja in ventanas():
        if n == numero:
            return pid == os.getpid()
    return False


# ---------------------------------------------------------------- mandar eventos (necesita Accesibilidad)

def _mandar(evento, banderas=0):
    Q.CGEventSetFlags(evento, banderas)
    Q.CGEventSetIntegerValueField(evento, Q.kCGEventSourceUserData, MARCA)
    Q.CGEventPost(Q.kCGHIDEventTap, evento)


def clic(x, y):
    p = Q.CGPointMake(x / _escala, y / _escala)
    _mandar(Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, p, Q.kCGMouseButtonLeft))
    time.sleep(0.05)
    abajo = Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseDown, p, Q.kCGMouseButtonLeft)
    Q.CGEventSetIntegerValueField(abajo, Q.kCGMouseEventClickState, 1)
    _mandar(abajo)
    time.sleep(0.03)
    arriba = Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseUp, p, Q.kCGMouseButtonLeft)
    Q.CGEventSetIntegerValueField(arriba, Q.kCGMouseEventClickState, 1)
    _mandar(arriba)


def _tecla(codigo, banderas=0):
    _mandar(Q.CGEventCreateKeyboardEvent(None, codigo, True), banderas)
    _mandar(Q.CGEventCreateKeyboardEvent(None, codigo, False), banderas)


def seleccionar_todo():
    _tecla(K_A, Q.kCGEventFlagMaskCommand)


TECLAS = {"derecha": 124, "izquierda": 123, "arriba": 126, "abajo": 125, "retroceso": 51, "escape": 53, "enter": 36}


def tecla(nombre, veces=1):
    """Presiona una tecla especial (derecha, izquierda, arriba, abajo, retroceso, escape, enter)."""
    codigo = TECLAS[nombre]
    for _ in range(max(1, int(veces))):
        _tecla(codigo)
        time.sleep(0.03)


def mover(x, y):
    """Solo pone el mouse encima (sin clic). Pixeles."""
    p = Q.CGPointMake(x / _escala, y / _escala)
    _mandar(Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, p, Q.kCGMouseButtonLeft))


def arrastrar(x0, y0, x1, y1, pasos=24, cancelar=None):
    """Presiona en (x0, y0), se mueve poco a poco (eventos de 'arrastrar') y suelta en (x1, y1). Pixeles."""
    s = _escala
    a = Q.CGPointMake(x0 / s, y0 / s)
    _mandar(Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, a, Q.kCGMouseButtonLeft))
    time.sleep(0.08)
    abajo = Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseDown, a, Q.kCGMouseButtonLeft)
    Q.CGEventSetIntegerValueField(abajo, Q.kCGMouseEventClickState, 1)
    _mandar(abajo)
    time.sleep(0.15)
    ultimo = a
    try:
        puntos = [(x0 + d, y0 + d // 3) for d in (3, 6, 9)]
        for i in range(1, pasos + 1):
            if cancelar and cancelar():
                break
            t = i / pasos
            t = t * t * (3 - 2 * t)
            puntos.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        puntos += [(x1, y1), (x1 + 1, y1), (x1, y1)]
        for (x, y) in puntos:
            ultimo = Q.CGPointMake(x / s, y / s)
            _mandar(Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseDragged, ultimo, Q.kCGMouseButtonLeft))
            time.sleep(0.016)
        time.sleep(0.12)
    finally:
        arriba = Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseUp, ultimo, Q.kCGMouseButtonLeft)
        Q.CGEventSetIntegerValueField(arriba, Q.kCGMouseEventClickState, 1)
        _mandar(arriba)


def trozos(texto):
    """Cada caracter por separado (un emoji o una letra con acento combinado van juntos en UTF-16)."""
    out = []
    for ch in texto:
        out.append(ch)
    return out


def _largo16(t):
    return len(t.encode("utf-16-le")) // 2


def eventos_texto(texto):
    return [(c, _largo16(c)) for c in trozos(texto)]


def escribir(texto, cancelar=None):
    """Teclea el texto como caracteres Unicode (acentos, ñ, ¿ y √ salen bien con cualquier teclado).
    Si 'cancelar()' devuelve True (o se presiona Esc) se detiene."""
    enviados = 0
    for i, (c, n) in enumerate(eventos_texto(texto)):
        if i % 8 == 0 and ((cancelar and cancelar()) or tecla_abajo(VK_ESCAPE)):
            raise Cancelado()
        for abajo in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, 0, abajo)
            Q.CGEventKeyboardSetUnicodeString(ev, n, c)
            _mandar(ev)
        enviados += 1
        time.sleep(0.004 if i % 8 else 0.012)
    return enviados == len(trozos(texto))


__all__ = ["Cancelado", "tecla_abajo", "boton_izquierdo", "posicion_mouse", "ventana_raiz_en", "clic", "tecla",
           "arrastrar", "mover", "TECLAS",
           "eventos_texto", "seleccionar_todo", "escribir", "soltar_ctrl_si_hace_falta", "juego_en_pantalla_completa",
           "bajar_prioridad_hilo", "rect_ventana", "clase_ventana", "ventana_al_frente", "U32", "VK_LBUTTON",
           "VK_RBUTTON", "VK_CONTROL", "VK_ESCAPE", "VK_MENU", "VK_ATAJO"]
