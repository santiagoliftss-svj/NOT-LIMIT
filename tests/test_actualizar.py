"""Actualizacion sola: comparar versiones, buscar en GitHub, bajar el instalador completo y correrlo callado."""

import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from clw import actualizar, version  # noqa: E402


class Respuesta(io.BytesIO):
    def __init__(self, datos, largo=None):
        super().__init__(datos)
        self.headers = {"content-length": str(len(datos) if largo is None else largo)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _con_urlopen(fn, respuesta):
    viejo = actualizar.urllib.request.urlopen
    pedidos = []

    def falso(req, timeout=None):
        pedidos.append(req.full_url)
        return respuesta() if callable(respuesta) else respuesta
    actualizar.urllib.request.urlopen = falso
    try:
        return fn(), pedidos
    finally:
        actualizar.urllib.request.urlopen = viejo


def _con_datos(fn):
    viejo = os.environ.get("CLW_DATOS")
    os.environ["CLW_DATOS"] = tempfile.mkdtemp()
    try:
        return fn()
    finally:
        if viejo is None:
            os.environ.pop("CLW_DATOS", None)
        else:
            os.environ["CLW_DATOS"] = viejo


def prueba_numero_de_version():
    assert actualizar.numero("v1.3.0") == (1, 3, 0)
    assert actualizar.numero("1.10") == (1, 10, 0)
    assert actualizar.numero("v2.0.1-beta") == (2, 0, 1)
    assert actualizar.numero("1.10.0") > actualizar.numero("1.9.9")


def prueba_buscar():
    def release(tag, assets):
        return lambda: Respuesta(json.dumps({"tag_name": tag, "assets": assets}).encode())

    instalador = {"name": "NO-LIMIT-Setup.exe", "browser_download_url": "https://x/NO-LIMIT-Setup.exe", "size": 1234}
    otro = {"name": "notas.txt", "browser_download_url": "https://x/notas.txt", "size": 5}
    hay, pedidos = _con_urlopen(actualizar.buscar, release("v99.0.0", [otro, instalador]))
    assert hay == ("99.0.0", "https://x/NO-LIMIT-Setup.exe", 1234), hay
    assert pedidos == [f"https://api.github.com/repos/{version.REPO}/releases/latest"]
    # la misma o una vieja: nada que hacer
    assert _con_urlopen(actualizar.buscar, release("v" + version.VERSION, [instalador]))[0] is None
    assert _con_urlopen(actualizar.buscar, release("v0.9.0", [instalador]))[0] is None
    # nueva pero sin instalador todavia: avisa sin link de descarga
    assert _con_urlopen(actualizar.buscar, release("v99.0.0", [otro]))[0] == ("99.0.0", None, 0)


def prueba_descargar_completo_y_con_avance():
    datos = os.urandom(700 * 1024)

    def bajar():
        avance = []
        ruta = actualizar.descargar("9.9.9", "https://x/a.exe", len(datos), al_avance=avance.append)
        assert ruta and open(ruta, "rb").read() == datos
        assert avance and avance == sorted(avance) and avance[-1] == 99, avance
        assert not os.path.exists(ruta + ".parcial")
        # ya bajado: no lo vuelve a pedir
        assert actualizar.descargar("9.9.9", "https://x/a.exe", len(datos)) == ruta
        return ruta
    ruta, pedidos = _con_datos(lambda: _con_urlopen(bajar, lambda: Respuesta(datos)))
    assert len(pedidos) == 1


def prueba_descarga_cortada_no_se_instala():
    datos = os.urandom(300 * 1024)

    def bajar():
        # el servidor manda menos de lo que dice GitHub: no queda nada a medias
        assert actualizar.descargar("9.9.8", "https://x/a.exe", len(datos) + 10) is None
        assert os.listdir(actualizar.carpeta()) == []
        # cancelar a medio camino (al cerrar la app)
        try:
            actualizar.descargar("9.9.8", "https://x/a.exe", len(datos), cancelar=lambda: True)
            assert False, "debio cancelarse"
        except InterruptedError:
            pass
        assert os.listdir(actualizar.carpeta()) == [], "sin pedazos a medias"
    _con_datos(lambda: _con_urlopen(bajar, lambda: Respuesta(datos)))


def prueba_instalar_callado_y_limpio():
    llamadas = []
    viejo = actualizar.subprocess.Popen
    actualizar.subprocess.Popen = lambda args, **k: llamadas.append((args, k))
    os.environ["_PYI_APPLICATION_HOME_DIR"] = "C:/viejo"
    os.environ["TCL_LIBRARY"] = "C:/viejo/tcl"
    try:
        assert actualizar.instalar("C:/datos/NO-LIMIT-Setup-9.9.9.exe", relanzar=True)
        assert actualizar.instalar("C:/datos/NO-LIMIT-Setup-9.9.9.exe", relanzar=False)
    finally:
        actualizar.subprocess.Popen = viejo
        os.environ.pop("_PYI_APPLICATION_HOME_DIR", None)
        os.environ.pop("TCL_LIBRARY", None)
    (a1, k1), (a2, _) = llamadas
    assert a1[1:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELANZAR=1"] and a2[-1] == "/RELANZAR=0"
    env = k1["env"]
    assert "_PYI_APPLICATION_HOME_DIR" not in env and "TCL_LIBRARY" not in env
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and "PATH" in {k.upper() for k in env}
