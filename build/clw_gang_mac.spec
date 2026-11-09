# -*- mode: python ; coding: utf-8 -*-
# PyInstaller (Mac, Apple Silicon): pyinstaller build/clw_gang_mac.spec --noconfirm
# Sale dist/NO LIMIT.app. Despues build/empacar_tesseract_mac.py le mete el OCR y se firma (ad-hoc).
import os
import sys

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(RAIZ, "app")
sys.path.insert(0, APP)
from clw.version import VERSION  # noqa: E402

a = Analysis(
    [os.path.join(APP, "clw_gang.py")],
    pathex=[APP],
    datas=[(os.path.join(APP, "assets"), "assets")],
    hiddenimports=["objc", "AppKit", "Foundation", "Quartz", "HIServices", "certifi",
                   "clw.mac.ventana", "clw.mac.escucha", "clw.mac.entrada", "clw.mac.captura",
                   "clw.mac.llavero", "clw.mac.permisos", "clw.mac.autoprueba"],
    excludes=["tkinter", "_tkinter", "PIL.ImageTk", "PIL._tkinter_finder", "numpy", "matplotlib", "pytest",
              "IPython", "pystray"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NO LIMIT",
    console=False,
    argv_emulation=False,
    target_arch=os.environ.get("MAC_ARCH") or None,   # arm64 (M1...) o x86_64 (Intel)
    codesign_identity=None,
    entitlements_file=None,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="NO LIMIT")

app = BUNDLE(
    coll,
    name="NO LIMIT.app",
    icon=os.path.join(APP, "assets", "icono.icns"),
    bundle_identifier="mx.nolimit.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "NO LIMIT",
        "CFBundleDisplayName": "NO LIMIT",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": os.environ.get("MAC_MINIMO", "15.0"),
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "NO LIMIT",
    },
)
