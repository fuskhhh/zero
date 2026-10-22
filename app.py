"""零号桌宠: local-only Qt prototype shared by macOS and Windows."""
import argparse
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QStandardPaths
from PySide6.QtGui import QActionGroup, QBitmap, QColor, QCursor, QFont, QIcon, QImage, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget

from model import PetModel
from animation import ATLAS_SIZE, CELL_WIDTH, CELL_HEIGHT, ROWS, LOOK_START, EXTRA_CLIPS, FRAME_COUNT, look_direction

VERSION = '0.2.1'
ASSETS = Path(__file__).resolve().parent / 'assets'
INK, CREAM, MINT = '#233f39', '#fff9e9', '#a8d6bb'
PHRASES = [
    '搬家完成。桌面比工位大。',
    '我在观察。没有偷偷加班。',
    '拖得动我，拖不动截止日期。',
    '右键找我，想安静就暂停。',
    '今天先把这一小步做好。',
    '这次的休息申请，我批准。',
]


def read_settings(folder):
    try:
        data = json.loads((folder / 'settings.json').read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def opaque_region(pixmap):
    # Near-transparent atlas noise must not expand pose bounds or intercept clicks.
    mask = pixmap.toImage().createAlphaMask(Qt.ImageConversionFlag.ThresholdAlphaDither)
    return QRegion(QBitmap.fromImage(mask))


class Pet(QWidget):
    def __init__(self, config_dir, *, parent=None, persist=True):
        super().__init__(parent)
        self.config_dir, self.persist = Path(config_dir), persist
        cfg = read_settings(self.config_dir)
        size = cfg.get('size', 240)
        self.pet_size = size if size in (170, 240, 310) else 240
        self.on_top = cfg.get('on_top', True) is not False
        self.follow_mouse = cfg.get('follow_mouse', True) is not False
        self._look_frame = None
        self._last_cursor = None
        self._gaze_until = 0
        self._last_gaze_change = 0
        interval = cfg.get('reminder_minutes', 30)
        self.reminder_minutes = interval if interval in (15, 30, 45, 60) else 30
        # Reminder consent is per launch. Merely opening the pet never enables it.
        self.reminder_on = False
        self.model = PetModel()
        self.bubble, self.bubble_until = '', 0
        self.phrase_index = 0
        self._press_global = None
        self._dragged = False
        self._before_drag = 'idle'
        self._frame_key = None
        self._quitting = False
        self._menu_open = False
        self.setWindowTitle('零号桌宠')
        if parent is None:
            flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus
            if self.on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            if sys.platform == 'darwin':
                # Qt::Tool uses NSPanel on macOS, which otherwise disappears
                # when another app becomes active, even with stays-on-top set.
                self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        atlas = QImage(str(ASSETS / 'linghao-codex-v2.webp'))
        if atlas.isNull() or (atlas.width(), atlas.height()) != ATLAS_SIZE:
            raise RuntimeError('找不到零号动作素材，请保留应用的完整文件夹。')
        # Preserve exact v2 cell registration; no per-pose fitting or mirroring.
        self.frames = []
        for row, (_, holds) in enumerate(ROWS):
            for col in range(len(holds)):
                self.frames.append(QPixmap.fromImage(atlas.copy(col*CELL_WIDTH, row*CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT)))
        for index in range(16):
            self.frames.append(QPixmap.fromImage(atlas.copy(index%8*CELL_WIDTH, (9+index//8)*CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT)))
        self.frames.append(QPixmap.fromImage(atlas.copy(6*CELL_WIDTH, 0, CELL_WIDTH, CELL_HEIGHT)))
        for name, (filename, holds) in EXTRA_CLIPS.items():
            extra = QImage(str(ASSETS / filename))
            if extra.isNull() or (extra.width(), extra.height()) != (CELL_WIDTH * len(holds), CELL_HEIGHT):
                raise RuntimeError('找不到完整的零号动作素材：' + filename)
            for col in range(len(holds)):
                self.frames.append(QPixmap.fromImage(extra.copy(col*CELL_WIDTH, 0, CELL_WIDTH, CELL_HEIGHT)))
        if len(self.frames) != FRAME_COUNT:
            raise RuntimeError('零号动作表不完整。')
        self.scaled = {}
        self.resize_pet(self.pet_size)
        self.tray = QSystemTrayIcon(self.make_icon(), self)
        self.tray.setToolTip('零号桌宠 · 右键打开菜单')
        self.tray.activated.connect(self.tray_activated)
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self.sync_menu)
        self.menu.aboutToHide.connect(self.menu_closed)
        self.build_menu()
        self.tray.setContextMenu(self.menu)
        if parent is None and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.recovery = None
        self.reminder = QTimer(self)
        self.reminder.timeout.connect(self.remind)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(41)
        self.last_tick = time.monotonic()
        self.initial_position()

    def make_icon(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(MINT)); p.setPen(QPen(QColor(INK), 3))
        p.drawRoundedRect(4, 4, 56, 56, 16, 16)
        p.setFont(QFont('Arial', 32, QFont.Weight.Bold))
        p.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, '0')
        p.end()
        return QIcon(pm)

    def available(self):
        if self.parentWidget():
            return self.parentWidget().rect()
        center = self.pos() + self.rect().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        return screen.availableGeometry()

    def initial_position(self):
        a = self.available()
        self.model.x, self.model.y = a.right() - self.width() - 55, a.bottom() - self.height() - 18
        self.keep_in_bounds()

    def keep_in_bounds(self):
        a = self.available()
        self.model.clamp(a.left(), a.top(), a.right()+1, a.bottom()+1, self.width(), self.height())
        self.move(round(self.model.x), round(self.model.y))

    def resize_pet(self, size):
        old_floor = self.y() + self.height() if self.height() > 30 else None
        self.pet_size = size
        self.setFixedSize(max(290, size + 34), size + 100)
        self.scaled.clear()
        self._frame_key = None
        if old_floor is not None and hasattr(self, 'timer'):
            self.model.y = old_floor - self.height()
            self.keep_in_bounds()
        self.update_shape()
        self.save_settings()

    def sprite(self):
        i = self._look_frame if self.model.mode == 'idle' and self._look_frame is not None else self.model.frame()
        key = (i, self.pet_size)
        if key not in self.scaled:
            # V2 cells are rectangular. Square stretching changes face shape.
            self.scaled[key] = self.frames[i].scaled(self.pet_size, self.pet_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return key, self.scaled[key]

    def update_shape(self):
        if not hasattr(self, 'frames'):
            return
        key, pm = self.sprite()
        bubble = bool(self.bubble)
        content_key = (key, self.bubble)
        if content_key == self._frame_key:
            return
        if self._frame_key is None or (key, bubble) != (self._frame_key[0], bool(self._frame_key[1])):
            region = opaque_region(pm).translated((self.width()-pm.width())//2, 92)
            if bubble:
                region |= QRegion(QRect(4, 8, self.width()-8, 76))
            # Transparent space is removed from the native input region.
            self.setMask(region)
        self._frame_key = content_key
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        if self.bubble:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor(CREAM)); p.setPen(QPen(QColor(INK), 2))
            r = QRect(5, 9, self.width()-10, 66)
            p.drawRoundedRect(r, 12, 12)
            p.setFont(QFont('PingFang SC' if sys.platform == 'darwin' else 'Microsoft YaHei', 12))
            p.drawText(r.adjusted(12, 5, -12, -5), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.bubble)
        _, pm = self.sprite()
        p.drawPixmap((self.width()-pm.width())//2, 92, pm)
        p.end()

    def advance(self):
        now = time.monotonic()
        dt, self.last_tick = now - self.last_tick, now
        if not self.isVisible() or self._menu_open:
            return
        a = self.available()
        self.model.tick(dt, a.left(), a.right()+1, self.width())
        self.keep_in_bounds()
        if not self.model.paused:
            self.update_gaze(now=now)
        if self.bubble and now >= self.bubble_until:
            self.bubble = ''
        self.update_shape()

    def update_gaze(self, *, cursor=None, now=None):
        """Briefly watch a nearby moving pointer; never inspect screen content."""
        cursor = QCursor.pos() if cursor is None else cursor
        now = time.monotonic() if now is None else now
        moved = self._last_cursor is not None and cursor != self._last_cursor
        self._last_cursor = QPoint(cursor)
        if not self.follow_mouse or self.model.mode != 'idle':
            self._look_frame = None
            return
        center = self.mapToGlobal(QPoint(self.width()//2, 92+round(self.pet_size*.42)))
        delta = cursor-center
        distance2 = delta.x()**2+delta.y()**2
        near = (self.pet_size*.2)**2 < distance2 < max(300, self.pet_size*1.6)**2
        if moved and near:
            self._gaze_until = now+2.5
            if now-self._last_gaze_change >= .16:
                self._look_frame = LOOK_START+look_direction(delta.x(), delta.y())
                self._last_gaze_change = now
        elif not near or now >= self._gaze_until:
            self._look_frame = None

    def say(self, words, seconds=3.2):
        self.bubble, self.bubble_until = words, time.monotonic() + seconds
        self.update_shape()

    def react(self):
        words = PHRASES[self.phrase_index % len(PHRASES)]
        self.phrase_index += 1
        if not self.model.paused and self.model.mode != 'rest':
            self.model.mode, self.model.elapsed, self.model.remaining = 'react', 0, 2.8
        self.say(words)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_origin = self.pos()
            self._before_drag = self.model.mode
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._press_global is None:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if delta.manhattanLength() >= QApplication.startDragDistance():
            self._dragged = True
        if self._dragged:
            if self.model.mode != 'drag':
                self.model.elapsed = 0
            self.model.mode = 'drag'
            point = self._press_origin + delta
            if point.x() != self.model.x:
                self.model.direction = 1 if point.x() > self.model.x else -1
            self.model.x, self.model.y = point.x(), point.y()
            # Move before choosing a screen, so dragging can cross monitors.
            self.move(point)
            self.keep_in_bounds()
            self.update_shape()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            return
        dragged = self._dragged
        self._press_global = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if dragged:
            if self._before_drag == 'rest':
                self.model.mode = 'rest'
            else:
                self.model.settle(minimum_idle=60)
            self.say('这里不错。先住下了。')
        else:
            self.react()
        self.update_shape()

    def contextMenuEvent(self, event):
        self.menu.popup(event.globalPos())

    def build_menu(self):
        title = self.menu.addAction(f'零号桌宠 · {VERSION} 测试版')
        title.setEnabled(False)
        self.menu.addAction('显示零号', self.restore_pet)
        self.pause_action = self.menu.addAction('暂停活动', self.toggle_pause)
        self.pause_action.setCheckable(True)
        self.rest_action = self.menu.addAction('原地休息', self.toggle_rest)
        self.rest_action.setCheckable(True)
        self.gaze_action = self.menu.addAction('看看鼠标', self.toggle_gaze)
        self.gaze_action.setCheckable(True)
        actions = self.menu.addMenu('做个动作')
        for label, name in [('打个招呼', 'waving'), ('开心跳一下', 'jumping'), ('有点沮丧', 'failed'), ('等你回应', 'waiting'), ('认真思考', 'running'), ('仔细观察', 'review'), ('敲会儿键盘', 'typing'), ('动动鼠标', 'using-mouse')]:
            actions.addAction(label, lambda checked=False, n=name: self.play_action(n))
        self.menu.addSeparator()
        sizes = self.menu.addMenu('角色大小')
        group = QActionGroup(sizes)
        self.size_actions = {}
        for name, size in [('小', 170), ('中', 240), ('大', 310)]:
            act = sizes.addAction(name)
            act.setCheckable(True); group.addAction(act)
            act.triggered.connect(lambda checked=False, n=size: self.resize_pet(n))
            self.size_actions[size] = act
        self.top_action = self.menu.addAction('保持置顶', self.toggle_top)
        self.top_action.setCheckable(True)
        reminders = self.menu.addMenu('休息提醒（默认关闭）')
        self.reminder_action = reminders.addAction('开启提醒', self.toggle_reminder)
        self.reminder_action.setCheckable(True)
        intervals = QActionGroup(reminders)
        self.interval_actions = {}
        for minutes in (15, 30, 45, 60):
            act = reminders.addAction(f'每 {minutes} 分钟')
            act.setCheckable(True); intervals.addAction(act)
            act.triggered.connect(lambda checked=False, n=minutes: self.set_interval(n))
            self.interval_actions[minutes] = act
        self.menu.addSeparator()
        self.menu.addAction('隐藏零号', self.hide_pet)
        self.menu.addAction('退出零号', self.quit_pet)

    def sync_menu(self):
        self._menu_open = True
        self.pause_action.setChecked(self.model.paused)
        self.rest_action.setChecked(self.model.mode == 'rest')
        self.top_action.setChecked(self.on_top)
        self.gaze_action.setChecked(self.follow_mouse)
        self.reminder_action.setChecked(self.reminder_on)
        for n, a in self.size_actions.items():
            a.setChecked(n == self.pet_size)
        for n, a in self.interval_actions.items():
            a.setChecked(n == self.reminder_minutes)

    def menu_closed(self):
        self._menu_open = False
        self.last_tick = time.monotonic()

    def toggle_pause(self):
        self.model.paused = not self.model.paused
        self.say('暂停了。我就在这里。' if self.model.paused else '好，继续观察。')

    def toggle_rest(self):
        if self.model.mode == 'rest':
            self.model.settle(observe_chance=0)
        else:
            self.model.mode, self.model.elapsed = 'rest', 0
        self.say('休息五分钟，我批准了。' if self.model.mode == 'rest' else '休息结束，继续观察。')

    def toggle_top(self):
        self.on_top = not self.on_top
        if self.parentWidget() is None:
            point = self.pos()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.on_top)
            self.show(); self.move(point)
        self.save_settings()

    def toggle_gaze(self):
        self.follow_mouse = not self.follow_mouse
        self._look_frame = None
        self.update_shape()
        self.save_settings()

    def play_action(self, name):
        self.model.paused = False
        self._look_frame = None
        self.model.play(name)
        self.update_shape()

    def set_interval(self, minutes):
        self.reminder_minutes = minutes
        if self.reminder_on:
            self.reminder.start(minutes * 60_000)
        self.save_settings()

    def toggle_reminder(self):
        self.reminder_on = not self.reminder_on
        if self.reminder_on:
            self.reminder.start(self.reminder_minutes * 60_000)
            self.say(f'好，每 {self.reminder_minutes} 分钟提醒你休息。')
        else:
            self.reminder.stop()
            self.say('休息提醒已关闭。')

    def remind(self):
        # Hidden means quiet: no unsolicited pop-up or window restoration.
        if self.isVisible() and self.reminder_on:
            self.say('看远一点，伸个懒腰。工作也要留空格。', 6)

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_pet()

    def hide_pet(self):
        self.hide()
        if not self.tray.isVisible():
            if self.recovery is None:
                self.recovery = QWidget()
                self.recovery.setWindowTitle('找回零号')
                layout = QVBoxLayout(self.recovery)
                layout.addWidget(QLabel('零号已隐藏'))
                show = QPushButton('显示零号'); show.clicked.connect(self.restore_pet)
                leave = QPushButton('退出零号'); leave.clicked.connect(self.quit_pet)
                layout.addWidget(show); layout.addWidget(leave)
            self.recovery.show()

    def restore_pet(self):
        if self.recovery:
            self.recovery.hide()
        self.keep_in_bounds()
        self.last_tick = time.monotonic()
        self.show()
        self.update_shape()

    def save_settings(self):
        if not self.persist:
            return
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            target = self.config_dir / 'settings.json'
            tmp = target.with_suffix('.tmp')
            tmp.write_text(json.dumps({'size': self.pet_size, 'on_top': self.on_top, 'reminder_minutes': self.reminder_minutes, 'follow_mouse': self.follow_mouse}, ensure_ascii=False))
            tmp.replace(target)
        except OSError:
            pass  # The pet remains usable in a read-only portable folder.

    def quit_pet(self):
        self._quitting = True
        self.save_settings()
        self.timer.stop(); self.reminder.stop(); self.tray.hide()
        if self.recovery:
            self.recovery.close()
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self._quitting:
            event.accept()
        else:
            event.ignore()
            self.quit_pet()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-dir', type=Path)
    parser.add_argument('--quit-after', type=float)
    parser.add_argument('--paused', action='store_true', help='Start with autonomous activity paused')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('LinghaoPet')
    app.setOrganizationName('LinghaoStudio')
    app.setQuitOnLastWindowClosed(False)
    folder = args.config_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    pet = Pet(folder)
    pet.model.paused = args.paused
    app.setWindowIcon(pet.make_icon())
    pet.show()
    pet.say('我是零号。点我打招呼，右键找设置。', 5)
    if args.quit_after:
        QTimer.singleShot(int(args.quit_after * 1000), pet.quit_pet)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
