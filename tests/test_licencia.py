"""Licencia: sin codigo pagado NO LIMIT no arranca."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from clw import config, licencia  # noqa: E402
from clw.ui.vistas import Interfaz  # noqa: E402

CODIGO = "NL-7K2Q-M9XD-4TPA"


class _Sin:
    """Apaga el modo de prueba y deja solo CODIGO como valido."""
    def __enter__(self):
        self.antes = (licencia.PRUEBA, licencia.HUELLAS, licencia._cargado, dict(licencia._remoto))
        licencia.PRUEBA, licencia._cargado = False, True
        licencia.HUELLAS = frozenset({licencia.huella(CODIGO)})
        licencia._remoto.update(extra=set(), bloqueadas=set())
        return self

    def __exit__(self, *a):
        licencia.PRUEBA, licencia.HUELLAS, licencia._cargado = self.antes[:3]
        licencia._remoto.clear()
        licencia._remoto.update(self.antes[3])


class App:
    def __init__(self):
        self.log, self.ui, self.portapapeles = [], None, ""

    def iniciar(self):
        self.log.append("iniciar")
        self.ui.evento_bot(("estado", "activo"))

    def detener(self):
        self.log.append("detener")

    def verificar_clave(self, prov, texto):
        self.log.append(("verificar", prov))

    def leer_portapapeles(self):
        return self.portapapeles

    def abrir_url(self, url):
        self.log.append(("url", url))

    def abrir_carpeta(self):
        pass


def _ui():
    d = tempfile.mkdtemp()
    c = config.Config(os.path.join(d, "a.json"))
    app = App()
    ui = Interfaz(c, app, 1.0, reloj=lambda: 100.0)
    app.ui = ui
    ui.render()
    return ui, app, c


def prueba_codigos():
    with _Sin():
        assert licencia.valido(CODIGO)
        assert licencia.valido("nl 7k2q m9xd 4tpa")              # minusculas y espacios
        assert licencia.valido("NL-7K2Q-M9XD-4TPA ")
        assert not licencia.valido("NL-7K2Q-M9XD-4TPB")
        assert not licencia.valido("") and not licencia.valido("AIzaSyA1234567890")
        assert licencia.formatear("7k2qm9xd4tpa") == CODIGO
        assert licencia.parece_licencia(CODIGO) and not licencia.parece_licencia("sk-ant-api03-xx")
        # bloquear uno compartido desde la pagina y agregar uno nuevo sin sacar version
        nuevo = "NL-AAAA-BBBB-CCCC"
        licencia._aplicar({"bloqueadas": [licencia.huella(CODIGO)], "extra": [licencia.huella(nuevo)]})
        assert not licencia.valido(CODIGO) and licencia.valido(nuevo)


def prueba_sin_codigo_no_arranca():
    with _Sin():
        ui, app, c = _ui()
        c.poner_clave("claude", "sk-ant-api03-x")
        ui.inyectar()
        assert "iniciar" not in app.log
        assert ui.pantalla == "clave" and ui.clave["prov"] == "licencia", ui.pantalla
        ui.render()                                                # la pantalla del codigo se dibuja
        for ch in "NL-0000-0000-0000":
            ui.tecla(ch, ch)
        ui.tecla("", "Return")
        assert "no sirve" in ui.clave["msg"] and "iniciar" not in app.log
        ui.tecla("", "BackSpace", ctrl=True)
        app.portapapeles = CODIGO.lower()
        ui._accion("pegar")
        ui.tecla("", "Return")
        assert c.get("licencia") == CODIGO, c.get("licencia")
        assert "iniciar" in app.log, app.log                     # ya con codigo: arranca solo
        assert licencia.activa(c)


def prueba_codigo_primero_luego_clave():
    with _Sin():
        ui, app, c = _ui()
        ui.inyectar()
        assert ui.clave["prov"] == "licencia"
        app.portapapeles = CODIGO
        ui._accion("pegar")
        ui.guardar_clave()
        assert ui.pantalla == "clave" and ui.clave["prov"] != "licencia"   # ahora pide la clave de la IA
        app.portapapeles = CODIGO
        ui._accion("pegar")
        ui.guardar_clave()
        assert "código de NO LIMIT" in ui.clave["msg"]                    # pego el codigo donde va la clave
        ui._ir("ajustes")
        ui.render()
