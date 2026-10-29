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
        estado, datos = GUION["f"](self.command, self.path, self.headers, cuerpo)
        crudo = json.dumps(datos).encode()
        self.send_response(estado)
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
