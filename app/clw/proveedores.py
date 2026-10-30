"""Claude, Gemini y ChatGPT por HTTPS directo (sin librerias extra).

Cada modelo acepta parametros distintos para "pensar poco". Se prueban variantes en orden
y se recuerda la que funciono para cada modelo.
"""

import json
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Proveedor:
    id: str
    nombre: str
    prefijo: str          # como empiezan sus claves
    url_clave: str        # donde se saca la clave
    texto_clave: str      # texto del enlace


PROVEEDORES = {
    "claude": Proveedor("claude", "Claude", "sk-ant-", "https://console.anthropic.com/settings/keys",
                        "¿No tienes una? Sácala en la Console de Anthropic"),
    "gemini": Proveedor("gemini", "Gemini", "AIza", "https://aistudio.google.com/apikey",
                        "¿No tienes una? Sácala gratis en Google AI Studio"),
    "openai": Proveedor("openai", "ChatGPT", "sk-", "https://platform.openai.com/api-keys",
                        "¿No tienes una? Sácala en la plataforma de OpenAI"),
}


@dataclass(frozen=True)
class Modelo:
    proveedor: str
    id: str
    nombre: str
    nota: str
    corto: str = ""


MODELOS = [
    Modelo("claude", "claude-haiku-5-5", "Claude Haiku 5.5", "Rápido", "Haiku 5.5"),
    Modelo("claude", "claude-sonnet-5-5", "Claude Sonnet 5.5", "Equilibrado", "Sonnet 5.5"),
    Modelo("claude", "claude-opus-5-5", "Claude Opus 5.5", "El más listo", "Opus 5.5"),
    Modelo("gemini", "gemini-flash-latest", "Gemini Flash", "Clave gratis", "Flash"),
    Modelo("gemini", "gemini-pro-latest", "Gemini Pro", "Preciso", "Pro"),
    Modelo("openai", "gpt-6-luna", "GPT-6 Luna", "Rápido", "GPT-6 Luna"),
    Modelo("openai", "gpt-6.1-terra", "GPT-6.1 Terra", "Visión", "GPT-6.1 Terra"),
]


def buscar_modelo(id_modelo):
    for m in MODELOS:
        if m.id == id_modelo:
            return m
    return MODELOS[0]


# ---------------------------------------------------------------- errores

class ErrorIA(Exception):
    """Error con mensaje listo para mostrar."""

    def __init__(self, mensaje, tipo="otro", detalle=""):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.tipo = tipo          # clave, saldo, limite, modelo, red, servidor, peticion, otro
        self.detalle = detalle


def _texto_error(cuerpo):
    try:
        j = json.loads(cuerpo)
    except ValueError:
        return cuerpo[:300]
    e = j.get("error", j) if isinstance(j, dict) else j
    if isinstance(e, dict):
        return str(e.get("message") or e.get("status") or e)[:400]
    if isinstance(e, list) and e:
        return _texto_error(json.dumps(e[0]))
    return str(e)[:400]


def _traducir(proveedor, estado, cuerpo):
    msg = _texto_error(cuerpo)
    bajo = msg.lower()
    nombre = PROVEEDORES[proveedor].nombre
    if estado in (401,) or "api key not valid" in bajo or "invalid api key" in bajo or "incorrect api key" in bajo \
            or "invalid x-api-key" in bajo or "api_key_invalid" in bajo:
        return ErrorIA(f"Tu clave de {nombre} no sirve. Revisa que esté completa.", "clave", msg)
    if "credit balance" in bajo or "insufficient_quota" in bajo or "exceeded your current quota" in bajo \
            or "billing" in bajo or "insufficient balance" in bajo:
        return ErrorIA(f"Tu cuenta de {nombre} no tiene saldo.", "saldo", msg)
    if estado == 429 or "resource_exhausted" in bajo or "rate limit" in bajo:
        return ErrorIA("Muchas preguntas seguidas. Espera unos segundos.", "limite", msg)
    if estado == 404 or "not found" in bajo and "model" in bajo:
        return ErrorIA("Ese modelo no está disponible para tu cuenta. Elige otro.", "modelo", msg)
    if estado == 403:
        return ErrorIA(f"{nombre} no deja usar esa clave aquí. Revisa los permisos de tu cuenta.", "clave", msg)
    if estado >= 500 or estado == 529:
        return ErrorIA(f"{nombre} está saturado. Intenta otra vez.", "servidor", msg)
    return ErrorIA(f"{nombre} rechazó la pregunta: {msg[:140]}", "peticion", msg)


# ---------------------------------------------------------------- HTTP

def _contexto_ssl():
    ctx = ssl.create_default_context()
    try:  # usa tambien los certificados de Windows
        ctx.load_default_certs()
    except Exception:
        pass
    return ctx


_CTX = _contexto_ssl()


def _http(metodo, url, cabeceras, cuerpo=None, timeout=60):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo, headers=dict(cabeceras))
    if datos is not None:
        req.add_header("content-type", "application/json")
    req.add_header("user-agent", "clw-gang")
    contexto = _CTX if url.startswith("https") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=contexto) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            texto = e.read().decode("utf-8", errors="replace")
        except Exception:
            texto = ""
        return e.code, texto
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise ErrorIA("No hay conexión a internet (o tardó demasiado).", "red", str(e))


def _base(proveedor, predeterminada):
    return os.environ.get(f"CLW_API_{proveedor.upper()}", predeterminada).rstrip("/")


# ---------------------------------------------------------------- variantes por proveedor

def _variantes(proveedor, preciso):
    if proveedor == "claude":
        if preciso:
            return [{"output_config": {"effort": "low"}}, {}]
        return [{"thinking": {"type": "disabled"}},
                {"thinking": {"type": "between_tools"}},
                {"output_config": {"effort": "low"}},
                {}]
    if proveedor == "gemini":
        if preciso:
            return [{"thinkingConfig": {"thinkingLevel": "low"}}, {}]
        return [{"thinkingConfig": {"thinkingLevel": "minimal"}},
                {"thinkingConfig": {"thinkingLevel": "low"}},
                {"thinkingConfig": {"thinkingBudget": 0}},
                {}]
    if proveedor == "openai":
        if preciso:
            return [{"reasoning_effort": "low"}, {}]
        return [{"reasoning_effort": "none"}, {"reasoning_effort": "minimal"}, {"reasoning_effort": "low"}, {}]
    return [{}]


def _peticion(proveedor, modelo, clave, sistema, b64, mime, texto, variante):
    """Devuelve (url, cabeceras, cuerpo) para una variante."""
    if proveedor == "claude":
        cuerpo = {
            "model": modelo,
            "max_tokens": 2000 if variante.get("thinking", {}).get("type") == "disabled" else 16000,
            "system": sistema,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": texto},
            ]}],
        }
        cuerpo.update(variante)
        cab = {"x-api-key": clave, "anthropic-version": "2023-06-01"}
        return _base("claude", "https://api.anthropic.com") + "/v1/messages", cab, cuerpo

    if proveedor == "gemini":
        config = {}
        config.update(variante)
        cuerpo = {
            "systemInstruction": {"parts": [{"text": sistema}]},
            "contents": [{"role": "user", "parts": [
                {"inlineData": {"mimeType": mime, "data": b64}},
                {"text": texto},
            ]}],
        }
        if config:
            cuerpo["generationConfig"] = config
        cab = {"x-goog-api-key": clave}
        url = _base("gemini", "https://generativelanguage.googleapis.com") + f"/v1beta/models/{modelo}:generateContent"
        return url, cab, cuerpo

    if proveedor == "openai":
        cuerpo = {
            "model": modelo,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": [
                    {"type": "text", "text": texto},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                ]},
            ],
            "max_completion_tokens": 3000 if variante.get("reasoning_effort") in ("none", "minimal") else 16000,
        }
        cuerpo.update(variante)
        cab = {"authorization": f"Bearer {clave}"}
        return _base("openai", "https://api.openai.com") + "/v1/chat/completions", cab, cuerpo

    raise ErrorIA("Proveedor desconocido", "otro")


def _extraer(proveedor, cuerpo_txt):
    """Devuelve (texto, se_corto)."""
    j = json.loads(cuerpo_txt)
    if proveedor == "claude":
        texto = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        return texto.strip(), j.get("stop_reason") == "max_tokens"
    if proveedor == "gemini":
        cands = j.get("candidates") or []
        if not cands:
            razon = (j.get("promptFeedback") or {}).get("blockReason")
            raise ErrorIA("Gemini no quiso contestar esa pregunta." if razon else "Gemini no devolvió respuesta.",
                          "peticion", cuerpo_txt[:300])
        partes = (cands[0].get("content") or {}).get("parts") or []
        texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
        return texto.strip(), cands[0].get("finishReason") == "MAX_TOKENS"
    if proveedor == "openai":
        ch = (j.get("choices") or [{}])[0]
        contenido = (ch.get("message") or {}).get("content") or ""
        if isinstance(contenido, list):
            contenido = "".join(p.get("text", "") for p in contenido if isinstance(p, dict))
        return contenido.strip(), ch.get("finish_reason") == "length"
    return "", False


# ---------------------------------------------------------------- cliente

class ClienteIA:
    def __init__(self):
        self._recordado = {}           # (proveedor, modelo, preciso) -> indice de variante
        self._candado = threading.Lock()

    def preguntar(self, proveedor, modelo, clave, sistema, b64, mime, texto, preciso=False, reintentos=1):
        if not clave:
            raise ErrorIA(f"Falta tu clave de {PROVEEDORES[proveedor].nombre}.", "clave")
        variantes = _variantes(proveedor, preciso)
        llave = (proveedor, modelo, preciso)
        inicio = self._recordado.get(llave, 0)
        ultimo = None
        i = inicio
        while i < len(variantes):
            url, cab, cuerpo = _peticion(proveedor, modelo, clave, sistema, b64, mime, texto, variantes[i])
            estado, resp = _http("POST", url, cab, cuerpo, timeout=90 if preciso else 60)
            if estado == 200:
                with self._candado:
                    self._recordado[llave] = i
                return _extraer(proveedor, resp)
            error = _traducir(proveedor, estado, resp)
            if estado == 400 and error.tipo == "peticion" and i + 1 < len(variantes):
                ultimo = error
                i += 1          # este modelo no acepta esta variante: se prueba la siguiente
                continue
            if error.tipo in ("limite", "servidor") and reintentos > 0:
                reintentos -= 1
                time.sleep(1.5)
                continue
            raise error
        raise ultimo or ErrorIA("No se pudo hablar con la IA.", "otro")


def validar_clave(proveedor, clave, timeout=20):
    """Revisa la clave con una consulta gratis (lista de modelos). Devuelve None si sirve o ErrorIA."""
    clave = (clave or "").strip()
    if not clave:
        return ErrorIA("Pega tu clave primero.", "clave")
    if proveedor == "claude":
        url = _base("claude", "https://api.anthropic.com") + "/v1/models?limit=1"
        cab = {"x-api-key": clave, "anthropic-version": "2023-06-01"}
    elif proveedor == "gemini":
        url = _base("gemini", "https://generativelanguage.googleapis.com") + "/v1beta/models?pageSize=1"
        cab = {"x-goog-api-key": clave}
    else:
        url = _base("openai", "https://api.openai.com") + "/v1/models"
        cab = {"authorization": f"Bearer {clave}"}
    try:
        estado, resp = _http("GET", url, cab, timeout=timeout)
    except ErrorIA as e:
        return e
    if estado == 200:
        return None
    return _traducir(proveedor, estado, resp)


def clave_parece_de(clave):
    """Adivina de que proveedor es una clave por como empieza."""
    clave = (clave or "").strip()
    if clave.startswith("sk-ant-"):
        return "claude"
    if clave.startswith("AIza"):
        return "gemini"
    if clave.startswith("sk-"):
        return "openai"
    return None
