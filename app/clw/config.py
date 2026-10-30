"""Ajustes del usuario. Las API keys se guardan cifradas con la cuenta de Windows (DPAPI)."""

import base64
import ctypes
import json
import os
import threading

from . import rutas

VERSION_AJUSTES = 2

_PREDETERMINADO = {
    "version_ajustes": VERSION_AJUSTES,
    "modelo": "claude-haiku-5-5",
    "claves": {},
    "modo_preciso": True,
    "guardar_capturas": True,
    "modelos_propios": {},   # para cambiar el id de un modelo sin actualizar la app
}

_candado = threading.Lock()


# ---------------------------------------------------------------- cifrado

class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(datos, cifrar):
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(datos, len(datos))
    entrada = _BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    salida = _BLOB()
    funcion = crypt32.CryptProtectData if cifrar else crypt32.CryptUnprotectData
    ok = funcion(ctypes.byref(entrada), None, None, None, None, 0x01, ctypes.byref(salida))  # 0x01 = sin ventanas
    if not ok:
        raise OSError("DPAPI fallo")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        kernel32.LocalFree(salida.pbData)


def proteger(texto):
    datos = texto.encode("utf-8")
    if rutas.WINDOWS:
        try:
            return "dpapi:" + base64.b64encode(_dpapi(datos, True)).decode("ascii")
        except Exception:
            pass
    return "b64:" + base64.b64encode(datos).decode("ascii")


def desproteger(valor):
    if not valor:
        return ""
    try:
        if valor.startswith("dpapi:"):
            return _dpapi(base64.b64decode(valor[6:]), False).decode("utf-8")
        if valor.startswith("b64:"):
            return base64.b64decode(valor[4:]).decode("utf-8")
    except Exception:
        return ""
    return ""


# ---------------------------------------------------------------- ajustes

class Config:
    def __init__(self, ruta=None):
        self.ruta = ruta or os.path.join(rutas.carpeta_datos(), "ajustes.json")
        self.datos = json.loads(json.dumps(_PREDETERMINADO))
        self.cargar()

    def cargar(self):
        try:
            with open(self.ruta, "r", encoding="utf-8") as f:
                guardado = json.load(f)
            if isinstance(guardado, dict):
                for k, v in guardado.items():
                    if k in self.datos and isinstance(v, type(self.datos[k])):
                        self.datos[k] = v
                if guardado.get("version_ajustes", 1) < 2:
                    self.datos["modo_preciso"] = True   # 1.1: pensar antes de contestar por defecto
                    self.datos["version_ajustes"] = VERSION_AJUSTES
        except (OSError, ValueError):
            pass

    def guardar(self):
        with _candado:
            tmp = self.ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.datos, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.ruta)

    # claves
    def clave(self, proveedor):
        return desproteger(self.datos["claves"].get(proveedor, ""))

    def tiene_clave(self, proveedor):
        return bool(self.clave(proveedor))

    def poner_clave(self, proveedor, texto):
        texto = (texto or "").strip()
        if texto:
            self.datos["claves"][proveedor] = proteger(texto)
        else:
            self.datos["claves"].pop(proveedor, None)
        self.guardar()

    # atajos
    def __getitem__(self, k):
        return self.datos[k]

    def __setitem__(self, k, v):
        self.datos[k] = v
        self.guardar()
