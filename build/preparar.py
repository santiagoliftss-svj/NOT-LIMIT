"""Escribe build/version_info.txt (datos del .exe) y la version para el instalador. Uso: python build/preparar.py"""

import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "app"))

from clw.version import VERSION  # noqa: E402

partes = [int(p) for p in VERSION.split(".")] + [0] * 4
v4 = tuple(partes[:4])

texto = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v4}, prodvers={v4}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040A04B0', [
      StringStruct('CompanyName', 'NO LIMIT'),
      StringStruct('FileDescription', 'NO LIMIT'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'NO LIMIT'),
      StringStruct('LegalCopyright', 'NO LIMIT'),
      StringStruct('OriginalFilename', 'NO LIMIT.exe'),
      StringStruct('ProductName', 'NO LIMIT'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1034, 1200])])
  ]
)
"""
with open(os.path.join(AQUI, "version_info.txt"), "w", encoding="utf-8") as f:
    f.write(texto)

salida = os.environ.get("GITHUB_OUTPUT")
if salida:
    with open(salida, "a", encoding="utf-8") as f:
        f.write(f"version={VERSION}\n")
print(VERSION)
