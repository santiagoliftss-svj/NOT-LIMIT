"""Arma servidor/huellas.js desde la hoja de codigos (que NO se sube: solo sus huellas).

    python servidor/generar_huellas.py "NO LIMIT - codigos de licencia.csv"

Cada codigo queda como huella rapida (PBKDF2 2000 vueltas, para que el servidor gratis la calcule en <1 ms)
-> [numero, huella lenta de la app]. Con la huella no se puede sacar el codigo.
"""
import csv
import hashlib
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "app"))
from clw import licencia  # noqa: E402
from clw.licencias_validas import HUELLAS  # noqa: E402

SAL_RAPIDA = b"NO-LIMIT-SRV-1"
VUELTAS_RAPIDA = 2000


def rapida(normal):
    return hashlib.pbkdf2_hmac("sha256", normal.encode("ascii"), SAL_RAPIDA, VUELTAS_RAPIDA).hex()


def main(ruta):
    filas = {}
    with open(ruta, encoding="utf-8-sig") as f:
        for r in csv.reader(f):
            if not r or not r[0].strip().isdigit():
                continue
            num, codigo = int(r[0]), r[1].strip()
            n = licencia.normalizar(codigo)
            h = licencia.huella(n)
            if HUELLAS.get(h) != num:
                raise SystemExit(f"el codigo #{num} no coincide con la app")
            filas[rapida(n)] = [num, h]
    salida = os.path.join(AQUI, "huellas.js")
    with open(salida, "w", encoding="utf-8") as f:
        f.write("// Generado por generar_huellas.py: huella rapida -> [numero, huella de la app]. Sin codigos.\n")
        f.write("export const HUELLAS = " + json.dumps(filas, sort_keys=True, separators=(",", ":")).replace("],", "],\n") + ";\n")
    print(f"{len(filas)} codigos -> {salida}")


if __name__ == "__main__":
    main(sys.argv[1])
