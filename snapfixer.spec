# -*- mode: python ; coding: utf-8 -*-
# Fichier de configuration PyInstaller pour Snapchat Memories Fixer.
#
# Utilisation locale (nécessite `pip install pyinstaller`) :
#   pyinstaller snapfixer.spec
#
# En pratique, les exécutables macOS (arm64 + intel) et Windows sont
# construits automatiquement par la CI GitHub Actions (voir
# .github/workflows/build.yml) — ce fichier n'a normalement pas besoin
# d'être lancé à la main, sauf pour du développement local.
#
# Note : l'app ne fonctionne pas sans `ffmpeg`/`ffprobe` accessibles dans le
# PATH (traitement vidéo) -- pas embarqués ici, voir le README.

import sys

block_cipher = None

APP_NAME = "Snapchat-Memories-Fixer"

a = Analysis(
    ["app.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[
        "snapfixer",
        "snapfixer.core",
        "snapfixer.gui",
        "snapfixer.cli",
        "snapfixer.matcher",
        "snapfixer.metadata",
        "snapfixer.overlay",
        "snapfixer.zip_source",
        "piexif",
        "PIL",
        "PIL.Image",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Mode "onefile" : un seul exécutable autonome, plus simple à distribuer
# publiquement qu'un dossier (l'utilisateur télécharge un seul fichier).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # pas de fenêtre de terminal derrière la GUI
    disable_windowed_traceback=False,
    argv_emulation=sys.platform == "darwin",
    target_arch=None,  # fixé par --target-arch en ligne de commande selon la plateforme CI
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="com.snapfixer.app",
        info_plist={
            "NSHighResolutionCapable": "True",
            "CFBundleShortVersionString": "1.0.0",
        },
    )
