"""Behavior checks for the pet's quiet walking / observation rhythm."""
import random
import unittest

from model import PetModel


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
        self.assertEqual(frames, {16, 17, 18, 19})
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


if __name__ == '__main__':
    unittest.main()
