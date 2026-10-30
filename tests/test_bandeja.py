"""Icono del reloj (bandeja) con un pystray de mentiras: menu, estado, avisos y cierre."""

import os
import sys
import threading
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))


def _pystray_falso():
    mod = types.ModuleType("pystray")

    class MenuItem:
        def __init__(self, text, action, default=False, **k):
            self._text, self.action, self.default = text, action, default

        @property
        def text(self):
            return self._text(self) if callable(self._text) else self._text

    class Menu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class Icon:
        def __init__(self, name, icon=None, title=None, menu=None):
            self.name, self.icon, self.title, self.menu = name, icon, title, menu
            self.avisos, self.menus = [], 0
            self.parar = threading.Event()

        def run(self):
            self.parar.wait()

        def stop(self):
            self.parar.set()

        def notify(self, texto, titulo=None):
            self.avisos.append((texto, titulo))

        def update_menu(self):
            self.menus += 1

    mod.MenuItem, mod.Menu, mod.Icon = MenuItem, Menu, Icon
    return mod


def _con_modulo(mod, fn):
    viejo = sys.modules.get("pystray")
    sys.modules["pystray"] = mod
    try:
        fn()
    finally:
        if viejo is not None:
            sys.modules["pystray"] = viejo
        else:
            sys.modules.pop("pystray", None)


def prueba_menu_estado_avisos_y_cierre():
    def caso():
        from clw.bandeja import Bandeja
        llamadas, activo = [], [False]
        b = Bandeja({"activo": "A", "apagado": "B"}, lambda: llamadas.append("abrir"),
                    lambda: llamadas.append("alternar"), lambda: llamadas.append("salir"), lambda: activo[0])
        assert b.disponible and b.icono.icon == "B"
        items = b.icono.menu.items
        assert items[0].text == "Abrir CLW GANG" and items[0].default
        assert items[1].text == "Activar"
        activo[0] = True
        assert items[1].text == "Detener"
        b.estado(True)
        assert b.icono.icon == "A" and b.icono.title.endswith("Activo") and b.icono.menus == 1
        b.estado(True)                      # sin cambio no hace nada
        assert b.icono.menus == 1
        for i in (0, 1, 3):
            items[i].action(b.icono, items[i])
        assert llamadas == ["abrir", "alternar", "salir"]
        b.avisar("hola")
        assert b.icono.avisos == [("hola", "CLW GANG")]
        icono = b.icono
        b.cerrar()
        assert icono.parar.is_set() and not b.disponible
        b.avisar("ya cerrada")              # no truena
        b.estado(False)
    _con_modulo(_pystray_falso(), caso)


def prueba_sin_pystray_no_truena():
    def caso():
        from clw.bandeja import Bandeja
        b = Bandeja({"activo": "A", "apagado": "B"}, lambda: None, lambda: None, lambda: None, lambda: False)
        assert not b.disponible and b.icono is None
        b.estado(True)
        b.avisar("x")
        b.cerrar()
    _con_modulo(None, caso)                 # None en sys.modules = ImportError al importar
