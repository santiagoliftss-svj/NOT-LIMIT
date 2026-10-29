"""Mouse y teclado de Windows: clics, escribir texto y leer teclas."""

import ctypes
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
    U32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]

VK_LBUTTON, VK_RBUTTON, VK_CONTROL, VK_ESCAPE = 0x01, 0x02, 0x11, 0x1B
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


def ventana_raiz_en(x, y):
    try:
        h = U32.WindowFromPoint(_POINT(int(x), int(y)))
        return U32.GetAncestor(h, 2) if h else None   # GA_ROOT
    except Exception:
        return None


def clic(x, y):
    U32.SetCursorPos(int(round(x)), int(round(y)))
    time.sleep(0.05)
    U32.mouse_event(0x0002, 0, 0, 0, 0)  # izquierdo abajo
    time.sleep(0.03)
    U32.mouse_event(0x0004, 0, 0, 0, 0)  # izquierdo arriba


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


__all__ = ["Cancelado", "tecla_abajo", "boton_izquierdo", "posicion_mouse", "ventana_raiz_en", "clic",
           "eventos_texto", "seleccionar_todo", "escribir", "soltar_ctrl_si_hace_falta"]
