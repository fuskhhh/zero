"""Codex v2 atlas geometry and clip timing, independent of the Qt renderer."""
import math

CELL_WIDTH, CELL_HEIGHT = 192, 208
ATLAS_SIZE = (1536, 2288)
# Separate left/right artwork preserves the character's asymmetric hair clip.
ROWS = (
    ('idle', (280, 110, 110, 140, 140, 320)),
    ('running-right', (120,) * 7 + (220,)),
    ('running-left', (120,) * 7 + (220,)),
    ('waving', (140, 140, 140, 280)),
    ('jumping', (140, 140, 140, 140, 280)),
    ('failed', (140,) * 7 + (240,)),
    ('waiting', (150,) * 5 + (260,)),
    ('running', (120,) * 5 + (220,)),
    ('review', (150,) * 5 + (280,)),
)
CLIPS = {}
offset = 0
for name, durations in ROWS:
    CLIPS[name] = (offset, durations)
    offset += len(durations)
LOOK_START, NEUTRAL_FRAME = offset, offset + 16
BASE_FRAME_COUNT = NEUTRAL_FRAME + 1
# Append prop actions after the original atlas so gaze/neutral indices stay fixed.
EXTRA_CLIPS = {
    'typing': ('linghao-typing-v1.png', (160, 120, 100, 120, 100, 140, 120, 180)),
    'using-mouse': ('linghao-mouse-v1.png', (180, 140, 140, 140, 180, 160, 140, 220)),
}
offset = BASE_FRAME_COUNT
for name, (_, holds) in EXTRA_CLIPS.items():
    CLIPS[name] = (offset, holds)
    offset += len(holds)
FRAME_COUNT = offset
MANUAL_ACTIONS = ('waving', 'jumping', 'failed', 'waiting', 'running', 'review', *EXTRA_CLIPS)
ACTION_REPEATS = {'typing': 3, 'using-mouse': 2}


def duration(name):
    return sum(CLIPS[name][1]) / 1000


def frame_at(name, elapsed, *, loop=False):
    start, durations = CLIPS[name]
    milliseconds = max(0, elapsed) * 1000
    total = sum(durations)
    if loop:
        milliseconds %= total
    for index, hold in enumerate(durations):
        if milliseconds < hold:
            return start + index
        milliseconds -= hold
    return start + len(durations) - 1


def look_direction(dx, dy):
    """Clockwise screen coordinates: up=0, right=4, down=8, left=12."""
    angle = math.degrees(math.atan2(dx, -dy)) % 360
    return int((angle + 11.25) // 22.5) % 16
