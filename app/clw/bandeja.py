"""Icono junto al reloj (bandeja de Windows): abrir, activar o detener, y salir.

Los botones del menu llegan en el hilo de la bandeja. Quien crea la Bandeja debe pasar funciones que solo
manden el trabajo al hilo de la ventana (Tk no se puede tocar desde otro hilo).
"""

import logging
import sys
import threading

log = logging.getLogger("clw")


class Bandeja:
    def __init__(self, imagenes, al_abrir, al_alternar, al_salir, esta_activo, titulo="CLW GANG", icos=None):
        """imagenes: {"activo": PIL.Image, "apagado": PIL.Image}; icos: lo mismo pero rutas .ico (se ven nitidos)"""
        self.imagenes = imagenes
        self.icos = icos
        self.titulo = titulo
        self._esta_activo = esta_activo
        self._activo = None
        self.icono = None
        self._hilo = None
        try:
            import pystray
        except Exception as ex:          # sin bandeja la app sigue funcionando (se minimiza normal)
            log.warning("sin icono junto al reloj: %s", ex)
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Abrir CLW GANG", lambda icon, item: al_abrir(), default=True),
                pystray.MenuItem(lambda item: "Detener" if self._esta_activo() else "Activar",
                                 lambda icon, item: al_alternar()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", lambda icon, item: al_salir()),
            )
            self.icono = pystray.Icon("clw_gang", imagenes["apagado"], titulo, menu)
            if sys.platform == "win32" and icos:
                self._icono_nitido()
            self._hilo = threading.Thread(target=self.icono.run, name="bandeja", daemon=True)
            self._hilo.start()
        except Exception as ex:
            log.warning("sin icono junto al reloj: %s", ex)
            self.icono = None

    def _icono_nitido(self):
        """pystray carga el icono a 32 px y Windows lo encoge (se ve borroso). Aqui se carga el .ico
        al tamano exacto de la bandeja."""
        import ctypes
        from pystray._util import win32

        icono = self.icono
        original = icono._assert_icon_handle

        def asegurar():
            if icono._icon_handle:
                return
            try:
                u32 = ctypes.windll.user32
                cx, cy = u32.GetSystemMetrics(49), u32.GetSystemMetrics(50)   # SM_CXSMICON, SM_CYSMICON
                ruta = self.icos["activo" if self._activo else "apagado"]
                icono._icon_handle = win32.LoadImage(None, ruta, win32.IMAGE_ICON, cx, cy, win32.LR_LOADFROMFILE)
            except Exception:
                original()

        icono._assert_icon_handle = asegurar

    @property
    def disponible(self):
        return self.icono is not None and self._hilo is not None and self._hilo.is_alive()

    def estado(self, activo):
        """Cambia el icono, el texto al pasar el mouse y el menu (Activar / Detener)."""
        if not self.disponible or activo == self._activo:
            return
        self._activo = activo
        try:
            self.icono.icon = self.imagenes["activo" if activo else "apagado"]
            self.icono.title = f"{self.titulo} · {'Activo' if activo else 'Apagado'}"
            self.icono.update_menu()
        except Exception as ex:
            log.warning("bandeja estado: %s", ex)

    def avisar(self, texto, titulo=None):
        if not self.disponible:
            return
        try:
            self.icono.notify(texto, titulo or self.titulo)
        except Exception as ex:
            log.warning("bandeja aviso: %s", ex)

    def cerrar(self):
        if self.icono is None:
            return
        try:
            self.icono.stop()
        except Exception:
            pass
        if self._hilo is not None:
            self._hilo.join(timeout=2)
        self.icono = None
