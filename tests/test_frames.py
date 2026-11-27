"""帧数学单测：与 H3 实测一致（124/158/136 等）。"""

import unittest

from director_deck.core import frames
from director_deck.core.types import DirectorError


class GridLengthTest(unittest.TestCase):
    def test_seconds_to_grid(self):
        self.assertEqual(frames.grid_length(5), 124)
        self.assertEqual(frames.grid_length(10), 243)
        self.assertEqual(frames.grid_length(15), 362)

    def test_rounding_is_nearest(self):
        # 3s -> (72-5)/17 = 3.94 -> 4 -> 73
        self.assertEqual(frames.grid_length(3), 73)

    def test_valid_length(self):
        for value in (5, 22, 124, 158, 175, 243, 294, 362):
            self.assertTrue(frames.is_valid_length(value), value)
        for value in (0, 1, 100, 123, 125):
            self.assertFalse(frames.is_valid_length(value), value)

    def test_grid_round_up(self):
        self.assertEqual(frames.grid_round_up(146), 158)
        self.assertEqual(frames.grid_round_up(158), 158)
        self.assertEqual(frames.grid_round_up(0), 5)

    def test_validate_length(self):
        self.assertEqual(frames.validate_length(124), 124)
        with self.assertRaises(DirectorError) as ctx:
            frames.validate_length(123)
        self.assertEqual(ctx.exception.code, "DD-E020")


class SegmentPlanTest(unittest.TestCase):
    def test_first_segment(self):
        plan = frames.segment_plan(0, 5.0, handoff_frames=22)
        self.assertEqual((plan.head, plan.delivery, plan.sample), (0, 124, 124))
        self.assertEqual(plan.length, 124)

    def test_second_segment(self):
        plan = frames.segment_plan(1, 5.0, handoff_frames=22)
        self.assertEqual(plan.head, 22)
        self.assertEqual(plan.sample, 158)
        self.assertEqual(plan.delivery, 136)

    def test_second_segment_handoff_39(self):
        plan = frames.segment_plan(1, 5.0, handoff_frames=39)
        self.assertEqual((plan.head, plan.sample, plan.delivery), (39, 175, 136))

    def test_context_frames_snap(self):
        self.assertEqual(frames.context_frames_for(1), 5)
        self.assertEqual(frames.context_frames_for(6), 22)
        self.assertEqual(frames.context_frames_for(23), 39)
        self.assertEqual(frames.context_frames_for(40), 56)
        self.assertEqual(frames.context_frames_for(999), 56)

    def test_chain_timeline(self):
        plans = frames.plan_chain([{"seconds": 5}, {"seconds": 5}, {"seconds": 5}],
                                  handoff_frames=22)
        self.assertEqual([p.delivery for p in plans], [124, 136, 136])
        self.assertAlmostEqual(plans[0].timeline_start, 0.0)
        self.assertAlmostEqual(plans[1].timeline_start, 124 / 24)
        self.assertAlmostEqual(plans[2].timeline_start, 260 / 24)
        self.assertEqual(frames.total_frames(plans), 396)
        self.assertAlmostEqual(frames.total_duration(plans), 16.5)

    def test_canvas_validation(self):
        frames.validate_canvas(640, 352)
        with self.assertRaises(DirectorError) as ctx:
            frames.validate_canvas(650, 352)
        self.assertEqual(ctx.exception.code, "DD-E021")


if __name__ == "__main__":
    unittest.main()
