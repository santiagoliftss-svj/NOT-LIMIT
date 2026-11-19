import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from clw import config  # noqa: E402


def prueba_guardar_y_leer():
    d = tempfile.mkdtemp()
    ruta = os.path.join(d, "a.json")
    c = config.Config(ruta)
    assert c["modelo"] == "nolimit" and not c.tiene_clave("claude")
    c.poner_clave("claude", "  sk-ant-secreta  ")
    c["modo_preciso"] = True
    c2 = config.Config(ruta)
    assert c2.clave("claude") == "sk-ant-secreta" and c2["modo_preciso"] is True
    with open(ruta, encoding="utf-8") as f:
        assert "sk-ant-secreta" not in f.read()
    c2.poner_clave("claude", "")
    assert not config.Config(ruta).tiene_clave("claude")


def prueba_archivo_roto():
    d = tempfile.mkdtemp()
    ruta = os.path.join(d, "a.json")
    with open(ruta, "w") as f:
        f.write("{roto")
    c = config.Config(ruta)
    assert c["modelo"] == "nolimit"
    with open(ruta, "w") as f:
        f.write('{"modelo": 5, "modo_preciso": true}')
    c = config.Config(ruta)
    assert c["modelo"] == "nolimit" and c["modo_preciso"] is True


def prueba_el_codigo_se_queda_al_reabrir():
    d = tempfile.mkdtemp()
    ruta = os.path.join(d, "a.json")
    c = config.Config(ruta)
    c["licencia"] = "NL-AAAA-BBBB-CCCC"
    assert config.Config(ruta).get("licencia") == "NL-AAAA-BBBB-CCCC"


def prueba_24_pasa_a_la_ia_incluida_y_recuerda_la_de_antes():
    d = tempfile.mkdtemp()
    ruta = os.path.join(d, "a.json")
    with open(ruta, "w") as f:
        f.write('{"version_ajustes": 2, "modelo": "gemini-flash-latest", "licencia": "NL-X"}')
    c = config.Config(ruta)
    assert c["modelo"] == "nolimit" and c["modelo_antes"] == "gemini-flash-latest" and c["licencia"] == "NL-X"
    c["modelo"] = "claude-haiku-5-5"                      # (el dueno elige otra): no se vuelve a cambiar
    assert config.Config(ruta)["modelo"] == "claude-haiku-5-5"


def prueba_desproteger_basura():
    assert config.desproteger("dpapi:@@@") == ""
    assert config.desproteger("otra") == ""
