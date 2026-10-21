"""Platform-independent movement rules; coordinates are logical desktop pixels."""
from dataclasses import dataclass, field
import random

from animation import CLIPS, MANUAL_ACTIONS, duration, frame_at

IDLE_SECONDS = (35, 80)
LONG_IDLE_SECONDS = (120, 180)
WALK_SECONDS = (1.8, 3.2)
OBSERVE_SECONDS = (5, 8)


@dataclass
class PetModel:
    x: float = 0
    y: float = 0
    direction: int = 1
    mode: str = 'idle'
    paused: bool = False
    elapsed: float = 0
    remaining: float = field(default_factory=lambda: random.uniform(35, 60))
    speed: float = 32
    idle_after_observation: float = 0
    action: str = 'review'

    def settle(self, *, observe_chance=.65, minimum_idle=35):
        """A short, one-shot action is followed by a much longer quiet stay."""
        interval = LONG_IDLE_SECONDS if random.random() < .2 else IDLE_SECONDS
        quiet_seconds = max(minimum_idle, random.uniform(*interval))
        self.elapsed = 0
        if random.random() < observe_chance:
            self.mode = 'observe'
            self.action = random.choice(('review', 'running'))
            self.remaining = random.uniform(*OBSERVE_SECONDS)
            self.idle_after_observation = quiet_seconds
        else:
            self.mode = 'idle'
            self.remaining = quiet_seconds
            self.idle_after_observation = 0

    def play(self, action):
        if action not in MANUAL_ACTIONS:
            raise ValueError('Unknown pet action: ' + action)
        self.mode, self.action, self.elapsed = 'action', action, 0
        self.remaining = duration(action) + .35

    def clamp(self, left, top, right, bottom, width, height):
        self.x = max(left, min(self.x, max(left, right - width)))
        self.y = max(top, min(self.y, max(top, bottom - height)))

    def tick(self, dt, left, right, width):
        if self.paused or self.mode == 'rest':
            return
        # A suspended laptop must not advance the pet across the whole desktop.
        dt = max(0, min(dt, .1))
        self.elapsed += dt
        if self.mode == 'drag':
            return  # Animate the held pet without moving it independently.
        self.remaining -= dt
        if self.mode == 'walk':
            self.x += self.direction * self.speed * dt
            end = max(left, right - width)
            if self.x <= left:
                self.x, self.direction = left, 1
            elif self.x >= end:
                self.x, self.direction = end, -1
        if self.remaining <= 0:
            if self.mode == 'walk':
                self.settle()
            elif self.mode == 'observe':
                self.mode, self.elapsed = 'idle', 0
                self.remaining = self.idle_after_observation
                self.idle_after_observation = 0
            elif self.mode in ('react', 'action'):
                self.settle(observe_chance=0, minimum_idle=60)
            else:
                self.mode, self.elapsed = 'walk', 0
                # Choose once per walking bout; drawing every tick would jitter.
                self.direction = random.choice((-1, 1))
                if self.x <= left:
                    self.direction = 1
                elif self.x >= max(left, right - width):
                    self.direction = -1
                self.remaining = random.uniform(*WALK_SECONDS)

    def frame(self):
        if self.mode in ('walk', 'drag'):
            name = 'running-right' if self.direction > 0 else 'running-left'
            return frame_at(name, self.elapsed, loop=True)
        if self.mode == 'rest':
            return CLIPS['idle'][0] + 4
        if self.mode == 'react':
            return frame_at('waving', self.elapsed)
        if self.mode in ('observe', 'action'):
            return frame_at(self.action, self.elapsed)
        # Keep the authored idle micro-animation, with a long quiet gap.
        phase = self.elapsed % 9.5
        return frame_at('idle', phase - 8.4) if phase >= 8.4 else 0
