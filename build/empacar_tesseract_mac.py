"""Deja una copia de Tesseract que funciona sola (sin Homebrew) y la mete en NO LIMIT.app.

Uso (en una Mac con Homebrew, desde la raiz del repo):
    python build/empacar_tesseract_mac.py preparar            -> build/tesseract_mac (programa + librerias + tessdata)
    python build/empacar_tesseract_mac.py meter "dist/NO LIMIT.app"   -> Contents/Resources/tesseract y firma ad-hoc

Las librerias de las que depende se copian a libs/ y se les cambian las rutas a @executable_path/libs/ (asi no
importa donde quede instalada la app). Todo se firma ad-hoc (en Apple Silicon el codigo sin firma no corre).
"""

import os
import re
import shutil
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(AQUI, "tesseract_mac")
TESSDATA = "https://github.com/tesseract-ocr/tessdata/raw/main/{}.traineddata"   # los mismos que en Windows


def correr(*args, **k):
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, check=True, capture_output=True, text=True, **k).stdout


def brew_prefijo(formula):
    return correr("brew", "--prefix", formula).strip()


def dependencias(archivo):
    salida = correr("otool", "-L", archivo).splitlines()[1:]
    deps = []
    for linea in salida:
        ruta = linea.strip().split(" (compatibility")[0].strip()
        if ruta:
            deps.append(ruta)
    return deps


def rpaths(archivo):
    texto = correr("otool", "-l", archivo)
    return re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset", texto)


def es_sistema(ruta):
    return ruta.startswith("/usr/lib/") or ruta.startswith("/System/")


def resolver(ref, desde, programa):
    base = os.path.dirname(os.path.realpath(desde))
    if ref.startswith("@loader_path/"):
        return os.path.realpath(os.path.join(base, ref[len("@loader_path/"):]))
    if ref.startswith("@executable_path/"):
        return os.path.realpath(os.path.join(os.path.dirname(programa), ref[len("@executable_path/"):]))
    if ref.startswith("@rpath/"):
        nombre = ref[len("@rpath/"):]
        candidatos = []
        for rp in rpaths(desde):
            rp = rp.replace("@loader_path", base).replace("@executable_path", os.path.dirname(programa))
            candidatos.append(os.path.join(rp, nombre))
        candidatos += [os.path.join("/opt/homebrew/lib", nombre), os.path.join(base, nombre)]
        for c in candidatos:
            if os.path.exists(c):
                return os.path.realpath(c)
        raise FileNotFoundError(f"no encontre {ref} (usada por {desde})")
    return os.path.realpath(ref)


def preparar():
    for formula in ("tesseract",):
        if subprocess.run(["brew", "list", formula], capture_output=True).returncode != 0:
            correr("brew", "install", formula)
    origen = os.path.join(brew_prefijo("tesseract"), "bin", "tesseract")
    programa_original = os.path.realpath(origen)
    if os.path.isdir(DEST):
        shutil.rmtree(DEST)
    libs = os.path.join(DEST, "libs")
    os.makedirs(libs)
    os.makedirs(os.path.join(DEST, "tessdata", "configs"))
    programa = os.path.join(DEST, "tesseract")
    shutil.copy2(programa_original, programa)
    os.chmod(programa, 0o755)

    # 1) juntar todas las librerias que no son del sistema
    nombres = {}                         # ruta real -> nombre dentro de libs/
    pendientes = [(programa_original, programa_original)]
    vistos = set()
    while pendientes:
        archivo, _ = pendientes.pop()
        if archivo in vistos:
            continue
        vistos.add(archivo)
        for ref in dependencias(archivo):
            if es_sistema(ref):
                continue
            real = resolver(ref, archivo, programa_original)
            if real == os.path.realpath(archivo):
                continue                 # (el id de la propia libreria)
            if real not in nombres:
                nombre = os.path.basename(ref)
                nombres[real] = nombre
                shutil.copy2(real, os.path.join(libs, nombre))
                os.chmod(os.path.join(libs, nombre), 0o755)
                pendientes.append((real, real))

    # 2) cambiar las rutas: todo apunta a @executable_path/libs/
    def arreglar(copia, original):
        for ref in dependencias(copia):
            if es_sistema(ref):
                continue
            real = resolver(ref, original, programa_original)
            if real in nombres:
                correr("install_name_tool", "-change", ref, "@executable_path/libs/" + nombres[real], copia)
        for rp in rpaths(copia):
            subprocess.run(["install_name_tool", "-delete_rpath", rp, copia], capture_output=True)

    arreglar(programa, programa_original)
    for real, nombre in nombres.items():
        copia = os.path.join(libs, nombre)
        correr("install_name_tool", "-id", "@executable_path/libs/" + nombre, copia)
        arreglar(copia, real)
    for f in [programa] + [os.path.join(libs, n) for n in nombres.values()]:
        correr("codesign", "--force", "-s", "-", f)

    # 3) tessdata con espanol e ingles
    for idioma in ("spa", "eng", "osd"):
        destino = os.path.join(DEST, "tessdata", idioma + ".traineddata")
        correr("curl", "-fsSL", "--retry", "3", "-o", destino, TESSDATA.format(idioma))
        if os.path.getsize(destino) < 500_000:
            raise RuntimeError(f"{idioma}.traineddata se bajo mal")
    configs = os.path.join(brew_prefijo("tesseract"), "share", "tessdata", "configs")
    if os.path.isdir(configs):
        for f in os.listdir(configs):
            shutil.copy2(os.path.join(configs, f), os.path.join(DEST, "tessdata", "configs", f))

    # 4) que no quede nada de Homebrew y que corra
    for f in [programa] + [os.path.join(libs, n) for n in nombres.values()]:
        for ref in dependencias(f):
            if not es_sistema(ref) and not ref.startswith("@executable_path/libs/"):
                raise RuntimeError(f"{f} todavia usa {ref}")
    env = dict(os.environ, TESSDATA_PREFIX=os.path.join(DEST, "tessdata"))
    print(subprocess.run([programa, "--version"], capture_output=True, text=True, env=env).stdout[:200])
    langs = subprocess.run([programa, "--list-langs"], capture_output=True, text=True, env=env)
    print(langs.stdout + langs.stderr)
    if "spa" not in langs.stdout + langs.stderr:
        raise RuntimeError("tesseract no ve el espanol")
    total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(DEST) for f in fs)
    print(f"Tesseract listo: {len(nombres)} librerias, {total / 1e6:.1f} MB")


def meter(app):
    destino = os.path.join(app, "Contents", "Resources", "tesseract")
    if os.path.isdir(destino):
        shutil.rmtree(destino)
    shutil.copytree(DEST, destino, symlinks=True)
    # la app entera otra vez firmada (ad-hoc), con el OCR adentro
    correr("codesign", "--force", "--deep", "-s", "-", app)
    print(correr("codesign", "--verify", "--deep", "--verbose=2", app) or "firma ok")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "preparar":
        preparar()
    elif len(sys.argv) >= 3 and sys.argv[1] == "meter":
        meter(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)
