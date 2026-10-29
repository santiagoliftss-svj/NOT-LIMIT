"""CLW GANG - punto de entrada."""

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
    """Evita dos copias abiertas (contestarian doble). Si ya hay una, la trae al frente."""
    try:
        k32 = ctypes.windll.kernel32
        _ya_abierta.mutex = k32.CreateMutexW(None, False, "CLWGANG_unica")
        if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            u32 = ctypes.windll.user32
            h = u32.FindWindowW(None, "CLW GANG")
            if h:
                u32.ShowWindow(h, 9)
                u32.SetForegroundWindow(h)
            return True
    except Exception:
        pass
    return False


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
    sys.exit(main())
