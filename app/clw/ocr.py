"""Lectura de texto en pantalla con tesseract.exe (viene dentro de la app)."""

import os
import subprocess
import tempfile
import threading

from . import rutas

_SIN_VENTANA = 0x08000000 if rutas.WINDOWS else 0  # CREATE_NO_WINDOW


class OCR:
    def __init__(self, idioma="spa"):
        self.exe, self.tessdata = rutas.tesseract()
        self.idioma = idioma
        self._idiomas = None
        self._candado = threading.Lock()

    @property
    def disponible(self):
        return bool(self.exe)

    def _entorno(self):
        env = dict(os.environ)
        if self.tessdata:
            env["TESSDATA_PREFIX"] = self.tessdata
        return env

    def idiomas(self):
        if self._idiomas is None and self.exe:
            try:
                p = subprocess.run([self.exe, "--list-langs"], capture_output=True, env=self._entorno(),
                                   timeout=20, creationflags=_SIN_VENTANA)
                texto = (p.stdout or b"").decode("utf-8", "ignore") + (p.stderr or b"").decode("utf-8", "ignore")
                self._idiomas = [l.strip() for l in texto.splitlines()[1:] if l.strip() and " " not in l.strip()]
            except Exception:
                self._idiomas = []
        return self._idiomas or []

    def idioma_usable(self):
        lista = self.idiomas()
        if self.idioma in lista:
            return self.idioma
        if "eng" in lista:
            return "eng"
        return self.idioma

    def datos(self, imagen, psm=11):
        """Corre tesseract y devuelve un dict estilo pytesseract.image_to_data."""
        if not self.exe:
            raise RuntimeError("No hay OCR instalado")
        fd, entrada = tempfile.mkstemp(suffix=".png", prefix="clw_")
        os.close(fd)
        salida = entrada[:-4] + "_out"
        try:
            imagen.save(entrada, format="PNG")
            cmd = [self.exe, entrada, salida, "--psm", str(psm), "-l", self.idioma_usable(),
                   "-c", "tessedit_create_tsv=1"]
            p = subprocess.run(cmd, capture_output=True, env=self._entorno(), timeout=40,
                               creationflags=_SIN_VENTANA)
            if p.returncode != 0:
                raise RuntimeError((p.stderr or b"").decode("utf-8", "ignore")[:300] or "tesseract fallo")
            with open(salida + ".tsv", "r", encoding="utf-8", errors="replace") as f:
                return _parsear_tsv(f.read())
        finally:
            for ruta in (entrada, salida + ".tsv"):
                try:
                    os.remove(ruta)
                except OSError:
                    pass


_COLUMNAS = ["level", "page_num", "block_num", "par_num", "line_num", "word_num",
             "left", "top", "width", "height", "conf", "text"]


def _parsear_tsv(texto):
    d = {c: [] for c in _COLUMNAS}
    lineas = texto.splitlines()
    for linea in lineas[1:]:
        partes = linea.split("\t")
        if len(partes) < 11:
            continue
        if len(partes) == 11:
            partes.append("")
        try:
            numeros = [int(v) for v in partes[:10]]
            conf = float(partes[10])
        except ValueError:
            continue
        for c, v in zip(_COLUMNAS[:10], numeros):
            d[c].append(v)
        d["conf"].append(conf)
        d["text"].append("\t".join(partes[11:]))
    return d
