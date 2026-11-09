"""Los dos permisos que pide macOS: Accesibilidad (dar clic, escribir y escuchar Option + clic) y Grabacion de
pantalla (leer la pregunta). Se dan una vez en Ajustes del Sistema > Privacidad y seguridad."""

import ctypes
import logging
import subprocess

log = logging.getLogger("clw")

ID_APP = "mx.nolimit.app"
SERVICIOS = {"accesibilidad": "Accessibility", "pantalla": "ScreenCapture"}
AJUSTES = {
    "accesibilidad": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "pantalla": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
}


def _lib(ruta):
    try:
        return ctypes.cdll.LoadLibrary(ruta)
    except OSError:
        return None


_AS = _lib("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
_CG = _lib("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
for _lib_, _nombres in ((_AS, ("AXIsProcessTrusted",)),
                        (_CG, ("CGPreflightScreenCaptureAccess", "CGRequestScreenCaptureAccess"))):
    for _n in _nombres:
        try:
            getattr(_lib_, _n).restype = ctypes.c_bool
        except Exception:
            pass


def accesibilidad(preguntar=False):
    if preguntar:
        try:
            import HIServices
            return bool(HIServices.AXIsProcessTrustedWithOptions({HIServices.kAXTrustedCheckOptionPrompt: True}))
        except Exception as ex:
            log.warning("permiso de accesibilidad: %s", ex)
    try:
        return bool(_AS.AXIsProcessTrusted())
    except Exception:
        return True


def pantalla(preguntar=False):
    try:
        if preguntar:
            return bool(_CG.CGRequestScreenCaptureAccess())
        return bool(_CG.CGPreflightScreenCaptureAccess())
    except Exception:
        return True


def estado():
    return {"accesibilidad": accesibilidad(), "pantalla": pantalla()}


def faltan():
    e = estado()
    return [k for k in ("accesibilidad", "pantalla") if not e[k]]


_limpiados = set()


def limpiar(cual):
    """Cada version nueva de la app (sin firma de Apple) es 'otra app' para macOS: el permiso viejo se queda
    prendido en la lista pero ya no sirve. Se borra para que la version nueva aparezca y se pueda activar.
    Solo una vez por vez que se abre la app (si ya lo dio y falta reiniciar, no se le borra)."""
    if cual in _limpiados:
        return
    _limpiados.add(cual)
    try:
        subprocess.run(["/usr/bin/tccutil", "reset", SERVICIOS[cual], ID_APP], capture_output=True, timeout=10)
    except Exception:
        pass


def pedir(cual):
    """Le pide el permiso a macOS (sale su ventanita la primera vez) y abre Ajustes en esa lista."""
    if not estado().get(cual, True):
        limpiar(cual)
    try:
        if cual == "accesibilidad":
            accesibilidad(preguntar=True)
        elif cual == "pantalla":
            pantalla(preguntar=True)
    except Exception:
        pass
    try:
        subprocess.Popen(["/usr/bin/open", AJUSTES[cual]])
    except Exception as ex:
        log.warning("no se pudo abrir Ajustes: %s", ex)
