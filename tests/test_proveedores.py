"""Pruebas de Claude / Gemini / ChatGPT contra un servidor falso local."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

from clw import proveedores as P  # noqa: E402

PEDIDOS = []
GUION = {}   # funcion(path, headers, body) -> (estado, dict)


class _Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _responder(self):
        largo = int(self.headers.get("content-length") or 0)
        cuerpo = json.loads(self.rfile.read(largo) or b"null") if largo else None
        PEDIDOS.append((self.command, self.path, dict(self.headers), cuerpo))
        res = GUION["f"](self.command, self.path, self.headers, cuerpo)
        estado, datos = res[0], res[1]
        crudo = json.dumps(datos).encode()
        self.send_response(estado)
        for k, v in (res[2] if len(res) > 2 else {}).items():
            self.send_header(k, v)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    do_GET = _responder
    do_POST = _responder


def _servidor():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    for p in ("CLAUDE", "GEMINI", "OPENAI"):
        os.environ[f"CLW_API_{p}"] = base
    return srv


SRV = _servidor()


def _claude_ok(texto):
    return {"content": [{"type": "thinking", "thinking": "x", "signature": "s"}, {"type": "text", "text": texto}],
            "stop_reason": "end_turn"}


def _err(msg, tipo="invalid_request_error"):
    return {"type": "error", "error": {"type": tipo, "message": msg}}


def prueba_claude_variantes_y_memoria():
    PEDIDOS.clear()

    def f(m, path, h, body):
        assert path == "/v1/messages" and h["x-api-key"] == "sk-ant-x" and h["anthropic-version"] == "2023-06-01"
        t = (body.get("thinking") or {}).get("type")
        if t == "disabled":
            return 400, _err('"thinking.type.disabled" is not supported for this model.')
        if t == "between_tools":
            return 400, _err('"thinking.type.between_tools" is not supported for this model.')
        assert body["output_config"] == {"effort": "low"} and body["max_tokens"] == 16000
        c = body["messages"][0]["content"]
        assert c[0]["type"] == "image" and c[0]["source"]["data"] == "QUJD" and c[1]["text"] == "hola"
        return 200, _claude_ok('{"id": 1}')

    GUION["f"] = f
    cli = P.ClienteIA()
    assert cli.preguntar("claude", "claude-opus-5-5", "sk-ant-x", "sis", "QUJD", "image/png", "hola") == ('{"id": 1}', False)
    assert len(PEDIDOS) == 3
    cli.preguntar("claude", "claude-opus-5-5", "sk-ant-x", "sis", "QUJD", "image/png", "hola")
    assert len(PEDIDOS) == 4 and PEDIDOS[3][3]["output_config"] == {"effort": "low"}


def prueba_claude_haiku_sin_pensar():
    PEDIDOS.clear()
    GUION["f"] = lambda m, p, h, b: (200, _claude_ok("ok"))
    P.ClienteIA().preguntar("claude", "claude-haiku-5-5", "sk-ant-x", "s", "QUJD", "image/png", "t")
    assert PEDIDOS[0][3]["thinking"] == {"type": "disabled"} and PEDIDOS[0][3]["max_tokens"] == 2000


def prueba_claude_errores():
    casos = [
        (401, _err("invalid x-api-key", "authentication_error"), "clave"),
        (400, _err("Your credit balance is too low to access the Anthropic API."), "saldo"),
        (404, _err("model: claude-x", "not_found_error"), "modelo"),
    ]
    for estado, cuerpo, tipo in casos:
        GUION["f"] = lambda m, p, h, b, e=estado, c=cuerpo: (e, c)
        try:
            P.ClienteIA().preguntar("claude", "claude-haiku-5-5", "sk-ant-x", "s", "QUJD", "image/png", "t")
            raise AssertionError("debio fallar")
        except P.ErrorIA as e:
            assert e.tipo == tipo, (e.tipo, tipo, e.mensaje)


def prueba_reintento_saturado():
    llamadas = []

    def f(m, p, h, b):
        llamadas.append(1)
        return (529, _err("Overloaded", "overloaded_error")) if len(llamadas) == 1 else (200, _claude_ok("ya"))

    GUION["f"] = f
    assert P.ClienteIA().preguntar("claude", "claude-haiku-5-5", "k", "s", "QUJD", "image/png", "t")[0] == "ya"


def prueba_gemini():
    PEDIDOS.clear()

    def f(m, path, h, body):
        assert path == "/v1beta/models/gemini-flash-latest:generateContent" and h["x-goog-api-key"] == "AIzaX"
        nivel = body.get("generationConfig", {}).get("thinkingConfig", {}).get("thinkingLevel")
        if nivel == "minimal":
            return 400, {"error": {"code": 400, "message": "Thinking level minimal is not supported", "status": "INVALID_ARGUMENT"}}
        partes = body["contents"][0]["parts"]
        assert partes[0]["inlineData"]["mimeType"] == "image/png" and partes[1]["text"] == "t"
        assert body["systemInstruction"]["parts"][0]["text"] == "s"
        return 200, {"candidates": [{"content": {"parts": [{"text": "pienso", "thought": True}, {"text": '{"id": 2}'}]},
                                     "finishReason": "STOP"}]}

    GUION["f"] = f
    assert P.ClienteIA().preguntar("gemini", "gemini-flash-latest", "AIzaX", "s", "QUJD", "image/png", "t") == ('{"id": 2}', False)
    assert PEDIDOS[1][3]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def prueba_gemini_clave_mala():
    GUION["f"] = lambda m, p, h, b: (400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                                      "status": "INVALID_ARGUMENT"}})
    try:
        P.ClienteIA().preguntar("gemini", "gemini-flash-latest", "AIzaX", "s", "QUJD", "image/png", "t")
        raise AssertionError("debio fallar")
    except P.ErrorIA as e:
        assert e.tipo == "clave", e.mensaje


def prueba_openai():
    PEDIDOS.clear()

    def f(m, path, h, body):
        assert path == "/v1/chat/completions" and h["authorization"] == "Bearer sk-x"
        if body.get("reasoning_effort") == "none":
            return 400, {"error": {"message": "Unsupported value: 'reasoning_effort' does not support 'none'", "type": "invalid_request_error"}}
        u = body["messages"][1]["content"]
        assert u[1]["image_url"]["url"].startswith("data:image/png;base64,QUJD")
        return 200, {"choices": [{"message": {"content": '{"ids": [0]}'}, "finish_reason": "stop"}]}

    GUION["f"] = f
    assert P.ClienteIA().preguntar("openai", "gpt-6-luna", "sk-x", "s", "QUJD", "image/png", "t") == ('{"ids": [0]}', False)
    assert PEDIDOS[1][3]["reasoning_effort"] == "minimal"


def prueba_openai_sin_saldo():
    GUION["f"] = lambda m, p, h, b: (429, {"error": {"message": "You exceeded your current quota, please check your plan and billing details.",
                                                      "type": "insufficient_quota", "code": "insufficient_quota"}})
    try:
        P.ClienteIA().preguntar("openai", "gpt-6-luna", "sk-x", "s", "QUJD", "image/png", "t")
        raise AssertionError("debio fallar")
    except P.ErrorIA as e:
        assert e.tipo == "saldo", e.mensaje


def prueba_validar_clave():
    def f(m, path, h, body):
        assert m == "GET"
        if h.get("x-api-key") == "sk-ant-buena" or h.get("x-goog-api-key") == "AIzaBuena" or h.get("authorization") == "Bearer sk-buena":
            return 200, {"data": []}
        return 401, _err("invalid x-api-key", "authentication_error")

    GUION["f"] = f
    assert P.validar_clave("claude", "sk-ant-buena") is None
    assert P.validar_clave("gemini", "AIzaBuena") is None
    assert P.validar_clave("openai", "sk-buena") is None
    assert P.validar_clave("claude", "sk-ant-mala").tipo == "clave"
    assert P.validar_clave("claude", "").tipo == "clave"


def prueba_clave_parece_de():
    assert P.clave_parece_de("sk-ant-api03-x") == "claude"
    assert P.clave_parece_de("AIzaSyX") == "gemini"
    assert P.clave_parece_de("sk-proj-x") == "openai"
    assert P.clave_parece_de("hola") is None


def prueba_gemini_saturado_usa_otro_modelo():
    """Gemini gratis: si Flash esta saturado (503) o sin cupo (429), contesta Flash-Lite y se queda con ese un rato."""
    PEDIDOS.clear()
    ok = {"candidates": [{"content": {"parts": [{"text": '{"id": 5}'}]}, "finishReason": "STOP"}]}

    def f(m, path, h, body):
        if "gemini-flash-latest" in path:
            return 503, {"error": {"code": 503, "message": "The model is overloaded. Please try again later.",
                                   "status": "UNAVAILABLE"}}
        if "gemini-flash-lite-latest" in path:
            return 200, ok
        return 404, {"error": {"code": 404, "message": "model not found", "status": "NOT_FOUND"}}

    GUION["f"] = f
    cli = P.ClienteIA()
    cli.pausa = 0.01
    assert cli.preguntar("gemini", "gemini-flash-latest", "AIzaX", "s", "QUJD", "image/png", "t")[0] == '{"id": 5}'
    rutas = [p for _, p, _, _ in PEDIDOS]
    assert sum("gemini-flash-latest" in p for p in rutas) == 2, rutas          # se reintento una vez
    PEDIDOS.clear()
    assert cli.preguntar("gemini", "gemini-flash-latest", "AIzaX", "s", "QUJD", "image/png", "t")[0] == '{"id": 5}'
    assert ["gemini-flash-lite-latest" in p for _, p, _, _ in PEDIDOS] == [True], "ya se va directo al que si sirve"

    # sin cupo en todos: se avisa claro (y no se queda pegado)
    GUION["f"] = lambda m, p, h, b: (429, {"error": {"code": 429, "message": "Resource has been exhausted",
                                                     "status": "RESOURCE_EXHAUSTED"}})
    cli = P.ClienteIA()
    cli.pausa = 0.01
    try:
        cli.preguntar("gemini", "gemini-flash-latest", "AIzaX", "s", "QUJD", "image/png", "t")
        raise AssertionError("debio fallar")
    except P.ErrorIA as e:
        assert e.tipo == "limite" and "cupo" in e.mensaje, e.mensaje

    # la clave mala no se reintenta con otros modelos
    PEDIDOS.clear()
    GUION["f"] = lambda m, p, h, b: (400, {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT"}})
    try:
        P.ClienteIA().preguntar("gemini", "gemini-flash-latest", "AIzaX", "s", "QUJD", "image/png", "t")
        raise AssertionError("debio fallar")
    except P.ErrorIA as e:
        assert e.tipo == "clave" and len(PEDIDOS) == 1


def prueba_preciso_piensa_mas():
    PEDIDOS.clear()

    def f(m, path, h, body):
        nivel = body.get("generationConfig", {}).get("thinkingConfig", {}).get("thinkingLevel")
        if nivel == "medium":
            return 400, {"error": {"code": 400, "message": "thinking level not supported", "status": "INVALID_ARGUMENT"}}
        return 200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}

    GUION["f"] = f
    assert P.ClienteIA().preguntar("gemini", "gemini-flash-latest", "k", "s", "QUJD", "image/png", "t", preciso=True)[0] == "ok"
    niveles = [b["generationConfig"]["thinkingConfig"]["thinkingLevel"] for _, _, _, b in PEDIDOS]
    assert niveles == ["medium", "low"], niveles


def prueba_si_un_modelo_se_tarda_se_pasa_al_siguiente():
    from clw import proveedores as P
    c = P.ClienteIA()
    c.pausa = 0
    usados = []

    def una(proveedor, modelo, clave, sistema, b64, mime, texto, preciso):
        usados.append(modelo)
        if modelo == "gemini-flash-latest":
            raise P.ErrorIA("No hay conexión a internet (o tardó demasiado).", "red", "The read operation timed out")
        return ("ok", False)
    c._una = una
    assert c.preguntar("gemini", "gemini-flash-latest", "k", "s", "b", "image/png", "t") == ("ok", False)
    assert usados == ["gemini-flash-latest", "gemini-flash-lite-latest"], usados


# ---------------------------------------------------------------- servidor de NO LIMIT (IA incluida en el plan)

def _clave_nl(pregunta="p1", peso=1, permitidos=None):
    return {"servidor": os.environ["CLW_API_GEMINI"], "codigo": "NL-AAAA-BBBB-CCCC", "equipo": "eq1",
            "pregunta": pregunta, "version": "2.4.0", "peso": peso, "permitidos": permitidos}


def _sin_claves(h):
    assert "x-goog-api-key" not in h and "x-api-key" not in h and "authorization" not in h, dict(h)


def prueba_servidor_gemini_manda_codigo_compu_y_pregunta():
    PEDIDOS.clear()

    def f(m, path, h, body):
        assert path == "/v1beta/models/gemini-flash-latest:generateContent"
        assert h["x-nl-codigo"] == "NL-AAAA-BBBB-CCCC" and h["x-nl-equipo"] == "eq1" and h["x-nl-pregunta"] == "p1"
        _sin_claves(h)                                        # la app ya no manda ninguna clave de IA
        assert body["contents"][0]["parts"][0]["inlineData"]["data"] == "QUJD"
        return 200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}, {"x-nl-restantes": "41"}

    GUION["f"] = f
    cli = P.ClienteIA()
    assert cli.preguntar("gemini", "gemini-flash-latest", _clave_nl(), "s", "QUJD", "image/png", "t") == ("ok", False)
    assert cli.restantes == 41


def prueba_servidor_claude_y_chatgpt_sin_clave():
    PEDIDOS.clear()

    def f(m, path, h, body):
        _sin_claves(h)
        assert h["x-nl-peso"] == "5"
        if path == "/v1/messages":
            assert body["model"] == "claude-opus-5-5" and h["anthropic-version"]
            return 200, _claude_ok("claude")
        assert path == "/v1/chat/completions" and body["model"] == "gpt-6-luna"
        return 200, {"choices": [{"message": {"content": "gpt"}, "finish_reason": "stop"}]}

    GUION["f"] = f
    cli = P.ClienteIA()
    assert cli.preguntar("claude", "claude-opus-5-5", _clave_nl(peso=5), "s", "QUJD", "image/png", "t")[0] == "claude"
    assert cli.preguntar("openai", "gpt-6-luna", _clave_nl(peso=5), "s", "QUJD", "image/png", "t")[0] == "gpt"


def prueba_servidor_errores_del_plan():
    cli = P.ClienteIA()
    cli.pausa = 0
    casos = [
        (402, "cupo", "Ya usaste tus 600 preguntas de este mes.", "saldo"),
        (402, "dia", "Llegaste al máximo de 120 preguntas por hoy.", "saldo"),
        (403, "equipo", "Tu código ya se está usando en otra compu.", "licencia"),
        (401, "vencido", "Tu plan venció el 2026-11-01.", "licencia"),
        (401, "codigo", "Ese código no sirve.", "licencia"),
        (403, "plan", "Claude Opus es del plan Premium. Elige otra IA o sube de plan.", "plan"),
    ]
    for estado, tipo, msg, esperado in casos:
        PEDIDOS.clear()
        GUION["f"] = lambda m, p, h, b, e=estado, t=tipo, ms=msg: (e, {"error": {"tipo": t, "message": ms}})
        try:
            cli.preguntar("claude", "claude-opus-5-5", _clave_nl(), "s", "QUJD", "image/png", "t")
            raise AssertionError("debio fallar")
        except P.ErrorIA as e:
            assert e.tipo == esperado and e.mensaje == msg, (e.tipo, e.mensaje)
            assert e.tipo != "clave"                          # nunca pide "clave de la IA"
        assert len(PEDIDOS) == 1, (tipo, len(PEDIDOS))        # no reintenta ni cambia de modelo


def prueba_servidor_ia_apagada_prueba_otra_del_plan():
    PEDIDOS.clear()

    def f(m, path, h, body):
        if body["model"] == "claude-sonnet-5-5":
            return 503, {"error": {"tipo": "ia", "message": "Claude no está disponible ahorita. Elige otra IA."}}
        return 200, _claude_ok("haiku")

    GUION["f"] = f
    cli = P.ClienteIA()
    cli.pausa = 0
    # Pro: no trae Sonnet ni Opus: si la elegida falla, solo prueba las de su plan
    assert cli.preguntar("claude", "claude-sonnet-5-5", _clave_nl(permitidos=["claude-haiku-5-5"]), "s", "QUJD",
                         "image/png", "t")[0] == "haiku"
    assert [b["model"] for _, _, _, b in PEDIDOS] == ["claude-sonnet-5-5", "claude-haiku-5-5"]


def prueba_servidor_variante_rechazada_prueba_otra():
    PEDIDOS.clear()

    def f(m, path, h, body):
        nivel = (body.get("generationConfig") or {}).get("thinkingConfig", {}).get("thinkingLevel")
        if nivel == "minimal":
            return 400, {"error": {"code": 400, "message": "Thinking level minimal is not supported", "status": "INVALID_ARGUMENT"}}
        return 200, {"candidates": [{"content": {"parts": [{"text": "ya"}]}, "finishReason": "STOP"}]}

    GUION["f"] = f
    assert P.ClienteIA().preguntar("gemini", "gemini-flash-latest", _clave_nl(), "s", "QUJD", "image/png", "t")[0] == "ya"
    assert len(PEDIDOS) == 2
