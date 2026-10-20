"""Check the real Cocoa window after switching to another application.

Run this on macOS, activate its small controller, then switch apps using the
desktop UI. Qt's isVisible() alone misses NSPanel hiding on deactivation.
"""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from app import Pet


def native_window_state(widget):
    """Read our own NSView/NSWindow; do not activate or control other apps."""
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    send_id = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
    send_bool = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
    send_int = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
    window = send_id(int(widget.winId()), objc.sel_registerName(b'window'))
    if not window:
        raise RuntimeError('Qt native view has no NSWindow')
    # NSPanel.isVisible may also stay true while Cocoa suppresses the panel.
    # Ask CoreGraphics about this window only, not about other apps' contents.
    number = send_int(window, objc.sel_registerName(b'windowNumber'))
    cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
    cf.CFBooleanGetValue.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    info = cg.CGWindowListCopyWindowInfo(1 << 3, number)
    on_screen = False
    if info:
        if cf.CFArrayGetCount(info):
            row = cf.CFArrayGetValueAtIndex(info, 0)
            key = ctypes.c_void_p.in_dll(cg, 'kCGWindowIsOnscreen').value
            value = cf.CFDictionaryGetValue(row, key)
            on_screen = bool(value and cf.CFBooleanGetValue(value))
        cf.CFRelease(info)
    return {
        'cocoa_visible': bool(send_bool(window, objc.sel_registerName(b'isVisible'))),
        'hides_on_deactivate': bool(send_bool(window, objc.sel_registerName(b'hidesOnDeactivate'))),
        'on_screen': on_screen,
        'qt_visible': widget.isVisible(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', default='current')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('This regression check requires macOS Cocoa.')
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    out = Path(__file__).resolve().parents[2] / 'work' / 'desktop-pet-checks'
    controller = QWidget()
    controller.setWindowTitle('零号驻留回归检查')
    controller.setFixedSize(440, 170)
    layout = QVBoxLayout(controller)
    layout.addWidget(QLabel('先激活此窗口，再切换到其他应用。\n检查后台的零号是否仍然可见。'))
    pet = Pet(out / 'residency-settings', persist=False)
    pet.model.paused = True
    controller.show()
    pet.show()
    active_seen = False
    snapshots = []
    started = time.monotonic()
    result_code = 2
    finished = False

    def finish(code, verdict):
        nonlocal result_code, finished
        if finished:
            return
        finished, result_code = True, code
        report = {'verdict': verdict, 'tag': args.tag, 'snapshots': snapshots}
        (out / f'residency-{args.tag}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(report, ensure_ascii=False), flush=True)
        controller.close()
        pet.quit_pet()

    def inspect():
        nonlocal active_seen
        active = app.applicationState() == Qt.ApplicationState.ApplicationActive
        state = {'active': active, **native_window_state(pet)}
        if not snapshots or state != snapshots[-1]:
            snapshots.append(state)
            print(json.dumps({'sample': state}, ensure_ascii=False), flush=True)
        if active and state['on_screen']:
            active_seen = True
        elif active_seen and not active:
            if not state['on_screen']:
                finish(1, 'FAIL: pet disappears when application deactivates')
            elif not state['hides_on_deactivate']:
                finish(0, 'PASS: native pet remains visible after application deactivation')
        if time.monotonic()-started > 50:
            finish(2, 'INCOMPLETE: no verified active-to-inactive transition')

    timer = QTimer()
    timer.timeout.connect(inspect)
    timer.start(100)
    app.exec()
    return result_code


if __name__ == '__main__':
    raise SystemExit(main())
