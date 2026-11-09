"""Claves cifradas en Mac.

Una llave maestra al azar vive en el Llavero de macOS (servicio "NO LIMIT"). Las API keys se guardan en los
ajustes cifradas con esa llave (HMAC-SHA256 en modo contador + etiqueta para detectar cambios).

Al Llavero se entra con /usr/bin/security (herramienta de Apple): como ella crea el elemento, ella misma lo
puede leer sin preguntar, aunque NO LIMIT cambie de version.
"""

import base64
import hashlib
import hmac
import os
import subprocess
import threading

SERVICIO = "NO LIMIT"
CUENTA = "llave-ajustes"
SECURITY = "/usr/bin/security"

_cache = {}
_candado = threading.Lock()


def _correr(args, entrada=None):
    return subprocess.run([SECURITY] + list(args), input=entrada, capture_output=True, timeout=15)


def _leer():
    p = _correr(["find-generic-password", "-s", SERVICIO, "-a", CUENTA, "-w"])
    if p.returncode != 0:
        return None
    texto = (p.stdout or b"").decode("ascii", "ignore").strip()
    try:
        llave = bytes.fromhex(texto)
    except ValueError:
        return None
    return llave if len(llave) == 32 else None


def _crear():
    nueva = os.urandom(32).hex()
    # por la entrada estandar (modo interactivo): asi la llave no aparece en la lista de procesos
    orden = f'add-generic-password -U -s "{SERVICIO}" -a "{CUENTA}" -l "{SERVICIO}" -w "{nueva}"\n'
    _correr(["-i"], entrada=orden.encode("ascii"))
    if _leer() is None:
        _correr(["add-generic-password", "-U", "-s", SERVICIO, "-a", CUENTA, "-l", SERVICIO, "-w", nueva])


def llave():
    with _candado:
        if "llave" not in _cache:
            k = _leer()
            if k is None:
                _crear()
                k = _leer()
            if k is None:
                raise OSError("no se pudo usar el Llavero")
            _cache["llave"] = k
        return _cache["llave"]


def _llaves(maestra):
    return (hmac.new(maestra, b"NO LIMIT cifrar", hashlib.sha256).digest(),
            hmac.new(maestra, b"NO LIMIT firmar", hashlib.sha256).digest())


def _flujo(k, nonce, n):
    out = bytearray()
    i = 0
    while len(out) < n:
        out += hmac.new(k, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return bytes(out[:n])


def cifrar(datos, maestra=None):
    k_cif, k_fir = _llaves(maestra or llave())
    nonce = os.urandom(16)
    cuerpo = bytes(a ^ b for a, b in zip(datos, _flujo(k_cif, nonce, len(datos))))
    etiqueta = hmac.new(k_fir, nonce + cuerpo, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + cuerpo + etiqueta).decode("ascii")


def descifrar(texto, maestra=None):
    crudo = base64.b64decode(texto)
    if len(crudo) < 32:
        raise ValueError("dato muy corto")
    nonce, cuerpo, etiqueta = crudo[:16], crudo[16:-16], crudo[-16:]
    k_cif, k_fir = _llaves(maestra or llave())
    if not hmac.compare_digest(etiqueta, hmac.new(k_fir, nonce + cuerpo, hashlib.sha256).digest()[:16]):
        raise ValueError("la clave guardada no cuadra con este Llavero")
    return bytes(a ^ b for a, b in zip(cuerpo, _flujo(k_cif, nonce, len(cuerpo))))
