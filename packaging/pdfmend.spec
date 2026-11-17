# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PDFMend desktop build (one folder, no console).

Build from the repository root:

    pyinstaller packaging/pdfmend.spec --noconfirm --clean

The output is ``dist/PDFMend/PDFMend.exe`` plus ``_internal``.
OCR (paddlepaddle / opencv) is deliberately excluded: it is a separate,
much heavier edition, and the Standard build must stay small.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = os.path.abspath(SPECPATH)  # noqa: F821 - SPECPATH is injected by PyInstaller
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
SRC = os.path.join(ROOT, "src")

hidden = collect_submodules("pdfmend")
datas = collect_data_files("pdfmend")  # profiles/*.json

a = Analysis(  # noqa: F821
    [os.path.join(SRC, "pdfmend", "desktop", "app.py")],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "paddle",
        "paddleocr",
        "paddlex",
        "cv2",
        "matplotlib",
        "pandas",
        "scipy",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFMend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PDFMend",
)
