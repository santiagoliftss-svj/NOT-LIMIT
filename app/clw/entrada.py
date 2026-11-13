"""Mouse y teclado de Windows: clics, escribir texto y leer teclas."""

import ctypes
import sys
import time


def _user32():
    try:
        return ctypes.windll.user32
    except Exception:
        return None


U32 = _user32()


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _UNION_INPUT(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _UNION_INPUT)]


if U32 is not None:
    U32.GetAsyncKeyState.restype = ctypes.c_short
    U32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    U32.WindowFromPoint.argtypes = [_POINT]
    U32.WindowFromPoint.restype = ctypes.c_void_p
    U32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    U32.GetAncestor.restype = ctypes.c_void_p
    U32.GetForegroundWindow.restype = ctypes.c_void_p
    U32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]

VK_LBUTTON, VK_RBUTTON, VK_CONTROL, VK_ESCAPE = 0x01, 0x02, 0x11, 0x1B
VK_ATAJO = VK_CONTROL      # la tecla que va con el clic (en Mac es Option)
_TECLA_ARRIBA = 0x0002
_UNICODE = 0x0004


class Cancelado(Exception):
    pass


def tecla_abajo(vk):
    if U32 is None:
        return False
    try:
        return bool(U32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def boton_izquierdo():
    """El boton 'principal' fisico (respeta si el mouse esta configurado para zurdos)."""
    try:
        return VK_RBUTTON if U32.GetSystemMetrics(23) else VK_LBUTTON
    except Exception:
        return VK_LBUTTON


def posicion_mouse():
    p = _POINT()
    U32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def ventana_al_frente():
    try:
        return U32.GetForegroundWindow()
    except Exception:
        return None


def ventana_raiz_en(x, y):
    try:
        h = U32.WindowFromPoint(_POINT(int(x), int(y)))
        return U32.GetAncestor(h, 2) if h else None   # GA_ROOT
    except Exception:
        return None


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def rect_ventana(hwnd):
    """(x0, y0, x1, y1) de una ventana visible, o None si esta oculta o minimizada."""
    try:
        h = ctypes.c_void_p(hwnd)
        if not U32.IsWindowVisible(h) or U32.IsIconic(h):
            return None
        r = _RECT()
        try:
            if ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
        if U32.GetWindowRect(h, ctypes.byref(r)):
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return None


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


# ventanas de navegador: aunque esten en pantalla completa (F11) si se contestan
_NAVEGADORES = ("Chrome_WidgetWin_1", "MozillaWindowClass", "ApplicationFrameWindow", "OperaWindowClass")
_ESCRITORIO = ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")


def clase_ventana(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    try:
        U32.GetClassNameW(ctypes.c_void_p(hwnd), buf, 256)
    except Exception:
        return ""
    return buf.value


def juego_en_pantalla_completa():
    """True si al frente hay una app en pantalla completa que no es navegador (casi siempre un juego)."""
    try:
        h = U32.GetForegroundWindow()
        if not h:
            return False
        clase = clase_ventana(h)
        if clase in _ESCRITORIO or clase in _NAVEGADORES:
            return False
        U32.GetWindowLongW.restype = ctypes.c_long
        estilo = U32.GetWindowLongW(ctypes.c_void_p(h), -16) & 0xFFFFFFFF   # GWL_STYLE
        if estilo & 0x00C00000 == 0x00C00000:   # tiene barra de titulo: es una ventana maximizada, no un juego
            return False
        r = _RECT()
        if not U32.GetWindowRect(ctypes.c_void_p(h), ctypes.byref(r)):
            return False
        U32.MonitorFromWindow.restype = ctypes.c_void_p
        mon = U32.MonitorFromWindow(ctypes.c_void_p(h), 2)
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not U32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    except Exception:
        return False


def bajar_prioridad_hilo():
    """El hilo actual corre con prioridad baja (para no robarle fuerza a un juego)."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentThread.restype = ctypes.c_void_p
        k32.SetThreadPriority(ctypes.c_void_p(k32.GetCurrentThread()), -1)   # BELOW_NORMAL
    except Exception:
        pass


def clic(x, y):
    U32.SetCursorPos(int(round(x)), int(round(y)))
    time.sleep(0.05)
    U32.mouse_event(0x0002, 0, 0, 0, 0)  # izquierdo abajo
    time.sleep(0.03)
    U32.mouse_event(0x0004, 0, 0, 0, 0)  # izquierdo arriba


# teclas especiales que se pueden mandar (editores de ecuaciones, menus)
TECLAS = {"derecha": 0x27, "izquierda": 0x25, "arriba": 0x26, "abajo": 0x28, "retroceso": 0x08, "escape": 0x1B,
          "enter": 0x0D}
_EXTENDIDA = 0x0001
_FLECHAS = (0x25, 0x26, 0x27, 0x28)


def tecla(nombre, veces=1):
    """Presiona una tecla especial (derecha, izquierda, arriba, abajo, retroceso, escape, enter)."""
    vk = TECLAS[nombre]
    ext = _EXTENDIDA if vk in _FLECHAS else 0
    for _ in range(max(1, int(veces))):
        _enviar([(vk, 0, ext), (vk, 0, ext | _TECLA_ARRIBA)])
        time.sleep(0.03)


def _virtual():
    try:
        x, y = U32.GetSystemMetrics(76), U32.GetSystemMetrics(77)
        w, h = U32.GetSystemMetrics(78), U32.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return x, y, w, h
    except Exception:
        pass
    return 0, 0, 1920, 1080


def _mover_abs(x, y):
    """Mueve el mouse con un evento de 'movimiento' de verdad (las paginas web lo necesitan para arrastrar)."""
    vx, vy, vw, vh = _virtual()
    dx = int(round((x - vx) * 65535 / max(1, vw - 1)))
    dy = int(round((y - vy) * 65535 / max(1, vh - 1)))
    ev = (_INPUT * 1)()
    ev[0].type = 0
    ev[0].u.mi = _MOUSEINPUT(dx, dy, 0, 0x0001 | 0x8000 | 0x4000, 0, 0)   # MOVE | ABSOLUTE | VIRTUALDESK
    U32.SendInput(1, ev, ctypes.sizeof(_INPUT))


def arrastrar(x0, y0, x1, y1, pasos=24, cancelar=None):
    """Presiona en (x0, y0), se mueve poco a poco y suelta en (x1, y1)."""
    x0, y0, x1, y1 = (int(round(v)) for v in (x0, y0, x1, y1))
    U32.SetCursorPos(x0, y0)
    _mover_abs(x0, y0)
    time.sleep(0.08)
    U32.mouse_event(0x0002, 0, 0, 0, 0)          # izquierdo abajo
    time.sleep(0.15)
    try:
        for dx in (3, 6, 9):                        # primero poquito: asi la pagina sabe que empieza a arrastrar
            _mover_abs(x0 + dx, y0 + dx // 3)
            time.sleep(0.03)
        for i in range(1, pasos + 1):
            if cancelar and cancelar():
                break
            t = i / pasos
            t = t * t * (3 - 2 * t)                 # arranca y frena suave
            _mover_abs(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            time.sleep(0.016)
        _mover_abs(x1, y1)
        time.sleep(0.12)
        _mover_abs(x1 + 1, y1)
        time.sleep(0.06)
        _mover_abs(x1, y1)
        time.sleep(0.1)
    finally:
        U32.mouse_event(0x0004, 0, 0, 0, 0)       # izquierdo arriba


def eventos_texto(texto):
    """Cada letra como caracter Unicode: acentos, ñ, ¿ y √ salen bien con cualquier teclado."""
    eventos = []
    datos = texto.encode("utf-16-le")
    for i in range(0, len(datos), 2):
        unidad = datos[i] | (datos[i + 1] << 8)
        eventos.append((0, unidad, _UNICODE))
        eventos.append((0, unidad, _UNICODE | _TECLA_ARRIBA))
    return eventos


def _enviar(eventos):
    arreglo = (_INPUT * len(eventos))()
    for i, (vk, scan, flags) in enumerate(eventos):
        arreglo[i].type = 1
        arreglo[i].u.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    return U32.SendInput(len(eventos), arreglo, ctypes.sizeof(_INPUT))


def seleccionar_todo():
    _enviar([(VK_CONTROL, 0, 0), (0x41, 0, 0), (0x41, 0, _TECLA_ARRIBA), (VK_CONTROL, 0, _TECLA_ARRIBA)])


def soltar_ctrl_si_hace_falta():
    """Si quedo Ctrl 'pegado' en el estado del sistema, lo suelta."""
    if tecla_abajo(VK_CONTROL):
        _enviar([(VK_CONTROL, 0, _TECLA_ARRIBA)])


def escribir(texto, cancelar=None):
    """Teclea el texto. Si 'cancelar()' devuelve True (o se presiona Esc) se detiene."""
    eventos = eventos_texto(texto)
    enviados = 0
    for i in range(0, len(eventos), 40):
        if (cancelar and cancelar()) or tecla_abajo(VK_ESCAPE):
            raise Cancelado()
        enviados += _enviar(eventos[i:i + 40])
        time.sleep(0.012)
    return enviados == len(eventos)


def tam_input():
    return ctypes.sizeof(_INPUT)


__all__ = ["Cancelado", "tecla_abajo", "boton_izquierdo", "posicion_mouse", "ventana_raiz_en", "clic", "tecla",
           "arrastrar", "TECLAS",
           "eventos_texto", "seleccionar_todo", "escribir", "soltar_ctrl_si_hace_falta", "juego_en_pantalla_completa",
           "bajar_prioridad_hilo", "rect_ventana", "clase_ventana", "ventana_al_frente"]

if sys.platform == "darwin":             # Mac: mismos nombres, hechos con Quartz
    from .mac.entrada import *  # noqa: F401,F403,E402
