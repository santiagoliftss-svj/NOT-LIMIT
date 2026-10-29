"""Pruebas de la interfaz sin ventana (se dibuja con PIL). Con CLW_CAPTURAS=carpeta guarda cada pantalla."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from clw import config  # noqa: E402
from clw.proveedores import ErrorIA  # noqa: E402
from clw.ui.vistas import BOTON, Interfaz  # noqa: E402

SALIDA = os.environ.get("CLW_CAPTURAS")


class AppFalsa:
    def __init__(self):
        self.log = []
        self.portapapeles = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-wxyz"
        self.ui = None

    def iniciar(self):
        self.log.append("iniciar")
        self.ui.evento_bot(("estado", "activo"))

    def detener(self):
        self.log.append("detener")
        self.ui.evento_bot(("estado", "apagado"))

    def verificar_clave(self, prov, texto):
        self.log.append(("verificar", prov, texto))

    def leer_portapapeles(self):
        return self.portapapeles

    def abrir_url(self, url):
        self.log.append(("url", url))

    def abrir_carpeta(self):
        self.log.append("carpeta")


def _nuevo(escala=1.0):
    d = tempfile.mkdtemp()
    c = config.Config(os.path.join(d, "a.json"))
    app = AppFalsa()
    ui = Interfaz(c, app, escala)
    app.ui = ui
    ui.render(0)
    return ui, app, c


def _guardar(ui, nombre, t=0.0):
    im = ui.render(t)
    assert im.size == (ui.ancho_px, ui.alto_px)
    if SALIDA:
        os.makedirs(SALIDA, exist_ok=True)
        im.convert("RGB").save(os.path.join(SALIDA, nombre + ".png"))
    return im


def _clic(ui, zid):
    for z, (x, y, w, h), _ in reversed(ui.zonas):
        if z == zid:
            cx, cy = x + w / 2, y + h / 2
            ui.mover(cx, cy)
            ui.presionar(cx, cy)
            ui.soltar(cx, cy)
            ui.render(0)
            return
    raise AssertionError(f"no hay zona {zid}: {[z[0] for z in ui.zonas]}")


def prueba_flujo_completo():
    ui, app, c = _nuevo(1.5)
    _guardar(ui, "01_inicio")
    # sin clave: INYECTAR lleva a pedir la clave
    _clic(ui, "inyectar")
    assert ui.pantalla == "clave" and ui.clave["iniciar"] and "iniciar" not in app.log
    _guardar(ui, "02_clave_vacia")
    _clic(ui, "pegar")
    assert ui.clave["texto"].startswith("sk-ant-")
    _guardar(ui, "03_clave_pegada")
    _clic(ui, "guardar_clave")
    assert ui.clave["verificando"] and app.log[-1][0] == "verificar"
    _guardar(ui, "04_revisando", 0.4)
    ui.clave_verificada("claude", ui.clave["texto"], None)
    assert ui.pantalla == "principal" and c.tiene_clave("claude") and "iniciar" in app.log
    assert ui.estado == "activo"
    ui.evento_bot(("actividad", "Marcó: París", "ok"))
    ui.evento_bot(("actividad", "Escribió 3 respuestas", "ok"))
    ui.evento_bot(("actividad", "Tu cuenta de Claude no tiene saldo.", "error"))
    _guardar(ui, "05_activo", 0.0)
    _guardar(ui, "06_activo_brillo", 0.65)
    ui.evento_bot(("estado", "pensando"))
    _guardar(ui, "07_pensando", 0.3)
    ui.evento_bot(("estado", "activo"))
    _clic(ui, "inyectar")
    assert ui.estado == "apagado" and app.log[-1] == "detener"


def prueba_clave_mala_y_de_otro():
    ui, app, c = _nuevo(1.25)
    ui.abrir_clave("claude")
    ui.render(0)
    for ch in "AIzaSyBoguskey":
        ui.tecla(ch, ch)
    ui.guardar_clave()
    assert ui.clave["tipo"] == "error" and "Gemini" in ui.clave["msg"]
    _guardar(ui, "08_clave_de_otro")
    ui.tecla("", "BackSpace", ctrl=True)
    assert ui.clave["texto"] == ""
    for ch in "sk-ant-mala":
        ui.tecla(ch, ch)
    ui.guardar_clave()
    ui.clave_verificada("claude", "sk-ant-mala", ErrorIA("Tu clave de Claude no sirve. Revisa que esté completa.", "clave"))
    assert ui.pantalla == "clave" and ui.clave["tipo"] == "error" and not c.tiene_clave("claude")
    _guardar(ui, "09_clave_mala")
    ui.tecla("", "Escape")
    assert ui.pantalla == "principal"


def prueba_selector_modelos():
    ui, app, c = _nuevo(1.0)
    c.poner_clave("claude", "sk-ant-x")
    ui.render(0)
    _clic(ui, "modelo")
    assert ui.capa == "modelos"
    ui.mover(190, 300)
    _guardar(ui, "10_modelos")
    _clic(ui, "modelo:gemini-flash-latest")
    assert c["modelo"] == "gemini-flash-latest" and ui.capa is None
    _guardar(ui, "11_gemini_sin_clave")
    _clic(ui, "agregar_clave")
    assert ui.pantalla == "clave" and ui.clave["prov"] == "gemini"
    _guardar(ui, "12_clave_gemini")
    # cerrar la capa tocando afuera
    ui.pantalla = "principal"
    ui.render(0)
    _clic(ui, "modelo")
    ui.mover(5, 5)
    ui.presionar(5, 5)
    ui.soltar(5, 5)
    assert ui.capa is None


def prueba_ajustes():
    ui, app, c = _nuevo(2.0)
    c.poner_clave("claude", "sk-ant-x")
    ui.render(0)
    _clic(ui, "ajustes")
    assert ui.pantalla == "ajustes"
    _guardar(ui, "13_ajustes")
    _clic(ui, "preciso")
    assert c["modo_preciso"] is True
    _clic(ui, "capturas")
    assert c["guardar_capturas"] is False
    _guardar(ui, "14_ajustes_cambiados")
    _clic(ui, "carpeta")
    assert "carpeta" in app.log
    _clic(ui, "clave:openai")
    assert ui.pantalla == "clave" and ui.clave["volver"] == "ajustes"
    _clic(ui, "cancelar_clave")
    assert ui.pantalla == "ajustes"
    _clic(ui, "volver")
    assert ui.pantalla == "principal"


def prueba_cache_y_animacion():
    ui, app, c = _nuevo(1.0)
    a = ui.render(0)
    b = ui.render(0.1)
    assert a is b, "sin cambios debe reusar la imagen"
    ui.evento_bot(("estado", "activo"))
    x = ui.render(0.0)
    y = ui.render(0.6)
    assert x is not y and ui.animando()
    ui.evento_bot(("nueva_version", "1.1.0"))
    _guardar(ui, "15_actualizacion")
    _clic(ui, "actualizar")
    assert app.log[-1][0] == "url"


def prueba_cambiar_modelo_activo_sin_clave_detiene():
    ui, app, c = _nuevo(1.0)
    c.poner_clave("claude", "sk-ant-x")
    ui.render(0)
    _clic(ui, "inyectar")
    assert ui.estado == "activo"
    _clic(ui, "modelo")
    _clic(ui, "modelo:gpt-6-luna")
    assert app.log[-1] == "detener" and ui.estado == "apagado"
