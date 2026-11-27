"""latent 尾帧续写的 token 边界单测（纯数学）。"""

import unittest

from director_deck.core import frames


class TokenMathTest(unittest.TestCase):
    def test_token_count(self):
        self.assertEqual(frames.video_latent_tokens(5), 2)
        self.assertEqual(frames.video_latent_tokens(124), 37)
        self.assertEqual(frames.video_latent_tokens(158), 47)
        self.assertEqual(frames.video_latent_tokens(362), 107)

    def test_boundaries_sum_to_frames(self):
        for frame_count in (124, 158, 175, 243):
            tokens = frames.video_latent_tokens(frame_count)
            boundaries = frames.token_frame_boundaries(tokens)
            self.assertEqual(boundaries[-1], frame_count, frame_count)

    def test_tail_boundary_exact(self):
        # 158 帧、head=22：token 边界正好有 136，因此搬 7 个 token、遮 22 帧。
        k0, masked = frames.tail_token_boundary(158, 22)
        self.assertEqual(masked, 22)
        self.assertEqual(k0, 40)
        self.assertEqual(47 - k0, 7)

    def test_tail_boundary_never_shorter_than_head(self):
        for sample in (124, 158, 175, 243, 362):
            for head in (5, 22, 39, 56):
                k0, masked = frames.tail_token_boundary(sample, head)
                self.assertGreaterEqual(masked, head, (sample, head))
                self.assertLessEqual(masked - head, 3, (sample, head))

    def test_tail_boundary_first_segment_guard(self):
        # head 超过整段时，最多搬全部 token（masked = 全部帧）。
        k0, masked = frames.tail_token_boundary(124, 200)
        self.assertGreaterEqual(masked, 124)
        self.assertEqual(k0, 0)


if __name__ == "__main__":
    unittest.main()
