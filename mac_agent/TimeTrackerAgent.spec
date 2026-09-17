# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # CoreMediaIO is imported inside media_capture._mac_camera_in_use(), and
    # pyobjc frameworks need naming explicitly or the probe silently reports
    # "no camera in use" in the packaged build while working in development.
    # (The mic half reaches CoreAudio through ctypes and needs nothing here.)
    hiddenimports=['CoreMediaIO', 'media_capture'],
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
    name='TimeTrackerAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
