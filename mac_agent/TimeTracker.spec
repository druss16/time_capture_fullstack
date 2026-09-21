a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('notifications.py', '.'),
        ('timetracker_gui.py', '.'),
        ('agent_sync_integration.py', '.'),
        # The matching brain. Several of these are imported from inside
        # functions or behind try/except, which PyInstaller's analysis can
        # miss, and a module missing from the bundle fails silently at
        # runtime — the agent starts, the feature is just gone.
        ('ai_client_switcher.py', '.'),
        ('routing_rules.py', '.'),
        ('tax_software_constants.py', '.'),
        ('content_identity.py', '.'),
        ('pdf_identity.py', '.'),
        ('inference_cache.py', '.'),
        ('widget_state_tracker.py', '.'),
        ('tracking_health.py', '.'),
        ('finder_watcher.py', '.'),
        ('meeting_detector.py', '.'),
        ('update_checker.py', '.'),
        ('sync_manager.py', '.'),
        # Org-token pairing. Imported from inside run_agent, so the analysis
        # cannot see it; without this an IT-deployed Mac silently falls back
        # to asking the user to pair by hand.
        ('mdm_deploy.py', '.'),
        ('version.py', '.'),
        ('inference', 'inference'),
    ],
    hiddenimports=[
        # Same list again as imports, because datas only puts the file next
        # to the binary — it does not make PyInstaller collect what THEY
        # import.
        'ai_client_switcher',
        'routing_rules',
        'tax_software_constants',
        'content_identity',
        'pdf_identity',
        'inference_cache',
        'widget_state_tracker',
        'tracking_health',
        'finder_watcher',
        'meeting_detector',
        'update_checker',
        'mdm_deploy',
        'version',
        'inference',
        'inference.collectors',
        'inference.decay',
        'inference.engine',
        'inference.evidence',
        # The Mac meeting probes read the process table; without psutil both
        # the camera and audio probes return nothing and detection falls back
        # to window titles alone.
        'psutil',
        'UserNotifications',
        'objc',
        'Foundation',
        'AppKit',
        'Quartz',
        'PyObjCTools',
        'PyObjCTools.Conversion',
        'pyobjc_framework_UserNotifications',
        'rumps',
        'certifi',
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._darwin',
    ],
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
    [],
    exclude_binaries=True,
    name='TimeTracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TimeTracker',
    distpath='dist',
    workpath='build',
)
app = BUNDLE(
    coll,
    name='TimeTracker.app',
    icon='timetracker.icns',
    # MUST stay 'TimeTracker' — it is what the installed 1.7.22 declares.
    # TCC keys Accessibility on the bundle identifier, so changing this to
    # something tidier and reverse-DNS would present as a NEW application to
    # macOS: every existing Mac user silently loses Accessibility, window
    # titles start arriving empty, and attribution quietly falls back to file
    # paths and URLs alone. Continuity beats correct form here.
    bundle_identifier='TimeTracker',
)