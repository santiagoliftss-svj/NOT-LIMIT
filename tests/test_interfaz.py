"""Pruebas de la interfaz sin ventana (se dibuja con PIL). Con CLW_CAPTURAS=carpeta guarda cada pantalla."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from clw import config  # noqa: E402
from clw.proveedores import ErrorIA  # noqa: E402
from clw.ui import vistas  # noqa: E402
from clw.ui.vistas import Interfaz  # noqa: E402

SALIDA = os.environ.get("CLW_CAPTURAS")


class Reloj:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


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
    reloj = Reloj()
    ui = Interfaz(c, app, escala, reloj=reloj)
    app.ui = ui
    ui.render()
    return ui, app, c, reloj


def _pasar(ui, reloj, seg):
    """Avanza el reloj dibujando cuadro por cuadro (como la ventana)."""
    fin = reloj.t + seg
    while reloj.t < fin:
        reloj.t = min(fin, reloj.t + 1 / 30)
        ui.render()


def _guardar(ui, nombre):
    im = ui.render()
    assert im.size == (ui.ancho_px, ui.alto_px)
    if SALIDA:
        os.makedirs(SALIDA, exist_ok=True)
        im.convert("RGB").save(os.path.join(SALIDA, nombre + ".png"))
    return im


def _clic(ui, zid):
    ui.render()                      # zonas al dia (la ventana redibuja despues de cada evento)
    for z, (x, y, w, h), _ in reversed(ui.zonas):
        if z == zid:
            cx, cy = x + w / 2, y + h / 2
            ui.mover(cx, cy)
            ui.presionar(cx, cy)
            ui.soltar(cx, cy)
            ui.render()
            return
    raise AssertionError(f"no hay zona {zid}: {[z[0] for z in ui.zonas]}")


def prueba_flujo_completo():
    ui, app, c, reloj = _nuevo(1.5)
    _guardar(ui, "01_inicio")
    # sin clave: INYECTAR lleva a pedir la clave
    _clic(ui, "inyectar")
    assert ui.pantalla == "clave" and ui.clave["iniciar"] and "iniciar" not in app.log
    _pasar(ui, reloj, 0.4)
    _guardar(ui, "02_clave_vacia")
    _clic(ui, "pegar")
    assert ui.clave["texto"].startswith("sk-ant-")
    _guardar(ui, "03_clave_pegada")
    _clic(ui, "guardar_clave")
    assert ui.clave["verificando"] and app.log[-1][0] == "verificar"
    _guardar(ui, "04_revisando")
    ui.clave_verificada("claude", ui.clave["texto"], None)
    assert ui.pantalla == "principal" and c.tiene_clave("claude") and "iniciar" in app.log
    assert ui.estado == "activo"
    # la animacion de INYECTAR termina y la ventana pide irse junto al reloj (una sola vez)
    assert not ui.debe_esconder()
    _pasar(ui, reloj, 1.2)
    assert ui.debe_esconder() and not ui.debe_esconder()
    ui.evento_bot(("actividad", "Marcó: Canberra", "ok"))
    ui.evento_bot(("actividad", "Escribió 3 respuestas", "ok"))
    ui.evento_bot(("actividad", "Tu cuenta de Claude no tiene saldo.", "error"))
    _pasar(ui, reloj, 0.5)
    _guardar(ui, "05_activo")
    ui.evento_bot(("estado", "pensando"))
    _pasar(ui, reloj, 0.3)
    _guardar(ui, "07_pensando")
    ui.evento_bot(("estado", "activo"))
    _clic(ui, "inyectar")
    assert ui.estado == "apagado" and app.log[-1] == "detener"
    _pasar(ui, reloj, 0.5)
    assert not ui.debe_esconder()


def prueba_inyectar_anima_y_esconde():
    ui, app, c, reloj = _nuevo(2.0)
    c.poner_clave("claude", "sk-ant-x")
    ui.render()
    _clic(ui, "inyectar")
    assert app.log == ["iniciar"] and ui.estado == "activo"
    assert ui.ritmo() == 16, "durante la animacion dibuja rapido"
    cuadros = []
    for i in range(36):
        reloj.t += 1 / 30
        cuadros.append(ui.render())
        if i in (4, 12, 20):
            _guardar(ui, f"17_encendiendo_{i}")
        if reloj.t - 100 < 1.0:
            assert not ui.debe_esconder()
    assert len({id(x) for x in cuadros}) > 20, "cada cuadro de la animacion es distinto"
    assert ui.debe_esconder()
    # ya escondida no dibuja ni pide cuadros
    ui.visible = False
    assert ui.ritmo() is None and not ui.animando()


def prueba_detener_rapido_no_esconde():
    ui, app, c, reloj = _nuevo(1.0)
    c.poner_clave("claude", "sk-ant-x")
    ui.render()
    _clic(ui, "inyectar")
    _pasar(ui, reloj, 0.3)
    _clic(ui, "inyectar")
    assert app.log == ["iniciar", "detener"] and ui.estado == "apagado"
    _pasar(ui, reloj, 1.5)
    assert not ui.debe_esconder()


def prueba_clave_mala_y_de_otro():
    ui, app, c, reloj = _nuevo(1.25)
    ui.abrir_clave("claude")
    ui.render()
    for ch in "AIzaSyBoguskey":
        ui.tecla(ch, ch)
    ui.guardar_clave()
    assert ui.clave["tipo"] == "error" and "Gemini" in ui.clave["msg"]
    _pasar(ui, reloj, 0.4)
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
    ui, app, c, reloj = _nuevo(1.0)
    c.poner_clave("claude", "sk-ant-x")
    ui.render()
    _clic(ui, "modelo")
    assert ui.capa == "modelos"
    ui.mover(190, 300)
    _pasar(ui, reloj, 0.3)
    _guardar(ui, "10_modelos")
    _clic(ui, "modelo:gemini-flash-latest")
    assert c["modelo"] == "gemini-flash-latest" and ui.capa is None
    _guardar(ui, "11_gemini_sin_clave")
    _clic(ui, "agregar_clave")
    assert ui.pantalla == "clave" and ui.clave["prov"] == "gemini"
    _pasar(ui, reloj, 0.3)
    _guardar(ui, "12_clave_gemini")
    # cerrar la capa tocando afuera
    ui.pantalla = "principal"
    ui.render()
    _clic(ui, "modelo")
    ui.mover(5, 5)
    ui.presionar(5, 5)
    ui.soltar(5, 5)
    assert ui.capa is None
    # y con Escape
    _clic(ui, "modelo")
    assert ui.tecla("", "Escape") and ui.capa is None


def prueba_ajustes():
    ui, app, c, reloj = _nuevo(2.0)
    c.poner_clave("claude", "sk-ant-x")
    ui.render()
    _clic(ui, "ajustes")
    assert ui.pantalla == "ajustes"
    _pasar(ui, reloj, 0.4)
    _guardar(ui, "13_ajustes")
    assert c["modo_preciso"] is True          # viene prendido de fabrica
    _clic(ui, "preciso")
    assert c["modo_preciso"] is False
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
    ui, app, c, reloj = _nuevo(1.0)
    # pantalla principal con la ventana al frente: la estrella da vueltas
    assert ui.animando() and ui.ritmo() == 40
    a = ui.render()
    reloj.t += 0.05
    b = ui.render()
    assert a is not b
    # sin foco no se mueve nada y se reusa la misma imagen
    ui.enfocado = False
    reloj.t += 0.05
    a = ui.render()
    reloj.t += 1.0
    b = ui.render()
    assert a is b and ui.ritmo() is None
    # una transicion de pantalla si se anima aunque no tenga foco, y luego se queda quieta
    _clic(ui, "ajustes")
    assert ui.ritmo() == 16
    _pasar(ui, reloj, vistas.T_TRANSICION + 0.05)
    assert ui.ritmo() is None
    x = ui.render()
    reloj.t += 0.2
    assert ui.render() is x
    ui.tecla("", "Escape")
    _pasar(ui, reloj, 0.4)
    ui.evento_bot(("nueva_version", "1.2.0"))
    _guardar(ui, "15_actualizacion")
    _clic(ui, "actualizar")
    assert app.log[-1][0] == "url"


def prueba_estrella_no_salta_al_perder_foco():
    ui, app, c, reloj = _nuevo(1.0)
    _pasar(ui, reloj, 1.0)
    antes = ui._grados
    ui.enfocado = False
    _pasar(ui, reloj, 5.0)
    assert ui._grados == antes, "sin foco la estrella se queda donde iba"
    ui.enfocado = True
    _pasar(ui, reloj, 0.1)
    avance = (ui._grados - antes) % 360
    assert 0 < avance < 10, avance


def prueba_cambiar_modelo_activo_sin_clave_detiene():
    ui, app, c, reloj = _nuevo(1.0)
    c.poner_clave("claude", "sk-ant-x")
    ui.render()
    _clic(ui, "inyectar")
    assert ui.estado == "activo"
    _clic(ui, "modelo")
    _clic(ui, "modelo:gpt-6-luna")
    assert app.log[-1] == "detener" and ui.estado == "apagado"


def prueba_atajo_gemini():
    ui, app, c, reloj = _nuevo(1.0)
    _clic(ui, "inyectar")
    assert ui.pantalla == "clave" and ui.clave["prov"] == "claude"
    _pasar(ui, reloj, 0.4)
    _guardar(ui, "16_clave_con_atajo")
    _clic(ui, "usar_gemini")
    assert c["modelo"] == "gemini-flash-latest" and ui.pantalla == "clave" and ui.clave["prov"] == "gemini"
    assert ui.clave["iniciar"] is True
    assert not any(z[0] == "usar_gemini" for z in ui.zonas)


def prueba_todas_las_escalas():
    """Cada pantalla se dibuja bien con cualquier zoom de Windows (sin piezas fuera del lienzo)."""
    for escala in (0.8, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5):
        ui, app, c, reloj = _nuevo(escala)
        c.poner_clave("claude", "sk-ant-x")
        for i in range(0, 360, 30):          # la estrella en todo el halo
            ui._grados = i
            ui.render()
        _clic(ui, "inyectar")
        _pasar(ui, reloj, 1.3)
        ui.evento_bot(("actividad", "Marcó: " + "una respuesta muy larga " * 6, "ok"))
        _pasar(ui, reloj, 0.5)
        _clic(ui, "modelo")
        _pasar(ui, reloj, 0.3)
        ui.tecla("", "Escape")
        _clic(ui, "ajustes")
        _pasar(ui, reloj, 0.3)
        _clic(ui, "clave:gemini")
        for ch in "AIzaSy" + "x" * 60:
            ui.tecla(ch, ch)
        _pasar(ui, reloj, 0.3)
        im = ui.render()
        assert im.size == (round(380 * escala), round(600 * escala))
