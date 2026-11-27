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


class DbAndLimiterTest(unittest.TestCase):
    def test_db_roundtrip(self):
        self.assertAlmostEqual(audio.db_to_linear(-8.0), 0.3981, places=3)
        self.assertAlmostEqual(audio.linear_to_db(0.3981), -8.0, places=2)

    def test_limiter(self):
        self.assertEqual(audio.apply_limiter(0.5), 1.0)
        self.assertAlmostEqual(audio.apply_limiter(2.0, ceiling=0.99), 0.495, places=3)
        self.assertEqual(audio.apply_limiter(0.0), 1.0)

    def test_frame_rms(self):
        values = [1.0, -1.0, 1.0, -1.0, 0.0, 0.0]
        rms = audio.frame_rms(values, 2)
        self.assertEqual(len(rms), 3)
        self.assertAlmostEqual(rms[0], 1.0)
        self.assertAlmostEqual(rms[1], 1.0)
        self.assertAlmostEqual(rms[2], 0.0)


class MixGainsTest(unittest.TestCase):
    def _energies(self):
        # 20 帧（10ms/帧，共 200ms）：A 全程说话，B 从第 5 帧开始说话。
        a = [1.0] * 20
        b = [0.0] * 5 + [1.0] * 15
        return [a, b]

    def test_sum_mode_no_ducking(self):
        gains = audio.mix_gains(self._energies(), [0, 0], mode="sum")
        self.assertTrue(all(abs(g - 1.0) < 1e-9 for g in gains[0]))
        self.assertTrue(all(abs(g - 1.0) < 1e-9 for g in gains[1]))

    def test_priority_ducks_lower_priority(self):
        energies = self._energies()
        gains = audio.mix_gains(energies, [2, 1], mode="priority",
                               duck_db=-8.0, attack_ms=20.0, release_ms=200.0,
                               frame_ms=10.0)
        self.assertAlmostEqual(gains[1][4], 1.0)      # 还没重叠
        self.assertLess(gains[1][10], 0.7)            # 已经压下去
        self.assertGreater(gains[1][10], 0.398)       # 但还在 attack 过程中
        self.assertGreater(gains[1][15], 0.398)       # 稳定后接近 -8dB
        self.assertLess(gains[1][15], 0.45)
        # 优先级高的 A 不该被压
        self.assertTrue(all(g > 0.999 for g in gains[0][:15]))

    def test_auto_duck_uses_louder_role(self):
        energies = [[0.2] * 10, [1.0] * 10]  # B 更响
        gains = audio.mix_gains(energies, [2, 1], mode="auto_duck",
                               duck_db=-6.0, attack_ms=10.0, release_ms=50.0)
        self.assertLess(gains[0][-1], 0.6)   # A 被压
        self.assertGreater(gains[1][-1], 0.999)  # B 不被压

    def test_release_recovers(self):
        # A 前 5 帧说话、之后停；B 全程说话且优先级更高 -> A 在重叠时被压，之后慢慢恢复
        a = [1.0] * 5 + [0.0] * 15
        b = [1.0] * 20
        gains = audio.mix_gains([a, b], [1, 2], mode="priority",
                               duck_db=-12.0, attack_ms=10.0, release_ms=100.0)
        self.assertLess(gains[0][3], 0.6)
        self.assertLess(gains[0][4], gains[0][5])       # 第 5 帧开始恢复
        self.assertGreater(gains[0][-1], gains[0][5])   # 越恢复越接近 1
        self.assertGreater(gains[0][-1], 0.8)

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            audio.mix_gains([[1.0]], mode="nope")

    def test_initial_gains_continue_envelope(self):
        # 第二段开头：B 从上一段结束时的 0.45 接着算，而不是弹回 1.0。
        energies = [[1.0] * 10, [1.0] * 10]
        gains = audio.mix_gains(energies, [2, 1], mode="priority",
                               duck_db=-8.0, attack_ms=10.0, release_ms=200.0,
                               initial_gains=[1.0, 0.45])
        self.assertGreater(gains[1][0], 0.39)
        self.assertLess(gains[1][0], 0.45)  # 从 0.45 继续往下压，不弹回 1.0
        # A 从 1.0 起步，保持不变。
        self.assertGreater(gains[0][0], 0.999)

    def test_equal_power_mix_weights(self):
        # 权重满足 cos²+sin²=1：交叉结束时应完全变成 b。
        mixed = audio.equal_power_mix([1.0] * 8, [0.0] * 8)
        self.assertLess(mixed[0], 1.0)
        self.assertLess(mixed[-1], 0.1)
        reversed_mix = audio.equal_power_mix([0.0] * 8, [1.0] * 8)
        self.assertLess(reversed_mix[0], 0.1)
        self.assertGreater(reversed_mix[-1], 0.9)


if __name__ == "__main__":
    unittest.main()
