"""Segunda opinion en preguntas de calcular: se resuelve dos veces y, si no da lo mismo, se desempata."""

import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "app"))

from clw import cerebro  # noqa: E402


def _escribe(*valores, calculo=None):
    d = {"tipo": "numerica", "respuesta": " | ".join(valores),
         "acciones": [{"hacer": "escribir", "en": f"C{i}", "texto": v} for i, v in enumerate(valores)]}
    if calculo:
        d["calculo"] = calculo
    return d


class _IA:
    def __init__(self, *salidas):
        self.salidas = list(salidas)
        self.textos = []

    def __call__(self, b64, mime, texto, fase="contestar", esfuerzo=None):
        self.textos.append(texto)
        return json.dumps(self.salidas.pop(0)), False


def prueba_mismo_valor_con_redondeo():
    assert cerebro._mismo_valor("41.1", "41.09")
    assert cerebro._mismo_valor("39", "39.0")
    assert cerebro._mismo_valor("53.6°", "53.6")
    assert not cerebro._mismo_valor("53.6", "126.4")
    assert not cerebro._mismo_valor("41.1", "41.3")
    assert cerebro._mismo_valor("x^2 + 3", "x^2+3")


def prueba_si_cuadran_no_se_desempata():
    primera = _escribe("39", "41.1", "34.6")
    ia = _IA(_escribe("39", "41.09", "34.65"))
    datos, nota = cerebro.segunda_opinion(ia, "", "image/png", "FASE: CONTESTAR\nAlgo", primera)
    assert nota == "cuadra", nota
    assert datos is primera
    assert len(ia.textos) == 1 and ia.textos[0].startswith("FASE: COMPROBAR"), ia.textos


def prueba_si_no_cuadran_gana_el_desempate():
    primera = _escribe("126.4")
    segunda = _escribe("53.6")
    ia = _IA(segunda, _escribe("53.6"))
    datos, nota = cerebro.segunda_opinion(ia, "", "image/png", "FASE: CONTESTAR\nAngulo", primera)
    assert nota == "desempate: se queda la segunda", nota
    assert cerebro.valores_de(datos)["escritos"] == ["53.6"]
    assert len(ia.textos) == 2 and ia.textos[1].startswith("FASE: DESEMPATE")
    assert "126.4" in ia.textos[1] and "53.6" in ia.textos[1]


def prueba_la_calculadora_corrige_antes_de_comparar():
    # la primera dice 41.3 pero su propia cuenta da 41.09: corregida ya cuadra con la segunda (sin desempate)
    primera = _escribe("41.3", calculo="26*sind(84)/sind(39)")
    ia = _IA(_escribe("41.1", calculo="26*sind(84)/sind(39)"))
    datos, nota = cerebro.segunda_opinion(ia, "", "image/png", "FASE: CONTESTAR\nx", primera)
    assert nota == "cuadra", nota
    assert cerebro.valores_de(datos)["escritos"] == ["41.1"]


def prueba_graficas_comparan_los_puntos():
    a = {"tipo": "graficar", "acciones": [{"hacer": "clic", "en": {"gx": 0, "gy": 2}}, {"hacer": "clic", "en": {"gx": -1, "gy": 0}}]}
    b = {"tipo": "graficar", "acciones": [{"hacer": "clic", "en": {"gx": -1, "gy": 0}}, {"hacer": "clic", "en": {"gx": 0, "gy": 2}}]}
    c = {"tipo": "graficar", "acciones": [{"hacer": "clic", "en": {"gx": 0, "gy": 2}}, {"hacer": "clic", "en": {"gx": 1, "gy": 4}}]}
    assert cerebro.mismas_respuestas(a, b)
    assert not cerebro.mismas_respuestas(a, c)


def prueba_si_la_segunda_falla_se_queda_la_primera():
    primera = _escribe("12")

    def ia(b64, mime, texto, fase="contestar", esfuerzo=None):
        raise RuntimeError("sin red")
    datos, nota = cerebro.segunda_opinion(ia, "", "image/png", "FASE: CONTESTAR\nx", primera)
    assert datos is primera and nota.startswith("sin segunda opinion"), nota


def prueba_bot_comprueba_las_de_calcular():
    import queue

    from clw import config, motor
    from clw.bot import Bot
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (700, 300), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 40), "Calcula 7 x 8 y escribe el resultado:", fill="black")
    d.rectangle((60, 120, 260, 160), outline=(60, 60, 60))
    llamadas = []

    class Cliente:
        restantes = None

        def preguntar(self, proveedor, modelo, clave, sistema, b64, mime, texto, preciso=False):
            llamadas.append(texto.split("\n", 1)[0])
            if texto.startswith("FASE: UBICAR"):
                return json.dumps({"hay_pregunta": True, "caja": [10, 10, 690, 290], "tipo": "numerica"}), False
            if texto.startswith("FASE: REVISAR"):
                return '{"ok": true}', False
            campo = next((l.split("]")[0][1:] for l in texto.splitlines() if l.startswith("[C")), "C0")
            valor = {"FASE: CONTESTAR": "54", "FASE: COMPROBAR": "56", "FASE: DESEMPATE": "56"}[texto.split("\n", 1)[0]]
            return json.dumps({"tipo": "numerica", "respuesta": valor,
                               "acciones": [{"hacer": "escribir", "en": campo, "texto": valor}]}), False

    class Acciones:
        VK_ESCAPE = 0x1B

        class Cancelado(Exception):
            pass

        def __init__(self):
            self.log = []

        def tecla_abajo(self, vk):
            return False

        def clic(self, x, y, lento=False):
            self.log.append(("clic", x, y))

        def seleccionar_todo(self):
            pass

        def escribir(self, texto, cancelar=None):
            self.log.append(("escribe", texto))

    import tempfile
    c = config.Config(os.path.join(tempfile.mkdtemp(), "ajustes.json"))
    c.poner_clave("claude", "sk-ant-prueba")
    c["guardar_capturas"] = False
    acc = Acciones()
    bot = Bot(c, queue.Queue(), ocr=None, cliente=Cliente(), acciones=acc)
    viejo = motor.capturar_zona
    motor.capturar_zona = lambda left, top, w, h: img.crop((int(left), int(top), int(left + w), int(top + h)))
    try:
        plan, ej = bot.contestar(img, 0, 0, 100, 60, 1.0)
    finally:
        motor.capturar_zona = viejo
    assert llamadas[:4] == ["FASE: UBICAR", "FASE: CONTESTAR", "FASE: COMPROBAR", "FASE: DESEMPATE"], llamadas
    assert [p["texto"] for p in plan.pasos] == ["56"], plan.pasos
    assert ("escribe", "56") in acc.log and ("escribe", "54") not in acc.log, acc.log
