"""Behavior checks for the pet's quiet walking / observation rhythm."""
import random
import unittest
import math

from model import PetModel
from animation import CLIPS, FRAME_COUNT, MANUAL_ACTIONS, duration, frame_at, look_direction


class QuietMovementTests(unittest.TestCase):
    def setUp(self):
        random.seed(20261020)

    def test_walk_is_followed_by_a_long_stationary_stay(self):
        pet = PetModel(x=500, mode='walk', remaining=.01)
        pet.tick(.1, 0, 1400, 240)
        self.assertIn(pet.mode, ('idle', 'observe'))
        if pet.mode == 'observe':
            self.assertGreaterEqual(pet.idle_after_observation, 35)
        else:
            self.assertGreaterEqual(pet.remaining, 35)
        position = pet.x
        for _ in range(300):
            pet.tick(.1, 0, 1400, 240)
            self.assertEqual(pet.x, position)

    def test_observation_plays_once_then_stays_quiet(self):
        pet = PetModel(x=500)
        pet.settle(observe_chance=1)
        frames = set()
        while pet.mode == 'observe':
            frames.add(pet.frame())
            pet.tick(.1, 0, 1400, 240)
            self.assertEqual(pet.x, 500)
        start, holds = CLIPS[pet.action]
        self.assertEqual(frames, set(range(start, start+len(holds))))
        self.assertEqual(pet.mode, 'idle')
        self.assertGreaterEqual(pet.remaining, 35)

    def test_some_stays_are_two_to_three_minutes(self):
        stays = []
        pet = PetModel()
        for _ in range(1000):
            pet.settle(observe_chance=0)
            stays.append(pet.remaining)
        self.assertTrue(all(35 <= x <= 80 or 120 <= x <= 180 for x in stays))
        self.assertTrue(100 < sum(x >= 120 for x in stays) < 300)

    def test_placed_pet_can_stay_for_at_least_a_minute(self):
        for _ in range(100):
            pet = PetModel(x=500)
            pet.settle(minimum_idle=60)
            quiet = pet.idle_after_observation if pet.mode == 'observe' else pet.remaining
            self.assertGreaterEqual(quiet, 60)

    def test_pause_and_manual_rest_freeze_observation(self):
        pet = PetModel(x=500)
        pet.settle(observe_chance=1)
        pet.paused = True
        before = (pet.x, pet.elapsed, pet.remaining, pet.frame())
        pet.tick(.1, 0, 1400, 240)
        self.assertEqual(before, (pet.x, pet.elapsed, pet.remaining, pet.frame()))
        pet.paused = False
        pet.mode = 'rest'
        before = (pet.x, pet.elapsed, pet.remaining)
        pet.tick(.1, 0, 1400, 240)
        self.assertEqual(before, (pet.x, pet.elapsed, pet.remaining))

    def test_click_reaction_does_not_immediately_start_walking(self):
        pet = PetModel(x=500, mode='react', remaining=0)
        pet.tick(.1, 0, 1400, 240)
        self.assertEqual(pet.mode, 'idle')
        self.assertGreaterEqual(pet.remaining, 35)

    def test_hour_is_mostly_stationary_and_uses_both_directions(self):
        pet = PetModel(x=500)
        moving = 0
        directions = set()
        for _ in range(36000):
            before = pet.x
            pet.tick(.1, 0, 1400, 240)
            if pet.x != before:
                moving += .1
                directions.add(pet.direction)
            self.assertTrue(0 <= pet.x <= 1160)
        self.assertLess(moving/3600, .06)
        self.assertEqual(directions, {-1, 1})


class CodexAnimationTests(unittest.TestCase):
    def test_every_standard_clip_reaches_its_authored_frames_once(self):
        self.assertEqual(FRAME_COUNT, 74)  # 57 standard + 16 gaze + neutral.
        self.assertEqual([len(v[1]) for v in CLIPS.values()], [6,8,8,4,5,8,6,6,6])
        for name, (start, holds) in CLIPS.items():
            cursor = 0
            for index, hold in enumerate(holds):
                self.assertEqual(frame_at(name, (cursor+hold/2)/1000), start+index)
                cursor += hold
            self.assertEqual(frame_at(name, duration(name)+10), start+len(holds)-1)
            self.assertEqual(frame_at(name, duration(name), loop=True), start)

    def test_screen_clock_directions_do_not_swap_left_and_right(self):
        self.assertEqual([look_direction(*p) for p in [(0,-100),(100,0),(0,100),(-100,0)]], [0,4,8,12])
        for index in range(16):
            angle = math.radians(index*22.5)
            self.assertEqual(look_direction(math.sin(angle)*100, -math.cos(angle)*100), index)

    def test_left_and_right_use_different_authored_rows(self):
        pet = PetModel(mode='walk', direction=1, elapsed=.3)
        right = pet.frame()
        pet.direction = -1
        left = pet.frame()
        self.assertTrue(6 <= right < 14)
        self.assertTrue(14 <= left < 22)

    def test_manual_actions_finish_and_leave_a_quiet_minute(self):
        for action in MANUAL_ACTIONS:
            pet = PetModel(x=500)
            pet.play(action)
            while pet.mode == 'action':
                pet.tick(.05, 0, 1400, 240)
                self.assertEqual(pet.x, 500)
            self.assertEqual(pet.mode, 'idle')
            self.assertGreaterEqual(pet.remaining, 60)

    def test_drag_plays_its_pose_without_autonomous_motion(self):
        pet = PetModel(x=500, mode='drag', elapsed=0, remaining=7)
        before = pet.frame()
        for _ in range(4):
            pet.tick(.1, 0, 1400, 240)
        self.assertNotEqual(before, pet.frame())
        self.assertEqual((pet.x, pet.remaining), (500, 7))

    def test_paused_action_keeps_the_same_pose(self):
        pet = PetModel()
        pet.play('jumping')
        pet.tick(.1, 0, 1400, 240)
        pet.paused = True
        before = (pet.frame(), pet.elapsed, pet.remaining)
        pet.tick(.1, 0, 1400, 240)
        self.assertEqual(before, (pet.frame(), pet.elapsed, pet.remaining))


if __name__ == '__main__':
    unittest.main()
