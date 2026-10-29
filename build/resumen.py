"""Lee autoprueba/resultado.json, lo muestra y deja avisos en GitHub Actions. Sale con 1 si falla algo obligatorio."""

import json
import os
import sys

ruta = sys.argv[1] if len(sys.argv) > 1 else "autoprueba/resultado.json"
if not os.path.exists(ruta):
    print("::error title=autoprueba::No se genero resultado.json (la app no arranco)")
    sys.exit(1)

with open(ruta, encoding="utf-8") as f:
    r = json.load(f)

obligatorias = ("ocr", "motor", "proveedores", "cifrado", "interfaz", "ventana")
lineas = []
mal = False
for nombre, dato in r.items():
    if nombre.startswith("_"):
        continue
    ok = dato.get("ok")
    marca = "OK" if ok else "FALLA"
    extra = dato.get("error") or json.dumps(dato.get("detalle"), ensure_ascii=False, default=str)[:600]
    lineas.append(f"{marca:6} {nombre}: {extra}")
    if not ok and nombre in obligatorias:
        mal = True
        print(f"::error title=autoprueba {nombre}::{extra}")
    elif not ok:
        print(f"::warning title=autoprueba {nombre}::{extra}")
    if not ok and dato.get("traza"):
        print(dato["traza"])

texto = "\n".join(lineas)
print(texto)
print("::notice title=autoprueba resumen::" + texto.replace("\n", " %0A "))
resumen = os.environ.get("GITHUB_STEP_SUMMARY")
if resumen:
    with open(resumen, "a", encoding="utf-8") as f:
        f.write("### Autoprueba\n```\n" + texto + "\n```\n")
sys.exit(1 if mal else 0)
