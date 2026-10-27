# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['gui_app_flet.py'],
    # La GUI importa `superaudio.config`; el paquete está en el
    # directorio padre de este spec.
    pathex=['..'],
    binaries=[],
    # run.py se incluye para poder lanzar el venv de Supertonic.
    datas=[('run.py', '.')],
    hiddenimports=['superaudio.config'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Superaudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icono.ico'],
)
