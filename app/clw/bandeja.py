"""Icono junto al reloj (bandeja de Windows): abrir, activar o detener, y salir.

Los botones del menu llegan en el hilo de la bandeja. Quien crea la Bandeja debe pasar funciones que solo
manden el trabajo al hilo de la ventana (Tk no se puede tocar desde otro hilo).
"""

import logging
import sys
import threading

log = logging.getLogger("clw")


class Bandeja:
    def __init__(self, imagenes, al_abrir, al_alternar, al_salir, esta_activo, titulo="NO LIMIT", icos=None):
        """imagenes: {"activo": PIL.Image, "apagado": PIL.Image}; icos: lo mismo pero rutas .ico (se ven nitidos)"""
        self.imagenes = imagenes
        self.icos = icos
        self.titulo = titulo
        self._esta_activo = esta_activo
        self._activo = None
        self._alerta = None
        self.icono = None
        self._hilo = None
        try:
            import pystray
        except Exception as ex:          # sin bandeja la app sigue funcionando (se minimiza normal)
            log.warning("sin icono junto al reloj: %s", ex)
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Abrir " + titulo, lambda icon, item: al_abrir(), default=True),
                pystray.MenuItem(lambda item: "Detener" if self._esta_activo() else "Activar",
                                 lambda icon, item: al_alternar()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", lambda icon, item: al_salir()),
            )
            self.icono = pystray.Icon("no_limit", imagenes["apagado"], titulo, menu)
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
                ruta = self.icos.get(self._cual()) or self.icos["apagado"]
                icono._icon_handle = win32.LoadImage(None, ruta, win32.IMAGE_ICON, cx, cy, win32.LR_LOADFROMFILE)
            except Exception:
                original()

        icono._assert_icon_handle = asegurar

    @property
    def disponible(self):
        return self.icono is not None and self._hilo is not None and self._hilo.is_alive()

    def _cual(self):
        if self._alerta and "alerta" in self.imagenes:
            return "alerta"
        return "activo" if self._activo else "apagado"

    def estado(self, activo, alerta=None):
        """Cambia el icono, el texto al pasar el mouse y el menu (Activar / Detener).
        'alerta' = texto corto de un problema: el icono lo marca sin mostrar nada en pantalla."""
        if not self.disponible or (activo == self._activo and alerta == self._alerta):
            return
        self._activo, self._alerta = activo, alerta
        try:
            self.icono.icon = self.imagenes[self._cual()]
            detalle = alerta if alerta else ("Activo" if activo else "Apagado")
            self.icono.title = f"{self.titulo} · {detalle}"[:120]
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
