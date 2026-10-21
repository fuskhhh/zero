"""Smoke-test the shipped archive and installer on an actual Windows runner."""
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

from app import VERSION

ROOT = Path(__file__).resolve().parent
CHECKS = ROOT / 'checks'
CHECKS.mkdir(exist_ok=True)
passed = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    passed.append(name)


def visible_window(pid):
    user32 = ctypes.windll.user32
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return bool(found)


def launch(exe, config, label):
    # A temporary settings directory keeps the test independent of user data.
    process = subprocess.Popen([str(exe), '--config-dir', str(config), '--quit-after', '5'])
    try:
        deadline = time.monotonic() + 4
        seen = False
        while time.monotonic() < deadline and process.poll() is None:
            if visible_window(process.pid):
                seen = True
                break
            time.sleep(.1)
        check(label + '_native_window_visible', seen)
        check(label + '_clean_exit', process.wait(timeout=20) == 0)
        check(label + '_settings_created', (config / 'settings.json').is_file())
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def main():
    if sys.platform != 'win32':
        raise RuntimeError('This check requires Windows, not a cross-build host.')
    installer = ROOT / 'release' / f'LinghaoPet-Windows-x64-Setup-v{VERSION}.exe'
    archive = ROOT / 'release' / f'LinghaoPet-Windows-x64-Portable-v{VERSION}.zip'
    with tempfile.TemporaryDirectory(prefix='linghao-package-') as tmp:
        folder = Path(tmp)
        with zipfile.ZipFile(archive) as zipped:
            check('portable_zip_integrity', zipped.testzip() is None)
            zipped.extractall(folder / 'portable')
        exe = folder / 'portable' / 'LinghaoPet' / 'LinghaoPet.exe'
        check('portable_has_executable', exe.is_file())
        atlas = Path('_internal') / 'assets' / 'linghao-codex-v2.webp'
        source_atlas = (ROOT / 'assets' / 'linghao-codex-v2.webp').read_bytes()
        check('portable_uses_exact_codex_atlas', (exe.parent/atlas).read_bytes() == source_atlas)
        launch(exe, folder / 'portable-config', 'portable')
        destination = folder / 'installed'
        result = subprocess.run([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', f'/DIR={destination}', f'/LOG={folder / "install.log"}'], timeout=120)
        check('installer_success', result.returncode == 0)
        installed = destination / 'LinghaoPet.exe'
        check('installed_executable_matches_portable', installed.read_bytes() == exe.read_bytes())
        check('installed_uses_exact_codex_atlas', (destination/atlas).read_bytes() == source_atlas)
        launch(installed, folder / 'installed-config', 'installed')
        uninstaller = destination / 'unins000.exe'
        check('uninstaller_present', uninstaller.is_file())
        result = subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], timeout=120)
        check('uninstaller_success', result.returncode == 0)
        deadline = time.monotonic() + 30
        while installed.exists() and time.monotonic() < deadline:
            time.sleep(.2)
        check('uninstall_removes_application', not installed.exists())
    report = {
        'version': VERSION,
        'platform': sys.platform,
        'checks_passed': passed,
        'check_count': len(passed),
        'installer_sha256': hashlib.sha256(installer.read_bytes()).hexdigest(),
        'atlas_sha256': hashlib.sha256(source_atlas).hexdigest(),
        'scope': 'Windows CI portable launch, visible window, install, installed launch and uninstall. Not a physical Windows desktop or long-session acceptance test.',
    }
    (CHECKS / 'windows-package.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
