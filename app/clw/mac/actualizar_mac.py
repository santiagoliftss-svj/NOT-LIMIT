"""Actualizacion sola en Mac: baja el DMG nuevo de la beta, y al cerrar (o al tocar Actualizar) reemplaza
NO LIMIT.app y la vuelve a abrir. Lo hace un scriptito aparte que espera a que la app se cierre."""

import json
import logging
import os
import platform
import re
import subprocess
import sys
import urllib.request

from .. import actualizar, rutas, version

log = logging.getLogger("clw.actualizar_mac")

API = f"https://api.github.com/repos/{version.REPO}/releases/tags/mac-beta"
NATIVA, INTEL = "NO-LIMIT-Mac.dmg", "NO-LIMIT-Mac-Intel.dmg"
APLICACIONES = "/Applications/NO LIMIT.app"

SCRIPT = r'''#!/bin/bash
# (lo corre NO LIMIT para actualizarse: espera a que se cierre, cambia la app y la vuelve a abrir)
PID="$1"; DMG="$2"; DEST="$3"; RELANZAR="$4"; REG="$5"
exec >>"$REG" 2>&1
echo "== actualizar $(date) -> $DEST"
for i in $(seq 1 150); do kill -0 "$PID" 2>/dev/null || break; sleep 0.2; done
MNT="$(mktemp -d /tmp/nolimit-mnt.XXXXXX)"
if ! hdiutil attach -nobrowse -noautoopen -readonly -mountpoint "$MNT" "$DMG"; then echo "no abrio el DMG"; exit 1; fi
NUEVA="$(find "$MNT" -maxdepth 1 -name '*.app' -print | head -1)"
if [ -z "$NUEVA" ]; then echo "el DMG no trae la app"; hdiutil detach "$MNT" -force; exit 1; fi
TMP="$DEST.nuevo"
rm -rf "$TMP"
if ! ditto "$NUEVA" "$TMP"; then echo "no se pudo copiar"; hdiutil detach "$MNT" -force; rm -rf "$TMP"; exit 1; fi
hdiutil detach "$MNT" -force >/dev/null 2>&1
rmdir "$MNT" 2>/dev/null
xattr -dr com.apple.quarantine "$TMP" 2>/dev/null
if ! codesign --verify --deep --strict "$TMP"; then echo "la app nueva no paso la revision"; rm -rf "$TMP"; exit 1; fi
if [ -e "$DEST" ]; then
  rm -rf "$DEST.viejo"
  if ! mv "$DEST" "$DEST.viejo"; then echo "no se pudo mover la vieja"; rm -rf "$TMP"; exit 1; fi
fi
if ! mv "$TMP" "$DEST"; then echo "no se pudo poner la nueva"; [ -e "$DEST.viejo" ] && mv "$DEST.viejo" "$DEST"; exit 1; fi
rm -rf "$DEST.viejo"
rm -f "$DMG"
echo "ok"
if [ "$RELANZAR" = "1" ]; then open "$DEST"; fi
exit 0
'''


def _traducida():
    """True si es la version Intel corriendo en un chip M (Rosetta)."""
    try:
        r = subprocess.run(["/usr/sbin/sysctl", "-n", "sysctl.proc_translated"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "1"
    except Exception:
        return False


def preferidos():
    if platform.machine() == "arm64":
        return [NATIVA]
    return [NATIVA, INTEL] if _traducida() else [INTEL]     # en M1-M4 con Rosetta: la nativa si ya existe


def buscar(timeout=8):
    """(version, url, tamano) si hay una version mas nueva para esta Mac; None si no."""
    req = urllib.request.Request(API, headers={"user-agent": "no-limit", "accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    m = re.search(r"NO LIMIT (\d+(?:\.\d+){1,3}) para Mac", d.get("body") or "")
    if not m:
        return None
    v = m.group(1)
    if actualizar.numero(v) <= actualizar.numero(version.VERSION):
        return None
    assets = {a.get("name"): a for a in d.get("assets") or []}
    for nombre in preferidos():
        a = assets.get(nombre)
        if a and a.get("browser_download_url"):
            return v, a["browser_download_url"], int(a.get("size") or 0)
    return v, None, 0


def descargar(v, url, tam=0, al_avance=None, cancelar=None):
    return actualizar.descargar(v, url, tam, al_avance=al_avance, cancelar=cancelar, nombre=f"NO-LIMIT-Mac-{v}.dmg")


def app_actual():
    """Donde esta NO LIMIT.app. Si corre desde el DMG o macOS la movio a una carpeta temporal, va a Aplicaciones."""
    exe = os.path.realpath(sys.executable)
    app = os.path.dirname(os.path.dirname(os.path.dirname(exe)))
    if not app.endswith(".app"):
        return None
    if "/AppTranslocation/" in app or app.startswith("/Volumes/"):
        return APLICACIONES
    return app


def escribir_script(carpeta=None):
    carpeta = carpeta or actualizar.carpeta()
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "actualizar.sh")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(SCRIPT)
    os.chmod(ruta, 0o755)
    return ruta


def instalar(ruta_dmg, relanzar=True, destino=None):
    destino = destino or app_actual()
    if not destino or not os.path.exists(ruta_dmg):
        return False
    try:
        script = escribir_script()
        reg = os.path.join(rutas.carpeta_datos(), "actualizacion", "actualizar.log")
        subprocess.Popen(["/bin/bash", script, str(os.getpid()), ruta_dmg, destino, "1" if relanzar else "0", reg],
                         start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=actualizar.entorno_limpio())
        log.info("actualizando: %s -> %s (relanzar=%s)", ruta_dmg, destino, relanzar)
        return True
    except OSError as ex:
        log.error("no se pudo actualizar: %s", ex)
        return False
