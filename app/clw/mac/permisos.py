"""Los dos permisos que pide macOS: Accesibilidad (dar clic, escribir y escuchar Option + clic) y Grabacion de
pantalla (leer la pregunta). Se dan una vez en Ajustes del Sistema > Privacidad y seguridad."""

import ctypes
import logging
import subprocess

log = logging.getLogger("clw")

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


def pedir(cual):
    """Le pide el permiso a macOS (sale su ventanita la primera vez) y abre Ajustes en esa lista."""
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
