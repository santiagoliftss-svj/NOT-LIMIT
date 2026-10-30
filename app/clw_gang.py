"""NO LIMIT (antes CLW GANG) - punto de entrada."""

import ctypes
import os
import sys


def _preparar_windows():
    # pixeles reales aunque Windows tenga zoom: asi cuadran captura, mouse y clics
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:  # icono propio en la barra de tareas
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CLWGANG.App")
    except Exception:
        pass


def _ya_abierta():
    """Evita dos copias abiertas (contestarian doble). Si ya hay una (aunque este escondida junto al reloj),
    le pide que se muestre."""
    try:
        k32 = ctypes.windll.kernel32
        _ya_abierta.mutex = k32.CreateMutexW(None, False, "CLWGANG_unica")
        if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            u32 = ctypes.windll.user32
            try:
                u32.AllowSetForegroundWindow(-1)   # ASFW_ANY: que la otra copia pueda ponerse al frente
            except Exception:
                pass
            k32.OpenEventW.restype = ctypes.c_void_p
            evento = k32.OpenEventW(0x0002, False, "CLWGANG_mostrar")   # EVENT_MODIFY_STATE
            if evento:
                k32.SetEvent(ctypes.c_void_p(evento))
                k32.CloseHandle(ctypes.c_void_p(evento))
            else:   # version vieja abierta
                h = u32.FindWindowW(None, "NO LIMIT") or u32.FindWindowW(None, "CLW GANG")
                if h:
                    u32.ShowWindow(h, 9)
                    u32.SetForegroundWindow(h)
            return True
    except Exception:
        pass
    return False


def _terminar(codigo):
    """Sale de verdad aunque algun hilo de Windows (icono del reloj) se haya quedado colgado."""
    try:
        import logging
        logging.shutdown()
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(codigo)


def main():
    _preparar_windows()
    if "--autoprueba" in sys.argv:
        from clw import autoprueba
        i = sys.argv.index("--autoprueba")
        salida = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(os.getcwd(), "autoprueba")
        return autoprueba.main(salida)

    if _ya_abierta():
        return 0

    from clw.bot import Bot, configurar_registro
    from clw.config import Config
    from clw.motor import factor_zoom
    from clw.ui.ventana import Ventana

    configurar_registro()
    config = Config()
    bot = Bot(config)
    ventana = Ventana(config, bot, factor_zoom())
    ventana.root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        _codigo = main() or 0
    except SystemExit as e:
        _codigo = e.code if isinstance(e.code, int) else 0
    except Exception:
        import logging
        import traceback
        traza = traceback.format_exc()
        logging.getLogger("clw").error("la app se cerro por un error:\n%s", traza)
        try:
            ctypes.windll.user32.MessageBoxW(None, "NO LIMIT se cerró por un error:\n\n" + traza[-800:],
                                             "NO LIMIT", 0x10)
        except Exception:
            print(traza, file=sys.stderr)
        _codigo = 1
    _terminar(_codigo)
