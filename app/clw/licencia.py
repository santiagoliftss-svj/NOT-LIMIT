"""Suscripcion de NO LIMIT: sin un codigo pagado y al corriente la app no arranca.

- Cada cliente tiene un codigo (NL-XXXX-XXXX-XXXX). El codigo ES su cuenta: con el entra a la app y a la pagina.
- La app NO trae los codigos: solo su huella (PBKDF2 lenta, con sal) y el numero de cada uno, asi que leyendo la app
  no se puede sacar ninguno.
- En la pagina (licencias.json) esta hasta cuando esta pagado cada numero: {"vencen": {"1": "2026-12-13"}}. Si no
  paga, se vence solo; si se comparte, se bloquea. La app revisa la lista al abrir y cada 3 horas.
- La fecha de "hoy" sale del servidor (cabecera Date), asi no sirve atrasar el reloj de la compu.
"""

import datetime as dt
import email.utils
import hashlib
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import rutas, version
from .licencias_validas import HUELLAS

log = logging.getLogger("clw.licencia")

SAL = b"NO-LIMIT-LIC-2"
VUELTAS = 120_000                                   # huella lenta: probar codigos a lo loco no sirve
ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"      # sin I, L, O ni U (no se confunden al escribirlo)
LARGO = 12
URL = version.PAGINA + "licencias.json"
PRECIO = "desde 99 pesos al mes"
# Planes: Basico (lo esencial), Pro (todo) y Premium (todo + atencion 1 a 1). Los codigos que no dicen plan son Pro.
PLANES = {"basico": "Básico", "pro": "Pro", "premium": "Premium"}
PLAN_NORMAL = "pro"
# Lo que contesta el plan Basico; lo demas (graficas, problemas, menus, arrastrar...) es del Pro
TIPOS_BASICO = {"opcion_unica", "opcion_multiple", "verdadero_falso", "abierta", "opcion", "otra", ""}
REVISAR_CADA = 3 * 3600                             # la app vuelve a ver la lista cada 3 horas
SIN_REVISAR_MAX = 3 * 24 * 3600                     # sin poder revisarla en 3 dias: pide internet
PRUEBA = False                                       # (solo las pruebas automaticas)

_remoto = {"extra": {}, "bloqueadas": set(), "vencen": {}, "planes": {}, "hoy": "", "revisado": 0.0,
           "servidor": "", "duenos": set()}
_uso = {}                                            # lo ultimo que dijo el servidor: usadas, limite, restantes
_cargado = False
_candado = threading.Lock()
_memo = {}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def normalizar(texto):
    t = "".join(ch for ch in str(texto or "").upper() if ch.isalnum())
    if t.startswith("NL") and len(t) == LARGO + 2:
        t = t[2:]
    return t.replace("O", "0").replace("I", "1").replace("L", "1")


def formatear(texto):
    n = normalizar(texto)
    return "NL-" + "-".join(n[i:i + 4] for i in range(0, len(n), 4))


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


def fecha_corta(iso):
    try:
        d = dt.date.fromisoformat(iso)
        return f"{d.day} {MESES[d.month - 1]}"
    except (TypeError, ValueError):
        return str(iso or "")


# ---------------------------------------------------------------- la lista de la pagina

def _ruta_cache():
    return os.path.join(rutas.carpeta_datos(), "licencias.json")


def _aplicar(datos, hoy=None, revisado=None):
    extra = datos.get("extra") or {}
    if isinstance(extra, list):                       # (formato de la 1.5: solo huellas)
        extra = {h: None for h in extra}
    extra = {str(h).lower(): (int(n) if str(n).isdigit() else None) for h, n in extra.items()
             if isinstance(h, str) and len(h) == 64}
    codigos = datos.get("codigos") or {}
    if isinstance(codigos, dict):
        for h, n in codigos.items():
            if isinstance(h, str) and len(h) == 64 and str(n).isdigit():
                extra.setdefault(h.lower(), int(n))
    bloq = {str(h).lower() for h in datos.get("bloqueadas", []) if isinstance(h, str)}
    planes = {}
    for n, pl in (datos.get("planes") or {}).items():
        if str(n).isdigit() and str(pl).lower() in PLANES:
            planes[int(n)] = str(pl).lower()
    vencen = {}
    for n, f in (datos.get("vencen") or {}).items():
        try:
            vencen[int(n)] = dt.date.fromisoformat(str(f)).isoformat()
        except (TypeError, ValueError):
            continue
    servidor = str(datos.get("servidor") or "").strip().rstrip("/")
    if not servidor.startswith("https://"):
        servidor = ""
    duenos = {int(n) for n in (datos.get("duenos") or []) if str(n).isdigit()}
    with _candado:
        _remoto["extra"], _remoto["bloqueadas"], _remoto["vencen"] = extra, bloq, vencen
        _remoto["planes"] = planes
        _remoto["servidor"], _remoto["duenos"] = servidor, duenos
        if hoy:
            _remoto["hoy"] = hoy
        if revisado is not None:
            _remoto["revisado"] = revisado


def _cargar_cache():
    global _cargado
    if _cargado:
        return
    _cargado = True
    try:
        with open(_ruta_cache(), encoding="utf-8") as f:
            datos = json.load(f)
        _aplicar(datos, datos.get("_hoy") or "", float(datos.get("_revisado") or 0))
    except (OSError, ValueError, AttributeError, TypeError):
        pass


def refrescar(timeout=8):
    """Baja la lista de la pagina y la guarda (con la fecha del servidor) para cuando no haya internet."""
    req = urllib.request.Request(f"{URL}?t={int(time.time())}",
                                 headers={"user-agent": "no-limit", "cache-control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        crudo = r.read(2 * 1024 * 1024)
        fecha = r.headers.get("date")
    datos = json.loads(crudo.decode("utf-8"))
    if not isinstance(datos, dict):
        return
    hoy = ""
    try:
        hoy = email.utils.parsedate_to_datetime(fecha).date().isoformat() if fecha else ""
    except (TypeError, ValueError):
        hoy = ""
    _cargar_cache()
    ahora = time.time()
    _aplicar(datos, hoy, ahora)
    try:
        os.makedirs(os.path.dirname(_ruta_cache()), exist_ok=True)
        tmp = _ruta_cache() + ".tmp"
        guardar = dict(datos)
        guardar["_hoy"], guardar["_revisado"] = _remoto["hoy"], ahora
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(guardar, f)
        os.replace(tmp, _ruta_cache())
    except OSError:
        pass


def refrescar_en_fondo(al_terminar=None):
    def trabajo():
        _cargar_cache()
        try:
            refrescar()
        except Exception as ex:
            log.info("no se pudo revisar la lista de licencias: %s", ex)
        if al_terminar:
            try:
                al_terminar()
            except Exception:
                pass
    threading.Thread(target=trabajo, name="licencias", daemon=True).start()


# ---------------------------------------------------------------- el estado de un codigo

class Estado:
    def __init__(self, activa, motivo, numero=None, vence=None, plan=PLAN_NORMAL):
        self.activa = activa
        self.motivo = motivo          # ok | sin_codigo | codigo | bloqueado | sin_activar | vencido | sin_revisar
        self.numero = numero
        self.vence = vence            # "AAAA-MM-DD" o None
        self.plan = plan if plan in PLANES else PLAN_NORMAL
        self.propio = ""              # mensaje del servidor (ej. "ya se usa en otra compu")

    @property
    def nombre_plan(self):
        return PLANES[self.plan]

    @property
    def mensaje(self):
        if self.propio:
            return self.propio
        if self.motivo == "ok":
            p = f"Plan {self.nombre_plan} · "
            return p + (f"activa hasta el {fecha_corta(self.vence)}." if self.vence else "activa.")
        if self.motivo == "sin_codigo":
            return "Pega tu código de NO LIMIT para empezar."
        if self.motivo == "codigo":
            return ("Ese código no sirve. Revisa que esté completo (NL-XXXX-XXXX-XXXX) "
                    "o pídele uno a quien te vendió NO LIMIT.")
        if self.motivo == "bloqueado":
            return "Ese código está bloqueado. Pídele uno nuevo a quien te vendió NO LIMIT."
        if self.motivo == "sin_activar":
            return "Tu código todavía no está activado. Paga tu mes y pídele a tu vendedor que lo active."
        if self.motivo == "vencido":
            return (f"Tu mes venció el {fecha_corta(self.vence)}. Renueva tu plan y vuelve a "
                    "tocar GUARDAR.")
        if self.motivo == "sin_revisar":
            return "Conéctate a internet para revisar tu suscripción y vuelve a tocar GUARDAR."
        return "No se pudo revisar tu código."


def hoy():
    """La fecha de hoy: la mas nueva entre el reloj de la compu y la del servidor (no sirve atrasar el reloj)."""
    local = dt.date.today().isoformat()
    with _candado:
        servidor = _remoto["hoy"]
    return max(local, servidor) if servidor else local


def numero(texto):
    n = normalizar(texto)
    if len(n) != LARGO or any(ch not in ALFABETO for ch in n):
        return None
    _cargar_cache()
    h = huella(n)
    with _candado:
        if h in HUELLAS:
            return HUELLAS[h]
        if h in _remoto["extra"]:
            return _remoto["extra"][h] or 0
        return None


def estado_codigo(texto, ahora=None):
    if not str(texto or "").strip():
        return Estado(False, "sin_codigo")
    num = numero(texto)
    if num is None:
        return Estado(False, "codigo")
    h = huella(texto)
    ahora = time.time() if ahora is None else ahora
    with _candado:
        bloqueado = h in _remoto["bloqueadas"]
        vence = _remoto["vencen"].get(num)
        revisado = _remoto["revisado"]
        plan = _remoto["planes"].get(num, PLAN_NORMAL)
    if bloqueado:
        return Estado(False, "bloqueado", num, vence)
    if not revisado or ahora - revisado > SIN_REVISAR_MAX:
        return Estado(False, "sin_revisar", num, vence)
    if not vence:
        return Estado(False, "sin_activar", num)
    if vence < hoy():
        return Estado(False, "vencido", num, vence, plan)
    return Estado(True, "ok", num, vence, plan)


def permite(plan, tipo):
    """True si ese plan contesta ese tipo de pregunta (el Basico solo lo esencial)."""
    if plan != "basico":
        return True
    return str(tipo or "").strip().lower() in TIPOS_BASICO


def estado(config):
    if PRUEBA:
        return Estado(True, "ok")
    try:
        return estado_codigo(config.get("licencia") or "")
    except Exception as e:
        log.warning("licencia: %s", e)
        return Estado(False, "sin_revisar")


def activa(config):
    return estado(config).activa


def valido(texto):
    """True si el codigo existe (aunque este vencido): sirve para distinguir 'no existe' de 'no esta pagado'."""
    try:
        return numero(texto) is not None
    except Exception:
        return False


def necesita_revisar():
    with _candado:
        return time.time() - _remoto["revisado"] > REVISAR_CADA


# ---------------------------------------------------------------- el servidor de NO LIMIT (la IA incluida en el plan)

# Las IAs de cada plan (igual que en el servidor, que es el que manda). Las ligeras van incluidas: con ellas se
# ubica y se revisa la pregunta.
_BASICO = ["gemini-flash-lite-latest"]
_PRO = _BASICO + ["gemini-flash-latest", "claude-haiku-5-5", "gpt-6-luna"]
_PREMIUM = _PRO + ["gemini-pro-latest", "claude-sonnet-5-5", "claude-opus-5-5", "gpt-6.1-terra"]
PLAN_MODELOS = {"basico": _BASICO, "pro": _PRO, "premium": _PREMIUM}
PESOS = {"gemini-pro-latest": 2, "claude-sonnet-5-5": 2, "gpt-6.1-terra": 2, "claude-opus-5-5": 5}
PREDETERMINADO = {"basico": "gemini-flash-lite-latest", "pro": "gemini-flash-latest", "premium": "gemini-flash-latest"}


def servidor():
    """URL del servidor de NO LIMIT ('' si todavia no hay): con el, la IA va incluida y nadie pone claves."""
    propio = os.environ.get("CLW_SERVIDOR", "").strip().rstrip("/")
    if propio:
        return propio
    if PRUEBA:                                       # (la prueba automatica usa su IA de mentiras)
        return ""
    _cargar_cache()
    with _candado:
        return _remoto["servidor"]


def es_dueno(config):
    try:
        num = numero(config.get("licencia") or "")
    except Exception:
        return False
    with _candado:
        return num is not None and num in _remoto["duenos"]


def peso(modelo):
    """Cuantas preguntas cuenta una pregunta con esa IA (las caras cuentan mas)."""
    return PESOS.get(modelo, 1)


def permitidos(config):
    """Las IAs que puede usar con su plan (el dueno, todas)."""
    if es_dueno(config):
        return list(_PREMIUM)
    try:
        plan = estado(config).plan
    except Exception:
        plan = PLAN_NORMAL
    return list(PLAN_MODELOS.get(plan, _PRO))


def plan_de_modelo(modelo):
    """'Pro' o 'Premium': el plan mas barato que trae esa IA."""
    for clave in ("basico", "pro", "premium"):
        if modelo in PLAN_MODELOS[clave]:
            return PLANES[clave]
    return PLANES["premium"]


def modelo_efectivo(config):
    """El modelo que de verdad se usa. Con servidor: la IA que eligio (si viene en su plan) sin clave."""
    if servidor():
        elegido = str(config.get("modelo_servidor") or "")
        ok = permitidos(config)
        if elegido in ok:
            return elegido
        try:
            plan = estado(config).plan
        except Exception:
            plan = PLAN_NORMAL
        return PREDETERMINADO.get(plan, ok[0])
    return str(config.get("modelo") or "")


def equipo():
    """Id de esta compu (para que un codigo no se use en mas compus de las del plan). No dice nada de la compu."""
    global _equipo
    if _equipo:
        return _equipo
    crudo = ""
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
                crudo = str(winreg.QueryValueEx(k, "MachineGuid")[0])
        elif sys.platform == "darwin":
            import subprocess
            salida = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True,
                                    text=True, timeout=5).stdout
            for linea in salida.splitlines():
                if "IOPlatformUUID" in linea:
                    crudo = linea.split("=")[-1].strip().strip('"')
    except Exception as e:
        log.info("no se pudo leer el id de la compu: %s", e)
    if not crudo:
        ruta = os.path.join(rutas.carpeta_datos(), "equipo.txt")
        try:
            with open(ruta, encoding="utf-8") as f:
                crudo = f.read().strip()
        except OSError:
            crudo = ""
        if not crudo:
            crudo = uuid.uuid4().hex
            try:
                os.makedirs(os.path.dirname(ruta), exist_ok=True)
                with open(ruta, "w", encoding="utf-8") as f:
                    f.write(crudo)
            except OSError:
                pass
    _equipo = hashlib.sha256(("NL-EQUIPO|" + crudo).encode("utf-8")).hexdigest()[:32]
    return _equipo


_equipo = ""


def anotar_uso(restantes=None, limite=None, usadas=None):
    with _candado:
        if restantes is not None:
            _uso["restantes"] = restantes
        if limite is not None:
            _uso["limite"] = limite
        if usadas is not None:
            _uso["usadas"] = usadas


def uso():
    with _candado:
        return dict(_uso)


def consultar_servidor(codigo, timeout=10):
    """Pregunta al servidor como va el codigo (y registra esta compu). Devuelve (True, datos) o (False, mensaje)."""
    url = servidor()
    if not url:
        return True, {}
    req = urllib.request.Request(url + "/estado", headers={
        "user-agent": "no-limit", "x-nl-codigo": formatear(codigo), "x-nl-equipo": equipo(),
        "x-nl-version": version.VERSION})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl()) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = (json.loads(e.read().decode("utf-8")).get("error") or {}).get("message")
        except Exception:
            msg = None
        if e.code in (401, 402, 403) and msg:
            return False, msg
        return True, {}                              # el servidor fallo: no se le cierra la puerta al cliente
    except Exception as e:
        log.info("no se pudo consultar el servidor: %s", e)
        return True, {}
    anotar_uso(datos.get("restantes"), datos.get("limite"), datos.get("usadas"))
    return True, datos


def _ssl():
    from . import proveedores
    return proveedores._CTX
