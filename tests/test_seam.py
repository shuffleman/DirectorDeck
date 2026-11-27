"""接缝/曝光匹配单测（纯数学，不需要 GPU）。"""

import unittest

from director_deck.core import seam


class ExposurePlanTest(unittest.TestCase):
    def test_identical_no_change(self):
        means = [0.5] * 12
        plan = seam.exposure_plan(means, means, window=12)
        self.assertFalse(plan["apply"])
        self.assertAlmostEqual(plan["offset"], 0.0, places=6)

    def test_darker_cur_gets_brightened(self):
        # 2% 的亮度漂移（现实里常见的段间曝光差），应该被平滑修正。
        prev = [0.50] * 12
        cur = [0.48] * 12
        plan = seam.exposure_plan(prev, cur, window=12)
        self.assertTrue(plan["apply"])
        self.assertGreater(plan["offset"], 0.0)       # 下一段要提亮
        self.assertLessEqual(plan["offset"], 0.10)    # 但不超过上限
        self.assertFalse(plan["hard_cut"])

    def test_gain_clamped(self):
        prev = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        cur = [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09]  # 差 10 倍
        plan = seam.exposure_plan(prev, cur, window=8, gain_limit=0.04)
        self.assertGreaterEqual(plan["gain"], 0.96)
        self.assertLessEqual(plan["gain"], 1.04)

    def test_hard_cut_detected(self):
        prev = [0.8] * 12
        cur = [0.1] * 12
        plan = seam.exposure_plan(prev, cur, window=12)
        self.assertTrue(plan["hard_cut"])
        self.assertFalse(plan["apply"])

    def test_short_window(self):
        plan = seam.exposure_plan([0.5], [0.4], window=12)
        self.assertFalse(plan["apply"])
        self.assertEqual(plan["window"], 1)

    def test_result_is_json_friendly(self):
        import json
        plan = seam.exposure_plan([0.5] * 12, [0.45] * 12)
        json.dumps(plan)  # 不能抛异常


if __name__ == "__main__":
    unittest.main()
