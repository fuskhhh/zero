"""Exercise native Qt input and lifecycle; saves evidence, not release approval."""
import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import Pet, opaque_region, read_settings
from model import PetModel

OUT = Path(__file__).resolve().parent / 'checks'
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication(sys.argv[:1])
app.setQuitOnLastWindowClosed(False)
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


with tempfile.TemporaryDirectory(dir=OUT) as tmp:
    pet = Pet(tmp, persist=False)
    pet.show()
    QTest.qWait(200)
    check('native_window_visible', pet.isVisible())
    if sys.platform == 'darwin':
        from verify_mac_residency import native_window_state
        check('mac_panel_does_not_hide_on_deactivate', not native_window_state(pet)['hides_on_deactivate'])
    check('translucent_window', pet.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
    check('does_not_accept_keyboard_focus', bool(pet.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus))
    check('transparent_corner_excluded_from_input', not pet.mask().contains(QPoint(0, 0)))
    check('reminders_disabled_by_default', not pet.reminder_on and not pet.reminder.isActive())
    body = QPoint(pet.width()//2, 92 + pet.pet_size//2)
    QTest.mouseClick(pet, Qt.MouseButton.LeftButton, pos=body)
    check('click_reacts', pet.phrase_index == 1 and bool(pet.bubble))
    pet.grab().save(str(OUT / 'click.png'))
    before = pet.phrase_index
    origin = pet.pos()
    QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=body)
    target = body + QPoint(-70, -40)
    global_target = pet.mapToGlobal(target)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(target), QPointF(global_target), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(pet, move)
    QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=body)
    check('drag_moves_window', (pet.pos()-origin).manhattanLength() > 30)
    check('drag_does_not_click', pet.phrase_index == before)
    check('drag_settles_in_place', pet.model.mode in ('idle', 'observe'))
    quiet = pet.model.idle_after_observation if pet.model.mode == 'observe' else pet.model.remaining
    check('drag_leaves_at_least_one_quiet_minute', quiet >= 60)
    pet.model.mode, pet.model.elapsed, pet.model.remaining = 'observe', 1, 6
    pet.update_shape()
    check('magnifier_poses_loaded', len(pet.frames) == 20 and pet.model.frame() == 17)
    anchor = opaque_region(pet.frames[0]).boundingRect()
    observation = opaque_region(pet.frames[17]).boundingRect()
    check('observation_keeps_body_height', abs(anchor.height()-observation.height()) <= 2)
    check('observation_keeps_foot_anchor', abs(anchor.bottom()-observation.bottom()) <= 2)
    pet.grab().save(str(OUT / 'observe.png'))
    pet.model.mode = 'walk'
    pet.model.remaining = 30
    pet.model.direction = -1
    pet.model.x = pet.available().left()+1
    pet.model.tick(.1, pet.available().left(), pet.available().right()+1, pet.width())
    check('left_boundary_turns_around', pet.model.direction == 1 and pet.model.x >= pet.available().left())
    pet.toggle_pause()
    point, elapsed = pet.model.x, pet.model.elapsed
    QTest.qWait(200)
    check('pause_stops_motion_and_animation', pet.model.x == point and pet.model.elapsed == elapsed)
    pet.toggle_pause()
    pet.toggle_rest()
    check('rest_uses_distinct_pose', pet.model.mode == 'rest' and pet.model.frame() == 12)
    pet.grab().save(str(OUT / 'rest.png'))
    pet.resize_pet(170)
    check('resize_changes_character', pet.pet_size == 170 and pet.height() == 270)
    pet.toggle_top()
    check('top_toggle_preserves_visible_window', pet.isVisible() and not pet.on_top)
    pet.hide_pet()
    check('hide_has_recovery_entry', not pet.isVisible() and (pet.tray.isVisible() or bool(pet.recovery and pet.recovery.isVisible())))
    pet.restore_pet()
    check('restore_works', pet.isVisible())
    if sys.platform == 'darwin':
        check('mac_residency_survives_top_toggle_and_hide_restore', not native_window_state(pet)['hides_on_deactivate'])
    pet.toggle_reminder()
    check('reminder_explicit_enable', pet.reminder_on and pet.reminder.isActive())
    pet.remind()
    check('reminder_shows_local_message', '伸个懒腰' in pet.bubble)
    pet.toggle_reminder()
    check('reminder_can_disable', not pet.reminder.isActive())
    pet.model.x, pet.model.y = -100000, 100000
    pet.keep_in_bounds()
    check('offscreen_position_recovers', pet.available().contains(pet.geometry()))
    pet.persist = True
    pet.save_settings()
    cfg = read_settings(Path(tmp))
    check('settings_saved', cfg.get('size') == 170 and cfg.get('on_top') is False)
    check('reminder_consent_not_persisted', 'reminder_on' not in cfg)
    pet.menu.popup(pet.pos())
    QTest.qWait(100)
    check('menu_pauses_autonomous_motion', pet._menu_open)
    pet.menu.hide()
    QTest.qWait(50)
    check('menu_close_releases_pause', not pet._menu_open)
    pet.quit_pet()
    check('exit_stops_all_timers', not pet.timer.isActive() and not pet.reminder.isActive())

report = {
    'checks_passed': checks,
    'check_count': len(checks),
    'qt_platform': app.platformName(),
    'screens': [{'name': s.name(), 'geometry': [s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height()], 'dpr': s.devicePixelRatio()} for s in app.screens()],
    'scope': 'Native Qt input/lifecycle smoke checks on the reported platform; not a 30-minute desktop acceptance test.'
}
(OUT / 'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(report, ensure_ascii=False))
