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
        assert ui.modelo_actual().id.startswith("claude")   # (sin servidor: la de antes)
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


def prueba_planes_basico_pro_y_premium():
    with _Sin(vence=_dia(20)):
        e = licencia.estado_codigo(CODIGO)
        assert e.plan == "pro" and "Plan Pro" in e.mensaje             # sin plan en la lista = Pro (los de antes)
        licencia._aplicar({"codigos": {}, "vencen": {str(NUM): _dia(20)}, "planes": {str(NUM): "basico"}})
        e = licencia.estado_codigo(CODIGO)
        assert e.activa and e.plan == "basico" and "Plan Básico" in e.mensaje, e.mensaje
        licencia._aplicar({"vencen": {str(NUM): _dia(20)}, "planes": {str(NUM): "premium"}})
        assert licencia.estado_codigo(CODIGO).plan == "premium"
        licencia._aplicar({"vencen": {str(NUM): _dia(20)}, "planes": {str(NUM): "lo que sea"}})
        assert licencia.estado_codigo(CODIGO).plan == "pro"
    assert licencia.permite("basico", "opcion_unica") and licencia.permite("basico", "abierta")
    assert not licencia.permite("basico", "graficar") and not licencia.permite("basico", "numerica")
    assert licencia.permite("pro", "graficar") and licencia.permite("premium", "arrastrar")


# ---------------------------------------------------------------- 2.4: la IA incluida en el plan (servidor)

class _ConServidor(_Sin):
    def __init__(self, dueno=False, **k):
        super().__init__(vence=_dia(30), **k)
        self.dueno = dueno

    def __enter__(self):
        super().__enter__()
        os.environ["CLW_SERVIDOR"] = "https://servidor.prueba"
        licencia._remoto["duenos"] = {NUM} if self.dueno else set()
        return self

    def __exit__(self, *a):
        os.environ.pop("CLW_SERVIDOR", None)
        super().__exit__(*a)


def _planes(plan):
    licencia._remoto["planes"] = {NUM: plan} if plan else {}


def prueba_con_servidor_el_cliente_elige_ia_sin_claves():
    with _ConServidor():
        ui, app, c = _ui()
        assert ui.ia_incluida()
        ui.inyectar()
        assert ui.clave["prov"] == "licencia"              # sin codigo: pide el codigo, nunca una clave de IA
        c["licencia"] = CODIGO
        ui._ir("principal")
        assert ui.modelo_actual().id == "gemini-flash-latest"   # Pro: arranca con Gemini Flash
        ui.inyectar()
        assert "iniciar" in app.log, app.log               # arranca directo, sin clave de IA
        ui._accion("modelo:claude-haiku-5-5")               # Pro trae Claude Haiku
        assert ui.modelo_actual().id == "claude-haiku-5-5" and c["modelo"] == "claude-haiku-5-5"
        assert c["modelo_servidor"] == "claude-haiku-5-5"
        ui._accion("modelo:claude-opus-5-5")                # Opus es del Premium: no cambia y le avisa
        assert ui.modelo_actual().id == "claude-haiku-5-5"
        assert any("plan Premium" in a[1] for a in ui.actividad), list(ui.actividad)
        ui.capa = "modelos"
        ui.render()
        ui.capa = None
        ui.evento_bot(("uso", 37))
        ui._ir("ajustes")
        ui.render()
        assert any(z[0] == "planes" for z in ui.zonas), [z[0] for z in ui.zonas]
        assert not any(str(z[0]).startswith("clave:") for z in ui.zonas)
        ui._accion("planes")
        assert ("url", "https://santiagoliftss-svj.github.io/NOT-LIMIT/#precio") in app.log


def prueba_ias_por_plan():
    with _ConServidor():
        d = tempfile.mkdtemp()
        c = config.Config(os.path.join(d, "a.json"))
        c["licencia"] = CODIGO
        _planes("basico")
        assert licencia.permitidos(c) == ["gemini-flash-lite-latest"]
        c["modelo_servidor"] = "claude-opus-5-5"
        assert licencia.modelo_efectivo(c) == "gemini-flash-lite-latest"   # lo que no trae su plan no se usa
        _planes("pro")
        assert "claude-haiku-5-5" in licencia.permitidos(c) and "claude-opus-5-5" not in licencia.permitidos(c)
        assert licencia.modelo_efectivo(c) == "gemini-flash-latest"
        _planes("premium")
        assert licencia.modelo_efectivo(c) == "claude-opus-5-5" and licencia.peso("claude-opus-5-5") == 5
        assert licencia.plan_de_modelo("claude-opus-5-5") == "Premium" and licencia.plan_de_modelo("gpt-6-luna") == "Pro"


def prueba_dueno_tiene_todas():
    with _ConServidor(dueno=True):
        d = tempfile.mkdtemp()
        c = config.Config(os.path.join(d, "a.json"))
        c["licencia"] = CODIGO
        _planes("basico")
        assert "claude-opus-5-5" in licencia.permitidos(c)


def prueba_sin_servidor_todo_sigue_como_antes():
    with _Sin(vence=_dia(30)):
        ui, app, c = _ui()
        assert not licencia.servidor() and not ui.ia_incluida()
        assert ui.modelo_actual().id == "claude-haiku-5-5"
        assert not c.tiene_clave("claude")


def prueba_bot_con_servidor_manda_codigo_peso_y_una_pregunta_por_clic():
    from clw.bot import Bot
    with _ConServidor():
        _planes("premium")
        d = tempfile.mkdtemp()
        c = config.Config(os.path.join(d, "a.json"))
        c["licencia"] = CODIGO.lower()
        c["modelo_servidor"] = "claude-opus-5-5"
        b = Bot(c, queue.Queue(), ocr=None, cliente=object())
        assert b.puede_iniciar()                           # sin ninguna clave de IA
        m, real = b.modelo()
        assert m.proveedor == "claude" and real == "claude-opus-5-5"
        k = b._clave(m)
        assert k["servidor"] == "https://servidor.prueba" and k["codigo"] == CODIGO and len(k["equipo"]) == 32
        assert k["peso"] == 5 and "claude-haiku-5-5" in k["permitidos"]
        assert k["equipo"] == licencia.equipo()            # siempre la misma compu
        p1 = k["pregunta"]
        b._pregunta = "otra"
        assert b._clave(m)["pregunta"] == "otra" != p1


def prueba_restantes_avisa_cuando_quedan_pocas():
    from clw.bot import Bot
    with _ConServidor():
        d = tempfile.mkdtemp()
        c = config.Config(os.path.join(d, "a.json"))

        class Cli:
            restantes = 20
        b = Bot(c, queue.Queue(), ocr=None, cliente=Cli())
        b._avisar_restantes(21)
        ev = []
        while not b.eventos.empty():
            ev.append(b.eventos.get())
        assert ("uso", 20) in ev and any(e[0] == "actividad" and "20 preguntas" in e[1] for e in ev), ev
        assert licencia.uso()["restantes"] == 20
