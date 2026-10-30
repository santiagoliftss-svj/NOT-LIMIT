"""Pruebas del motor con pantallas de prueba y una IA simulada. Correr: python tests/correr.py"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from clw import motor, muestras  # noqa: E402
from clw.ocr import OCR  # noqa: E402

OCR_ = OCR()


def _lineas(texto):
    out = []
    for l in texto.splitlines():
        if l.startswith("["):
            ident = l[1:l.index("]")]
            x, y = l.split("(")[1].split(")")[0].split(",")
            out.append((ident, int(x), int(y), l[l.index(")") + 2:]))
    return out


def _dentro(p, caja, m=1):
    return caja[0] - m <= p[0] <= caja[2] + m and caja[1] - m <= p[1] <= caja[3] + m


class Acciones:
    """Mouse y teclado de mentira para revisar que haria el bot."""
    VK_ESCAPE = 0x1B

    class Cancelado(Exception):
        pass

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


def _ia(fn):
    def preguntar(b64, mime, texto):
        assert mime in ("image/png", "image/jpeg") and len(b64) > 100
        return fn(texto), False
    return preguntar


def prueba_ocr_disponible():
    assert OCR_.disponible, "no encontre tesseract"
    assert "spa" in OCR_.idiomas() or "eng" in OCR_.idiomas(), OCR_.idiomas()


def prueba_quiz_oscuro_opcion():
    img, tarjetas, (px, py) = muestras.quiz_oscuro()

    def ia(texto):
        i = next(c[0] for c in _lineas(texto) if not c[0].startswith("C") and "París" in c[3])
        return json.dumps({"tipo": "opcion", "ids": [int(i)], "respuesta": "París"})

    res = motor.procesar(img, px, py, _ia(ia), 1.0, OCR_)
    acc = Acciones()
    hecho, n = motor.ejecutar(res, 0, 0, acciones=acc)
    assert hecho == "clic" and n == 1, (hecho, acc.log)
    assert _dentro(acc.log[0][1:], tarjetas["París"]), (acc.log, tarjetas["París"])


def prueba_columnas_separadas():
    img, tarjetas, (px, py) = muestras.quiz_oscuro()
    cajas = motor.detectar_cajas(img, px, py, 1.0, OCR_)
    textos = [c["texto"] for c in cajas]
    for op in ("Madrid", "París", "Roma", "Berlín"):
        assert any(t.endswith(op) and len(t) < len(op) + 6 for t in textos), (op, textos)


def prueba_formulario_abierta_larga():
    img, cajas_txt, (px, py) = muestras.formulario_claro()

    def ia(texto):
        campos = [c for c in _lineas(texto) if c[0].startswith("C")]
        abajo = max(campos, key=lambda c: c[2])
        return '{"tipo":"abierta","respuestas":[{"campo":"%s","texto":"Por la desigualdad.\\nY por Napoleón."}]}' % abajo[0]

    res = motor.procesar(img, 300, 390, _ia(ia), 1.0, OCR_)
    acc = Acciones()
    hecho, n = motor.ejecutar(res, 0, 0, acciones=acc)
    assert hecho == "escrita" and n == 1, (hecho, acc.log)
    assert _dentro(acc.log[0][1:], cajas_txt[1]), acc.log
    assert acc.log[2] == ("escribe", "Por la desigualdad. Y por Napoleón."), acc.log


def prueba_formulario_por_texto_gris():
    img, cajas_txt, (px, py) = muestras.formulario_claro()

    def ia(texto):
        i = next(c[0] for c in _lineas(texto) if not c[0].startswith("C") and "Escriba" in c[3] and c[2] < 300)
        return json.dumps({"tipo": "abierta", "respuestas": [{"campo": int(i), "texto": "1910"}]})

    res = motor.procesar(img, px, py, _ia(ia), 1.0, OCR_)
    acc = Acciones()
    motor.ejecutar(res, 0, 0, acciones=acc)
    assert _dentro(acc.log[0][1:], cajas_txt[0]) and acc.log[2] == ("escribe", "1910"), acc.log


def prueba_cajitas_mate_varias():
    img, cajitas, (px, py) = muestras.cajitas_mate()

    def ia(texto):
        campos = [c for c in _lineas(texto) if c[0].startswith("C")]
        assert len(campos) == 3, texto
        return json.dumps({"tipo": "abierta", "respuestas": [
            {"campo": "C0", "texto": "13/12"}, {"campo": "C1", "texto": "5/13"}, {"campo": "C2", "texto": "√3/2"}]})

    res = motor.procesar(img, px, py, _ia(ia), 1.0, OCR_)
    acc = Acciones()
    hecho, n = motor.ejecutar(res, 0, 0, acciones=acc)
    clics = [a for a in acc.log if a[0] == "clic"]
    textos = [a[1] for a in acc.log if a[0] == "escribe"]
    assert hecho == "escrita" and n == 3 and textos == ["13/12", "5/13", "√3/2"], acc.log
    for c, caja in zip(clics, cajitas):
        assert _dentro(c[1:], caja, 0), (c, caja)


def prueba_coordenadas_chuecas():
    img, cajitas, _ = muestras.cajitas_mate()
    caja = cajitas[1]
    s = motor.factor_para_ia(img.width, img.height)
    obj = {"x": ((caja[0] + caja[2]) / 2 + 16) * s, "y": ((caja[1] + caja[3]) / 2 - 10) * s}
    p = motor.resolver_objetivo(obj, [], [], s, img, 1.0, escribir_ahi=True)
    assert p and _dentro(p, caja, 0), p


def prueba_interpretar_roto():
    d = motor.interpretar('Va: {"tipo": "abierta", "respuestas": [{"campo": "C0", "texto": "1/2"}, {"campo": "C1", "texto": "√3/2"} ]  (')
    assert d["tipo"] == "abierta" and [r["texto"] for r in d["respuestas"]] == ["1/2", "√3/2"], d
    assert motor.interpretar('{"tipo":"opcion","ids":[2,5],"respuesta":"x"').get("ids") == [2, 5]
    assert motor.interpretar("```json\n{\"id\": 3}\n```") == {"id": 3}
    assert motor.interpretar("nada") == {}


def prueba_limites_imagen():
    import math
    for w, h in [(1920, 1080), (3840, 2160), (1366, 768), (960, 640)]:
        s = motor.factor_para_ia(w, h)
        a, b = int(w * s), int(h * s)
        assert math.ceil(a / 28) * math.ceil(b / 28) <= 1560 and a <= 1568 and b <= 1568


def prueba_zona_captura():
    assert motor.calcular_zona(500, 900, (0, 0, 1920, 1080), 1.25) == (0, 0, 1920, 1080)
    for px in (-1000, -1900, 1500, 1910):
        z = motor.calcular_zona(px, 300, (-1920, 0, 3840, 1080), 1.0)
        assert z[0] >= -1920 and z[0] + z[2] <= 1920 and z[0] <= px <= z[0] + z[2]


def prueba_ninguna():
    img, _, _ = muestras.quiz_oscuro()
    res = motor.procesar(img, 10, 10, _ia(lambda t: '{"tipo": "ninguna"}'), 1.0, None)
    assert motor.ejecutar(res, 0, 0, acciones=Acciones()) == ("nada", 0)


def prueba_corrige_error_de_indice():
    """La IA dice 'París' pero pone el id de otra opcion (le paso con Canberra/Sydney): se corrige."""
    img, tarjetas, (px, py) = muestras.quiz_oscuro()

    def ia(texto):
        lineas = _lineas(texto)
        madrid = next(c[0] for c in lineas if not c[0].startswith("C") and "Madrid" in c[3])
        return json.dumps({"tipo": "opcion", "respuesta": "París", "ids": [int(madrid)]})

    res = motor.procesar(img, px, py, _ia(ia), 1.0, OCR_)
    acc = Acciones()
    motor.ejecutar(res, 0, 0, acciones=acc)
    assert _dentro(acc.log[0][1:], tarjetas["París"]), acc.log


def prueba_no_corrige_si_no_hay_algo_mejor():
    cajas = [{"texto": "Q.6", "cx": 30, "cy": 30}, {"texto": "8466 m", "cx": 150, "cy": 137},
             {"texto": "x O ss124m", "cx": 104, "cy": 195}, {"texto": "8488 m", "cx": 152, "cy": 253}]
    assert motor.corregir_ids([2], "8844 m", cajas) == [2]          # OCR leyo mal: se respeta el id
    assert motor.corregir_ids([1], "8488 m", cajas) == [3]          # el id no coincide y hay uno exacto
    assert motor.corregir_ids([3], "8488 m", cajas) == [3]
    cajas2 = [{"texto": "Sydney", "cx": 480, "cy": 380}, {"texto": "Melbourne", "cx": 180, "cy": 596},
              {"texto": "Canberra", "cx": 175, "cy": 654}, {"texto": "Xx O Sydney", "cx": 117, "cy": 713}]
    assert motor.corregir_ids([3], "Canberra", cajas2) == [2]
    assert motor.corregir_ids([0], "Sydney", cajas2) == [0]
    assert motor.corregir_ids([1, 2], "Melbourne | Canberra", cajas2) == [1, 2]
    assert motor.corregir_ids([{"x": 1, "y": 2}], "Canberra", cajas2) == [{"x": 1, "y": 2}]
    assert motor.parecido("París", "O París") > 0.75 and motor.parecido("Paris", "París") == 1.0
