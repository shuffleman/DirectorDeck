"""音频时间窗口单测（纯数学，锁音切片的依据）。"""

import unittest

from director_deck.core import audio


class SamplesTest(unittest.TestCase):
    def test_samples_for(self):
        self.assertEqual(audio.samples_for(1.0, 32000), 32000)
        self.assertEqual(audio.samples_for(0.5, 48000), 24000)
        self.assertEqual(audio.samples_for(0.0, 32000), 0)

    def test_overlap(self):
        self.assertEqual(audio.overlap(0, 5, 3, 8), 2)
        self.assertEqual(audio.overlap(0, 2, 5, 8), 0)
        self.assertEqual(audio.overlap(0, 10, 0, 10), 10)


class ClipWindowTest(unittest.TestCase):
    def test_clip_inside_segment(self):
        # 素材 0~10s，段 2~7s -> 从素材第 2s 取，放到段内第 0s，长 5s
        self.assertEqual(audio.clip_window(0, 10, 2, 7), (2.0, 0.0, 5.0))

    def test_segment_starts_before_clip(self):
        # 素材 5~10s，段 0~6s -> 从素材第 0s 取，放到段内第 5s，长 1s
        self.assertEqual(audio.clip_window(5, 10, 0, 6), (0.0, 5.0, 1.0))

    def test_no_overlap(self):
        self.assertIsNone(audio.clip_window(0, 2, 5, 7))

    def test_partial_overlap(self):
        self.assertEqual(audio.clip_window(0, 10, 8, 12), (8.0, 0.0, 2.0))


class SegmentSpanTest(unittest.TestCase):
    def test_first_segment(self):
        start, end = audio.segment_span(0.0, 0, 124)
        self.assertAlmostEqual(start, 0.0)
        self.assertAlmostEqual(end, 124 / 24)

    def test_chained_segment_moves_back_by_head(self):
        # 时间轴 5.1667s，head=22 帧 -> 采样起点要往前挪 22/24 秒
        start, end = audio.segment_span(124 / 24, 22, 158)
        self.assertAlmostEqual(start, (124 - 22) / 24)
        self.assertAlmostEqual(end, (124 - 22 + 158) / 24)

    def test_never_negative(self):
        start, _ = audio.segment_span(0.0, 22, 158)
        self.assertGreaterEqual(start, 0.0)


if __name__ == "__main__":
    unittest.main()
