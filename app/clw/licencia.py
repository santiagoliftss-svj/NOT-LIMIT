"""Licencia de NO LIMIT: sin un codigo pagado la app no arranca.

Cada cliente recibe un codigo (NL-XXXX-XXXX-XXXX). La app NO trae los codigos: solo su huella (PBKDF2 lenta, con sal),
asi que leyendo la app no se puede sacar ninguno. Desde la pagina (licencias.json) se pueden agregar huellas
nuevas o bloquear un codigo que se compartio, sin sacar otra version."""

import hashlib
import json
import logging
import os
import threading
import urllib.request

from . import rutas, version
from .licencias_validas import HUELLAS

log = logging.getLogger("clw.licencia")

SAL = b"NO-LIMIT-LIC-2"
VUELTAS = 120_000                                   # huella lenta: probar codigos a lo loco no sirve
ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"      # sin I, L, O ni U (no se confunden al escribirlo)
LARGO = 12
URL = version.PAGINA + "licencias.json"
PRUEBA = False                                       # (solo las pruebas automaticas)

_remoto = {"extra": set(), "bloqueadas": set()}
_cargado = False
_candado = threading.Lock()


def normalizar(texto):
    t = "".join(ch for ch in str(texto or "").upper() if ch.isalnum())
    if t.startswith("NL") and len(t) == LARGO + 2:
        t = t[2:]
    return t.replace("O", "0").replace("I", "1").replace("L", "1")


def formatear(texto):
    n = normalizar(texto)
    return "NL-" + "-".join(n[i:i + 4] for i in range(0, len(n), 4))


_memo = {}


def huella(texto):
    n = normalizar(texto)
    h = _memo.get(n)
    if h is None:
        h = hashlib.pbkdf2_hmac("sha256", n.encode("ascii", "ignore"), SAL, VUELTAS).hex()
        if len(_memo) < 64:
            _memo[n] = h
    return h


def parece_licencia(texto):
    t = str(texto or "").strip().upper()
    return t.startswith("NL-") or (t.startswith("NL") and len(normalizar(t)) == LARGO)


def _ruta_cache():
    return os.path.join(rutas.carpeta_datos(), "licencias.json")


def _aplicar(datos):
    extra = {str(h).lower() for h in datos.get("extra", []) if isinstance(h, str) and len(h) == 64}
    bloq = {str(h).lower() for h in datos.get("bloqueadas", []) if isinstance(h, str) and len(h) == 64}
    with _candado:
        _remoto["extra"], _remoto["bloqueadas"] = extra, bloq


def _cargar_cache():
    global _cargado
    if _cargado:
        return
    _cargado = True
    try:
        with open(_ruta_cache(), encoding="utf-8") as f:
            _aplicar(json.load(f))
    except (OSError, ValueError, AttributeError):
        pass


def valido(texto):
    n = normalizar(texto)
    if len(n) != LARGO or any(ch not in ALFABETO for ch in n):
        return False
    _cargar_cache()
    h = huella(n)
    with _candado:
        if h in _remoto["bloqueadas"]:
            return False
        return h in HUELLAS or h in _remoto["extra"]


def activa(config):
    if PRUEBA:
        return True
    try:
        return valido(config.get("licencia") or "")
    except Exception:
        return False


def refrescar(timeout=8):
    """Baja la lista de la pagina (codigos agregados o bloqueados) y la guarda para cuando no haya internet."""
    req = urllib.request.Request(URL, headers={"user-agent": "no-limit", "cache-control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        datos = json.loads(r.read(512 * 1024).decode("utf-8"))
    if not isinstance(datos, dict):
        return
    _aplicar(datos)
    try:
        os.makedirs(os.path.dirname(_ruta_cache()), exist_ok=True)
        tmp = _ruta_cache() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"extra": sorted(_remoto["extra"]), "bloqueadas": sorted(_remoto["bloqueadas"])}, f)
        os.replace(tmp, _ruta_cache())
    except OSError:
        pass


def refrescar_en_fondo():
    def trabajo():
        _cargar_cache()
        try:
            refrescar()
        except Exception as ex:
            log.info("no se pudo revisar la lista de licencias: %s", ex)
    threading.Thread(target=trabajo, name="licencias", daemon=True).start()
