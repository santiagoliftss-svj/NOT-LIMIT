"""Donde vive cada cosa, tanto en desarrollo como dentro del .exe."""

import os
import shutil
import sys

CONGELADO = getattr(sys, "frozen", False)
WINDOWS = sys.platform == "win32"

if CONGELADO:
    CARPETA_APP = os.path.dirname(sys.executable)
    CARPETA_RECURSOS = getattr(sys, "_MEIPASS", CARPETA_APP)
else:
    CARPETA_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    CARPETA_RECURSOS = CARPETA_APP

ASSETS = os.path.join(CARPETA_RECURSOS, "assets")


def asset(*partes):
    return os.path.join(ASSETS, *partes)


def carpeta_datos():
    """Carpeta del usuario donde se guardan ajustes, registro y capturas."""
    base = os.environ.get("CLW_DATOS")
    if not base:
        if WINDOWS:
            raiz = os.environ.get("APPDATA") or os.path.expanduser("~")
            base = os.path.join(raiz, "NO LIMIT")
            viejo = os.path.join(raiz, "CLW GANG")       # antes se llamaba asi: se conservan claves y ajustes
            if not os.path.exists(base) and os.path.isdir(viejo):
                try:
                    os.rename(viejo, base)
                except OSError:
                    base = viejo
        else:
            base = os.path.join(os.path.expanduser("~"), ".clw-gang")
    os.makedirs(base, exist_ok=True)
    return base


def tesseract():
    """Devuelve (ruta_tesseract, carpeta_tessdata) o (None, None) si no hay OCR."""
    candidatos = []
    propio = os.environ.get("CLW_TESSERACT")
    if propio:
        candidatos.append(propio)
    nombre = "tesseract.exe" if WINDOWS else "tesseract"
    candidatos.append(os.path.join(CARPETA_APP, "tesseract", nombre))
    candidatos.append(os.path.join(os.path.dirname(CARPETA_APP), "tesseract", nombre))
    if WINDOWS:
        candidatos.append(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        candidatos.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"))
    en_path = shutil.which("tesseract")
    if en_path:
        candidatos.append(en_path)

    for ruta in candidatos:
        if ruta and os.path.isfile(ruta):
            tessdata = os.environ.get("TESSDATA_PREFIX")
            junto = os.path.join(os.path.dirname(ruta), "tessdata")
            if os.path.isdir(junto):
                tessdata = junto
            return ruta, tessdata
    return None, None
