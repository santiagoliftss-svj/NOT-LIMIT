"""CI (Mac de verdad): prueba que la actualizacion sola cambia una NO LIMIT.app vieja por la del DMG nuevo."""

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from clw import version  # noqa: E402
from clw.mac import actualizar_mac as am  # noqa: E402

dmg = os.path.abspath(sys.argv[1])
d = tempfile.mkdtemp()
dest = os.path.join(d, "Aplicaciones", "NO LIMIT.app")
os.makedirs(os.path.join(dest, "Contents"))
with open(os.path.join(dest, "Contents", "vieja.txt"), "w") as f:
    f.write("version vieja")
copia = os.path.join(d, "NO-LIMIT-Mac-nueva.dmg")
shutil.copy(dmg, copia)
script = am.escribir_script(d)
reg = os.path.join(d, "registro.txt")
r = subprocess.run(["/bin/bash", script, "999999", copia, dest, "0", reg], timeout=600)
print(open(reg, encoding="utf-8", errors="replace").read())
assert r.returncode == 0, r.returncode
assert not os.path.exists(os.path.join(dest, "Contents", "vieja.txt")), "no cambio la app vieja"
assert not os.path.exists(dest + ".viejo") and not os.path.exists(dest + ".nuevo")
with open(os.path.join(dest, "Contents", "Info.plist"), "rb") as f:
    info = plistlib.load(f)
assert info.get("CFBundleShortVersionString") == version.VERSION, info.get("CFBundleShortVersionString")
subprocess.run(["codesign", "--verify", "--deep", "--strict", dest], check=True)
assert not os.path.exists(copia), "no borro el DMG bajado"
print("actualizacion sola en Mac: ok ->", info.get("CFBundleShortVersionString"), am.preferidos())
