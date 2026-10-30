"""Actualizaciones: busca la version nueva en GitHub, la baja sola y la instala sin ventanas.

El instalador se corre con /VERYSILENT. Con /RELANZAR=1 vuelve a abrir NO LIMIT al terminar.
"""

import glob
import json
import logging
import os
import subprocess
import urllib.request

from . import rutas, version

log = logging.getLogger("clw")
API = f"https://api.github.com/repos/{version.REPO}/releases/latest"


def numero(texto):
    partes = []
    for p in str(texto).strip().lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        partes.append(int(num) if num else 0)
    return tuple(partes + [0] * (3 - len(partes)))


def buscar(timeout=8):
    """(version, url_del_instalador, tamano) si hay una version mas nueva que esta; si no, None."""
    req = urllib.request.Request(API, headers={"accept": "application/vnd.github+json", "user-agent": "no-limit"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        datos = json.load(r)
    tag = str(datos.get("tag_name") or "")
    if not tag or numero(tag) <= numero(version.VERSION):
        return None
    for a in datos.get("assets") or []:
        if str(a.get("name", "")).lower().endswith("setup.exe"):
            return tag.lstrip("vV"), a.get("browser_download_url"), int(a.get("size") or 0)
    return tag.lstrip("vV"), None, 0


def carpeta():
    return os.path.join(rutas.carpeta_datos(), "actualizacion")


def descargar(v, url, tam=0, al_avance=None, cancelar=None):
    """Baja el instalador. Devuelve la ruta, o None si no se pudo (o si quedo incompleto)."""
    os.makedirs(carpeta(), exist_ok=True)
    destino = os.path.join(carpeta(), f"NO-LIMIT-Setup-{v}.exe")
    if os.path.exists(destino) and (not tam or os.path.getsize(destino) == tam):
        return destino
    parcial = destino + ".parcial"
    req = urllib.request.Request(url, headers={"user-agent": "no-limit"})
    with urllib.request.urlopen(req, timeout=30) as r, open(parcial, "wb") as f:
        total = tam or int(r.headers.get("content-length") or 0)
        hecho, ultimo = 0, -1
        while True:
            if cancelar and cancelar():
                raise InterruptedError("descarga cancelada")
            bloque = r.read(256 * 1024)
            if not bloque:
                break
            f.write(bloque)
            hecho += len(bloque)
            if total and al_avance:
                pct = min(99, int(hecho * 100 / total))
                if pct != ultimo:
                    ultimo = pct
                    al_avance(pct)
    if tam and os.path.getsize(parcial) != tam:
        os.remove(parcial)
        log.warning("actualizacion incompleta (%s de %s bytes)", hecho, tam)
        return None
    os.replace(parcial, destino)
    for viejo in glob.glob(os.path.join(carpeta(), "NO-LIMIT-Setup-*")):
        if os.path.abspath(viejo) != os.path.abspath(destino):
            try:
                os.remove(viejo)
            except OSError:
                pass
    return destino


def instalar(ruta, relanzar=True):
    """Corre el instalador sin ventanas (cierra NO LIMIT, reemplaza los archivos y, si se pide, la vuelve a abrir)."""
    args = [ruta, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELANZAR=" + ("1" if relanzar else "0")]
    flags = (0x00000008 | 0x00000200) if rutas.WINDOWS else 0   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(args, creationflags=flags, close_fds=True)
        log.info("instalando actualizacion: %s (relanzar=%s)", ruta, relanzar)
        return True
    except OSError as ex:
        log.error("no se pudo correr el instalador: %s", ex)
        return False
