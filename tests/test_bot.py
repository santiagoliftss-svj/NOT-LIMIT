import json
import os
import queue
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from clw import config, motor, muestras  # noqa: E402
from clw.bot import Bot  # noqa: E402
from clw.ocr import OCR  # noqa: E402
from clw.proveedores import ErrorIA  # noqa: E402


class Acciones:
    VK_ESCAPE = 0x1B
    Cancelado = type("Cancelado", (Exception,), {})

    def __init__(self):
        self.log = []

    def tecla_abajo(self, vk):
        return False

    def clic(self, x, y):
        self.log.append(("clic", round(x), round(y)))

    def seleccionar_todo(self):
        self.log.append(("ctrl+a",))

    def escribir(self, texto, cancelar=None):
        self.log.append(("escribe", texto))
        return True


class Cliente:
    def __init__(self, fn):
        self.fn = fn
        self.pedidos = []

    def preguntar(self, prov, modelo, clave, sistema, b64, mime, texto, preciso=False):
        self.pedidos.append((prov, modelo, clave, preciso))
        return self.fn(texto)


def _bot(fn, con_clave=True):
    d = tempfile.mkdtemp()
    os.environ["CLW_DATOS"] = d
    c = config.Config(os.path.join(d, "a.json"))
    if con_clave:
        c.poner_clave("claude", "sk-ant-x")
    acc = Acciones()
    cli = Cliente(fn)
    b = Bot(c, queue.Queue(), ocr=OCR(), cliente=cli, acciones=acc)
    return b, c, acc, cli


def _eventos(b):
    out = []
    while True:
        try:
            out.append(b.eventos.get_nowait())
        except queue.Empty:
            return out


def _esperar(b):
    for _ in range(300):
        if not b._ocupado.locked():
            return
        time.sleep(0.05)
    raise AssertionError("el trabajo no termino")


def prueba_bot_contesta_opcion():
    img, tarjetas, (px, py) = muestras.quiz_oscuro()
    OFF = (100, 50)
    motor_capturar = motor.capturar
    motor.capturar = lambda x, y: (img, OFF[0], OFF[1])
    try:
        def ia(texto):
            for l in texto.splitlines():
                if "París" in l and l.startswith("["):
                    return json.dumps({"tipo": "opcion", "ids": [int(l[1:l.index("]")])]}), False
            raise AssertionError(texto)

        b, c, acc, cli = _bot(ia)
        assert b.iniciar()
        b._disparo(OFF[0] + px, OFF[1] + py)
        b._disparo(OFF[0] + px, OFF[1] + py)   # segundo disparo mientras trabaja: se ignora
        _esperar(b)
        ev = _eventos(b)
        assert ("estado", "activo") in ev and ("estado", "leyendo") in ev and ("estado", "pensando") in ev, ev
        assert any(e[0] == "actividad" and e[1].startswith("Marcó") for e in ev), ev
        assert any(e[0] == "actividad" and "Espera" in e[1] for e in ev), ev
        x, y = acc.log[0][1] - OFF[0], acc.log[0][2] - OFF[1]
        t = tarjetas["París"]
        assert t[0] <= x <= t[2] and t[1] <= y <= t[3], acc.log
        assert cli.pedidos[0][:3] == ("claude", "claude-haiku-5-5", "sk-ant-x")
        assert os.path.exists(os.path.join(os.environ["CLW_DATOS"], "revision", "ultima_revision.png"))
        b.detener()
    finally:
        motor.capturar = motor_capturar


def prueba_bot_sin_clave_pide_clave():
    b, c, acc, cli = _bot(lambda t: ("{}", False), con_clave=False)
    assert not b.iniciar()
    assert ("falta_clave", "claude") in _eventos(b)


def prueba_bot_error_de_clave():
    img, _, (px, py) = muestras.quiz_oscuro()
    motor_capturar = motor.capturar
    motor.capturar = lambda x, y: (img, 0, 0)
    try:
        def ia(texto):
            raise ErrorIA("Tu clave de Claude no sirve. Revisa que esté completa.", "clave")
        b, c, acc, cli = _bot(ia)
        b.iniciar()
        b._disparo(px, py)
        _esperar(b)
        ev = _eventos(b)
        assert ("falta_clave", "claude") in ev and any(e[0] == "actividad" and e[2] == "error" for e in ev), ev
        assert acc.log == []
    finally:
        motor.capturar = motor_capturar


def prueba_modelo_propio():
    b, c, acc, cli = _bot(lambda t: ("{}", False))
    c["modelos_propios"] = {"claude-haiku-5-5": "claude-haiku-9"}
    m, real = b.modelo()
    assert m.id == "claude-haiku-5-5" and real == "claude-haiku-9"


def prueba_esc_mientras_piensa_cancela_sin_clic():
    acc_esc = {"desde": None}

    def ia(texto):
        acc_esc["desde"] = time.time()          # el usuario presiona Esc mientras la IA piensa
        time.sleep(0.4)
        return json.dumps({"tipo": "opcion", "ids": [0]}), False
    b, c, acc, cli = _bot(ia)
    acc.tecla_abajo = lambda vk: vk == 0x1B and acc_esc["desde"] is not None and time.time() - acc_esc["desde"] < 0.3
    img, _, (qx, qy) = muestras.quiz_oscuro()
    motor_capturar = motor.capturar
    motor.capturar = lambda x, y: (img, 0, 0)
    try:
        assert b.iniciar()
        b._disparo(qx, qy)
        _esperar(b)
    finally:
        motor.capturar = motor_capturar
        b.detener()
    evs = _eventos(b)
    assert not any(a[0] == "clic" for a in acc.log), acc.log
    assert ("actividad", "Cancelado", "info") in evs, evs
