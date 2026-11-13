"""Suscripcion: sin codigo pagado y al corriente NO LIMIT no arranca; se vence cada mes; se puede bloquear."""
import datetime as dt
import json
import os
import queue
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from clw import config, licencia  # noqa: E402
from clw.ui.vistas import Interfaz  # noqa: E402

CODIGO = "NL-7K2Q-M9XD-4TPA"
NUM = 7


def _dia(dias):
    return (dt.date.today() + dt.timedelta(days=dias)).isoformat()


class _Sin:
    """Apaga el modo de prueba y deja solo CODIGO (numero 7) como codigo que existe."""
    def __init__(self, vence=None, revisado=True, bloqueado=False, hoy=""):
        self.vence, self.revisado, self.bloqueado, self.hoy = vence, revisado, bloqueado, hoy

    def __enter__(self):
        self.antes = (licencia.PRUEBA, licencia.HUELLAS, licencia._cargado, dict(licencia._remoto))
        licencia.PRUEBA, licencia._cargado = False, True
        licencia.HUELLAS = {licencia.huella(CODIGO): NUM}
        licencia._remoto.update(extra={}, bloqueadas={licencia.huella(CODIGO)} if self.bloqueado else set(),
                                vencen={NUM: self.vence} if self.vence else {}, hoy=self.hoy,
                                revisado=time.time() if self.revisado else 0.0)
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
    with _Sin(vence=_dia(20)):
        assert licencia.valido(CODIGO) and licencia.valido("nl 7k2q m9xd 4tpa") and licencia.valido(CODIGO + " ")
        assert not licencia.valido("NL-7K2Q-M9XD-4TPB") and not licencia.valido("") and not licencia.valido("AIzaSy1")
        assert licencia.formatear("7k2qm9xd4tpa") == CODIGO
        assert licencia.parece_licencia(CODIGO) and not licencia.parece_licencia("sk-ant-api03-xx")
        assert licencia.numero(CODIGO) == NUM


def prueba_estados_del_mes():
    with _Sin(vence=_dia(20)):
        e = licencia.estado_codigo(CODIGO)
        assert e.activa and e.motivo == "ok" and e.vence == _dia(20), e.motivo
    with _Sin(vence=_dia(0)):
        assert licencia.estado_codigo(CODIGO).activa                    # el ultimo dia todavia sirve
    with _Sin(vence=_dia(-1)):
        e = licencia.estado_codigo(CODIGO)
        assert not e.activa and e.motivo == "vencido" and "venció" in e.mensaje
    with _Sin():
        assert licencia.estado_codigo(CODIGO).motivo == "sin_activar"   # vendido pero no registrado
    with _Sin(vence=_dia(20), bloqueado=True):
        assert licencia.estado_codigo(CODIGO).motivo == "bloqueado"
    with _Sin(vence=_dia(20), revisado=False):
        assert licencia.estado_codigo(CODIGO).motivo == "sin_revisar"   # sin poder revisar la lista
    with _Sin(vence=_dia(20)):
        assert licencia.estado_codigo("NL-0000-0000-0000").motivo == "codigo"
        assert licencia.estado_codigo("").motivo == "sin_codigo"


def prueba_atrasar_el_reloj_no_sirve():
    with _Sin(vence=_dia(5), hoy=_dia(40)):            # el servidor dice que ya es mas tarde
        assert licencia.hoy() == _dia(40)
        assert licencia.estado_codigo(CODIGO).motivo == "vencido"


def prueba_formatos_de_la_lista():
    with _Sin():
        nuevo = "NL-AAAA-BBBB-CCCC"
        licencia._aplicar({"extra": [licencia.huella(nuevo)], "vencen": {"7": _dia(3), "x": "mal"}})   # formato 1.5
        assert licencia.numero(nuevo) == 0 and licencia._remoto["vencen"] == {7: _dia(3)}
        licencia._aplicar({"codigos": {licencia.huella(nuevo): 42}, "vencen": {"42": _dia(3)}})
        assert licencia.numero(nuevo) == 42 and licencia.estado_codigo(nuevo).activa


class _Pagina(BaseHTTPRequestHandler):
    datos = {}

    def log_message(self, *a):
        pass

    def date_time_string(self, timestamp=None):      # la fecha "del servidor"
        return "Fri, 01 Jan 2100 10:00:00 GMT"

    def do_GET(self):
        crudo = json.dumps(_Pagina.datos).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)


def prueba_refrescar_baja_la_lista_y_la_fecha_del_servidor():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Pagina)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = tempfile.mkdtemp()
    antes_url, antes_datos = licencia.URL, os.environ.get("CLW_DATOS")
    os.environ["CLW_DATOS"] = d
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    try:
        with _Sin(revisado=False):
            licencia.URL = f"http://127.0.0.1:{srv.server_address[1]}/licencias.json"
            _Pagina.datos = {"vencen": {str(NUM): "2100-02-01"}, "bloqueadas": []}
            licencia.refrescar()
            assert licencia.hoy() == "2100-01-01"
            assert licencia.estado_codigo(CODIGO).activa
            with open(os.path.join(d, "licencias.json"), encoding="utf-8") as f:
                guardado = json.load(f)
            assert guardado["_hoy"] == "2100-01-01" and guardado["vencen"] == {str(NUM): "2100-02-01"}
            _Pagina.datos = {"vencen": {str(NUM): "2099-12-31"}}         # no pago: vencido
            licencia.refrescar()
            assert licencia.estado_codigo(CODIGO).motivo == "vencido"
    finally:
        licencia.URL = antes_url
        if antes_datos is not None:
            os.environ["CLW_DATOS"] = antes_datos
        srv.shutdown()


def prueba_sin_codigo_no_arranca_y_con_codigo_pagado_si():
    with _Sin(vence=_dia(30)):
        ui, app, c = _ui()
        c.poner_clave("claude", "sk-ant-api03-x")
        ui.inyectar()
        assert "iniciar" not in app.log
        assert ui.pantalla == "clave" and ui.clave["prov"] == "licencia", ui.pantalla
        ui.render()
        for ch in "NL-0000-0000-0000":
            ui.tecla(ch, ch)
        ui.tecla("", "Return")
        assert "no sirve" in ui.clave["msg"] and "iniciar" not in app.log
        ui.tecla("", "BackSpace", ctrl=True)
        app.portapapeles = CODIGO.lower()
        ui._accion("pegar")
        ui.tecla("", "Return")
        assert c.get("licencia") == CODIGO, c.get("licencia")
        assert "iniciar" in app.log, app.log                   # pagado: arranca solo
        assert any("activa hasta" in a[1] for a in ui.actividad), list(ui.actividad)


def prueba_codigo_vencido_no_entra_aunque_lo_vuelva_a_poner():
    with _Sin(vence=_dia(-3)):
        ui, app, c = _ui()
        c.poner_clave("claude", "sk-ant-api03-x")
        c["licencia"] = CODIGO
        ui.inyectar()
        assert ui.pantalla == "clave" and ui.clave["prov"] == "licencia"
        assert "venció" in ui.clave["msg"] and ui.clave["texto"] == CODIGO
        ui.guardar_clave()                                     # lo vuelve a poner: igual no entra
        assert "venció" in ui.clave["msg"] and "iniciar" not in app.log
        ui.render()
    with _Sin(vence=_dia(30)):                                 # ya pago (el vendedor lo renovo)
        ui.guardar_clave()
        assert "iniciar" in app.log


def prueba_codigo_primero_luego_clave():
    with _Sin(vence=_dia(30)):
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


def prueba_clave_de_otra_ia_se_acomoda_sola():
    with _Sin(vence=_dia(30)):
        ui, app, c = _ui()
        c["licencia"] = CODIGO
        assert c["modelo"].startswith("claude")
        ui.inyectar()
        assert ui.pantalla == "clave" and ui.clave["prov"] == "claude"
        app.portapapeles = "AIzaSyA-clave-gratis-de-gemini-1234567"
        ui._accion("pegar")
        ui.guardar_clave()
        assert ("verificar", "gemini") in app.log, app.log          # se revisa como clave de Gemini
        assert c["modelo"] == "gemini-flash-latest"
        ui.clave_verificada("gemini", "AIzaSyA-clave-gratis-de-gemini-1234567", None)
        assert c.tiene_clave("gemini") and "iniciar" in app.log


def prueba_bot_se_apaga_si_se_vence_el_mes():
    from clw.bot import Bot
    with _Sin(vence=_dia(-1)):
        d = tempfile.mkdtemp()
        c = config.Config(os.path.join(d, "a.json"))
        c.poner_clave("claude", "sk-ant-x")
        c["licencia"] = CODIGO
        b = Bot(c, queue.Queue(), ocr=None, cliente=object())
        b.escucha.iniciar = lambda: True
        b.escucha.detener = lambda: None
        b.activo = True
        b._disparo(10, 10)
        ev = []
        while not b.eventos.empty():
            ev.append(b.eventos.get_nowait())
        assert not b.activo and any(e[0] == "actividad" and "venció" in e[1] for e in ev), ev
