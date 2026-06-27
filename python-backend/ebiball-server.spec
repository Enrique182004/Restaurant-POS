# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para el servidor Flask de Ebi Ball POS.
# Genera un ejecutable standalone que no requiere Python instalado.
# Uso: pyinstaller ebiball-server.spec --clean --noconfirm

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    # templates/ y static/ NO se incluyen aquí — vienen en extraResources
    # de electron-builder (python-backend/) y se pasan via FLASK_APP_DIR.
    datas=[],
    hiddenimports=[
        'flask_wtf',
        'flask_wtf.csrf',
        'wtforms',
        'wtforms.validators',
        'wtforms.fields',
        'werkzeug.security',
        'werkzeug.middleware.proxy_fix',
        'jinja2.ext',
        'requests',
        'sqlite3',
        'csv',
        'io',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'unittest', 'pydoc'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ebiball-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # Console para ver logs de Flask
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ebiball-server',
)
