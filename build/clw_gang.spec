# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: pyinstaller build/clw_gang.spec --noconfirm
import os

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(RAIZ, "app")

a = Analysis(
    [os.path.join(APP, "clw_gang.py")],
    pathex=[APP],
    datas=[(os.path.join(APP, "assets"), "assets")],
    hiddenimports=["PIL.ImageTk", "PIL._tkinter_finder"],
    excludes=["numpy", "matplotlib", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CLW GANG",
    console=False,
    icon=os.path.join(APP, "assets", "icono.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="CLW GANG")
