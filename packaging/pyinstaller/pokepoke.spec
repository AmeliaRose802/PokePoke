# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files

spec_path = Path(__file__) if "__file__" in globals() else Path(sys.argv[0])
project_root = spec_path.resolve().parents[2]
src_root = project_root / "src"
icon_path = project_root / "desktop" / "public" / "pokepoke.ico"
version_file = project_root / "packaging" / "pyinstaller" / "version_info.txt"

block_cipher = None

# Package data
datas = collect_data_files("pokepoke", includes=["static/**", "builtin_prompts/**"])

# Include default config/prompts/scripts so bundled app has built-in templates
user_config_dir = project_root / ".pokepoke"
if user_config_dir.exists():
    for path in user_config_dir.rglob("*"):
        if path.is_file():
            datas.append((str(path), str(path.relative_to(project_root).parent)))

# pywebview / WebView2 assets and hidden imports
webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")
datas += webview_datas
binaries = webview_binaries
hiddenimports = sorted(
    set(
        webview_hiddenimports
        + [
            "webview.platforms.edgechromium",
            "webview.platforms.winforms",
        ]
    )
)

excludes = ["tkinter"]

a = Analysis(
    [str(src_root / "pokepoke" / "orchestrator.py")],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PokePoke",
)
