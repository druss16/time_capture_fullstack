"""The two shapes of the Windows camera/microphone consent store.

Runs anywhere — winreg is faked — because the bug it pins down was found on a
Windows laptop and fixed on a Mac:

    ConsentStore\\webcam\\Microsoft.WindowsCamera_8wekyb3d8bbwe
        LastUsedTimeStop = 0            <- packaged app, on the package key
    ConsentStore\\webcam\\NonPackaged\\C:#...#chrome.exe
        LastUsedTimeStop = 0            <- desktop app, one level down

Reading only the second shape meant the probe reported "nothing in use" on a
machine whose camera was plainly on, for every Store app — including new
Teams, which is what the firms actually use.

    python consent_store_test.py
"""
import sys
import types
import unittest

BASE = (r"Software\Microsoft\Windows\CurrentVersion"
        r"\CapabilityAccessManager\ConsentStore")

LIVE = 0
STALE = 0x1dcd341eecab3ca


def install_fake_winreg(tree):
    class FakeKey:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake = types.ModuleType('winreg')
    fake.HKEY_CURRENT_USER = 'HKCU'

    def open_key(root, path):
        if path not in tree:
            raise FileNotFoundError(path)
        return FakeKey(path)

    def enum_key(key, index):
        subs = tree[key.path].get('subkeys', [])
        if index >= len(subs):
            raise OSError('no more items')
        return subs[index]

    def query_value(key, name):
        node = tree[key.path]
        if name not in node:
            raise FileNotFoundError(name)
        return node[name], 11

    fake.OpenKey, fake.EnumKey, fake.QueryValueEx = open_key, enum_key, query_value
    sys.modules['winreg'] = fake


# The tree exactly as `reg query` printed it on a machine with the Camera app
# running and Chrome/Zoom/Edge having used the camera earlier.
TREE = {
    f"{BASE}\\webcam": {'subkeys': [
        'Microsoft.WindowsCamera_8wekyb3d8bbwe',
        'MSTeams_8wekyb3d8bbwe',
        'NonPackaged',
    ]},
    f"{BASE}\\webcam\\Microsoft.WindowsCamera_8wekyb3d8bbwe": {'LastUsedTimeStop': LIVE},
    f"{BASE}\\webcam\\MSTeams_8wekyb3d8bbwe": {'LastUsedTimeStop': STALE},
    f"{BASE}\\webcam\\NonPackaged": {'subkeys': [
        'C:#Program Files#Google#Chrome#Application#chrome.exe',
    ]},
    f"{BASE}\\webcam\\NonPackaged\\C:#Program Files#Google#Chrome#Application#chrome.exe":
        {'LastUsedTimeStop': STALE},
    f"{BASE}\\microphone": {'subkeys': ['NonPackaged']},
    f"{BASE}\\microphone\\NonPackaged": {'subkeys': [
        'C:#Program Files#Google#Chrome#Application#chrome.exe',
    ]},
    f"{BASE}\\microphone\\NonPackaged\\C:#Program Files#Google#Chrome#Application#chrome.exe":
        {'LastUsedTimeStop': LIVE},
}


class ConsentStoreTests(unittest.TestCase):
    def setUp(self):
        install_fake_winreg(TREE)
        import media_capture
        media_capture.IS_MAC, media_capture.IS_WINDOWS = False, True
        self.probe = media_capture._probe_windows

    def test_packaged_app_holding_the_camera_is_seen(self):
        # The bug: this returned nothing, because the value is on the package
        # key rather than in a child of it.
        devices = self.probe().devices
        self.assertTrue(
            any('WindowsCamera' in d for d in devices),
            f'packaged camera use not detected in {devices}',
        )

    def test_desktop_app_holding_the_microphone_is_seen(self):
        devices = self.probe().devices
        self.assertTrue(
            any(d.startswith('mic:') and 'chrome' in d.lower() for d in devices),
            f'NonPackaged mic use not detected in {devices}',
        )

    def test_apps_that_have_released_the_device_are_ignored(self):
        devices = self.probe().devices
        self.assertFalse([d for d in devices if 'MSTeams' in d],
                         'a stale LastUsedTimeStop was treated as in use')
        self.assertFalse([d for d in devices if d.startswith('camera:') and 'chrome' in d.lower()],
                         'a stale camera entry was treated as in use')

    def test_state_is_active_when_anything_is_held(self):
        self.assertTrue(self.probe().active)


if __name__ == '__main__':
    unittest.main(verbosity=2)
