"""零号桌宠: local-only Qt prototype shared by macOS and Windows."""
import argparse
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QStandardPaths
from PySide6.QtGui import QActionGroup, QBitmap, QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget

from model import PetModel

VERSION = '0.1.3'
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
        atlas = QImage(str(ASSETS / 'linghao-atlas-v1.png'))
        if atlas.isNull():
            raise RuntimeError('找不到零号动作素材，请保留应用的完整文件夹。')
        # Equal-cell slicing handles atlases whose image dimensions are not /4.
        self.frames = []
        for row in range(4):
            for col in range(4):
                x0, x1 = round(col * atlas.width() / 4), round((col + 1) * atlas.width() / 4)
                y0, y1 = round(row * atlas.height() / 4), round((row + 1) * atlas.height() / 4)
                frame = QPixmap(x1-x0, y1-y0)
                frame.fill(Qt.GlobalColor.transparent)
                painter = QPainter(frame)
                # The generated atlas has a few pixels of the preceding row's
                # soles in its top gutter. Exclude that gutter while slicing.
                gutter = round((y1-y0)*.038)
                painter.drawImage(0, gutter, atlas.copy(x0, y0+gutter, x1-x0, y1-y0-gutter))
                painter.end()
                self.frames.append(frame)
        self.load_observation_frames()
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

    def load_observation_frames(self):
        atlas = QImage(str(ASSETS / 'linghao-observe-v1.png'))
        if atlas.isNull():
            raise RuntimeError('找不到零号观察动作，请保留应用的完整文件夹。')
        base = self.frames[0]
        anchor = opaque_region(base).boundingRect()
        for row in range(2):
            for col in range(2):
                x0, x1 = round(col*atlas.width()/2), round((col+1)*atlas.width()/2)
                y0, y1 = round(row*atlas.height()/2), round((row+1)*atlas.height()/2)
                tile = QPixmap.fromImage(atlas.copy(x0, y0, x1-x0, y1-y0))
                bounds = opaque_region(tile).boundingRect()
                if bounds.isEmpty():
                    raise RuntimeError('观察动作单元为空。')
                # Align separately generated poses to the existing body height
                # and foot anchor, so changing actions does not resize the pet.
                pose = tile.copy(bounds).scaled(base.width()-12, anchor.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
                frame = QPixmap(base.size())
                frame.fill(Qt.GlobalColor.transparent)
                painter = QPainter(frame)
                painter.drawPixmap((base.width()-pose.width())//2, anchor.bottom()+1-pose.height(), pose)
                painter.end()
                self.frames.append(frame)

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
        i = self.model.frame()
        mirrored = self.model.mode == 'walk' and self.model.direction < 0
        key = (i, mirrored, self.pet_size)
        if key not in self.scaled:
            pm = self.frames[i].scaled(self.pet_size, self.pet_size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            self.scaled[key] = pm.transformed(QTransform().scale(-1, 1)) if mirrored else pm
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
            region = opaque_region(pm).translated((self.width()-self.pet_size)//2, 92)
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
        p.drawPixmap((self.width()-self.pet_size)//2, 92, pm)
        p.end()

    def advance(self):
        now = time.monotonic()
        dt, self.last_tick = now - self.last_tick, now
        if not self.isVisible() or self._menu_open:
            return
        a = self.available()
        self.model.tick(dt, a.left(), a.right()+1, self.width())
        self.keep_in_bounds()
        if self.bubble and now >= self.bubble_until:
            self.bubble = ''
        self.update_shape()

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
            self.model.mode = 'drag'
            point = self._press_origin + delta
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
        title = self.menu.addAction(f'零号桌宠 · {VERSION} 内部原型')
        title.setEnabled(False)
        self.menu.addAction('显示零号', self.restore_pet)
        self.pause_action = self.menu.addAction('暂停活动', self.toggle_pause)
        self.pause_action.setCheckable(True)
        self.rest_action = self.menu.addAction('原地休息', self.toggle_rest)
        self.rest_action.setCheckable(True)
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
            tmp.write_text(json.dumps({'size': self.pet_size, 'on_top': self.on_top, 'reminder_minutes': self.reminder_minutes}, ensure_ascii=False))
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
