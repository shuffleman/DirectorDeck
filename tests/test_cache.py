"""抽卡缓存指纹单测。"""

import unittest

from director_deck.core import cache


def sample_payload(**overrides):
    payload = {
        "resolved_hash": "sha1:abc",
        "prompt": "湖面，小舟",
        "mode": "t2va",
        "width": 640,
        "height": 352,
        "length": 124,
        "seed": 20264,
        "steps": 10,
        "denoise": 1.0,
        "guide_prev": None,
        "lock": {"applied": False},
    }
    payload.update(overrides)
    return payload


class FingerprintTest(unittest.TestCase):
    def test_stable(self):
        self.assertEqual(cache.segment_fingerprint(sample_payload()),
                         cache.segment_fingerprint(sample_payload()))

    def test_seed_changes(self):
        self.assertNotEqual(cache.segment_fingerprint(sample_payload()),
                            cache.segment_fingerprint(sample_payload(seed=1)))

    def test_prompt_changes(self):
        self.assertNotEqual(cache.segment_fingerprint(sample_payload()),
                            cache.segment_fingerprint(sample_payload(prompt="别的画面")))

    def test_guide_previous_changes(self):
        self.assertNotEqual(cache.segment_fingerprint(sample_payload()),
                            cache.segment_fingerprint(sample_payload(guide_prev="abc")))

    def test_schema_invalidates(self):
        old = cache.segment_fingerprint(sample_payload())
        original = cache.CACHE_SCHEMA
        try:
            cache.CACHE_SCHEMA = original + 1
            self.assertNotEqual(old, cache.segment_fingerprint(sample_payload()))
        finally:
            cache.CACHE_SCHEMA = original

    def test_stem_and_validation(self):
        fingerprint = cache.segment_fingerprint(sample_payload())
        self.assertTrue(cache.is_valid_fingerprint(fingerprint))
        self.assertEqual(len(cache.cache_stem(fingerprint)), 32)
        self.assertFalse(cache.is_valid_fingerprint("abc"))


if __name__ == "__main__":
    unittest.main()
