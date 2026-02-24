# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# SPECPATH is provided by PyInstaller at spec-execution time
project_root = Path(SPECPATH).resolve().parent.parent
src_root = project_root / "src"
icon_path = project_root / "desktop" / "public" / "pokepoke.ico"
version_file = project_root / "packaging" / "pyinstaller" / "version_info.txt"

block_cipher = None

datas = collect_data_files("pokepoke", includes=["static/**"])

a = Analysis(
    [str(src_root / "pokepoke" / "orchestrator.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinter", "tkinter.filedialog"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PokePoke",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=str(icon_path),
    version=str(version_file),
)
