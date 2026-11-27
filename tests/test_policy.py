"""分段覆盖/继承解析单测（核心契约 §3/§4）。"""

import json
import unittest

from director_deck.core import policy
from director_deck.core.types import DirectorError


def base_defaults():
    return {
        "bundle": {"fl2va_model": "m", "ref2va_model": "m", "text_encoder": "te",
                   "video_vae": "v", "audio_vae": "a", "loras": [], "vram_tier": "12G"},
        "config": {"width": 640, "height": 352, "fps": 24, "segment_seconds": 5.0,
                   "handoff_frames": 22, "sampler_name": "er_sde"},
        "assets": {"slots": [{"slot": 1, "path": "a.png"}], "audios": [], "videos": []},
        "cast": {"roles": [{"id": "girl", "name": "女主"}]},
        "brief": None,
    }


def full_policies(**overrides):
    values = {
        "bundle_policy": "provided",
        "config_policy": "inherit",
        "assets_policy": "inherit",
        "brief_policy": "inherit",
        "cast_policy": "inherit",
        "continuity": "start",
    }
    values.update(overrides)
    return values


class ExplicitPolicyTest(unittest.TestCase):
    def test_unset_policy_rejected(self):
        policies = full_policies()
        policies["assets_policy"] = "unset"
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(index=0, policies=policies, defaults=base_defaults())
        self.assertEqual(ctx.exception.code, "DD-E001")

    def test_missing_policy_rejected(self):
        policies = full_policies()
        policies.pop("cast_policy")
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(index=0, policies=policies, defaults=base_defaults())
        self.assertEqual(ctx.exception.code, "DD-E001")

    def test_illegal_choice_rejected(self):
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(index=0, policies=full_policies(assets_policy="copy"),
                                   defaults=base_defaults())
        self.assertEqual(ctx.exception.code, "DD-E004")


class FirstSegmentTest(unittest.TestCase):
    def test_first_segment_ok(self):
        res = policy.resolve_segment(
            index=0, policies=full_policies(),
            sockets={"bundle": base_defaults()["bundle"]},
            defaults=base_defaults())
        self.assertEqual(res.continuity, "start")
        self.assertEqual(res.bundle["fl2va_model"], "m")
        self.assertEqual(res.assets["slots"][0]["path"], "a.png")
        self.assertTrue(res.hash.startswith("sha1:"))

    def test_first_segment_missing_bundle(self):
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(index=0, policies=full_policies(), defaults=base_defaults())
        self.assertEqual(ctx.exception.code, "DD-E002")

    def test_first_segment_continuity_must_start(self):
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(
                index=0, policies=full_policies(continuity="guide_tail"),
                sockets={"bundle": base_defaults()["bundle"]}, defaults=base_defaults())
        self.assertEqual(ctx.exception.code, "DD-E004")


class ChainTest(unittest.TestCase):
    def _chain(self):
        defaults = base_defaults()
        first = policy.resolve_segment(
            index=0, policies=full_policies(),
            sockets={"bundle": defaults["bundle"]}, defaults=defaults)
        return defaults, first

    def test_second_segment_inherit_all(self):
        defaults, first = self._chain()
        policies = full_policies(bundle_policy="inherit", continuity="guide_tail")
        res = policy.resolve_segment(index=1, policies=policies, previous=first,
                                     defaults=defaults)
        self.assertEqual(res.continuity, "guide_tail")
        self.assertEqual(res.guide["source_index"], 0)
        self.assertEqual(res.bundle, first.bundle)
        self.assertEqual(res.assets, first.assets)

    def test_bundle_only_at_head(self):
        defaults, first = self._chain()
        policies = full_policies(bundle_policy="provided", continuity="guide_tail")
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(index=1, policies=policies, previous=first,
                                   defaults=defaults)
        self.assertEqual(ctx.exception.code, "DD-E004")

    def test_guide_tail_requires_previous(self):
        defaults = base_defaults()
        policies = full_policies(bundle_policy="inherit", continuity="guide_tail")
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(index=1, policies=policies, previous=None,
                                   defaults=defaults)
        self.assertEqual(ctx.exception.code, "DD-E008")

    def test_assets_replace(self):
        defaults, first = self._chain()
        replacement = {"slots": [{"slot": 1, "path": "new.png"}]}
        policies = full_policies(bundle_policy="inherit", continuity="none",
                                 assets_policy="replace")
        res = policy.resolve_segment(index=1, policies=policies, previous=first,
                                     sockets={"assets": replacement}, defaults=defaults)
        self.assertEqual(res.assets["slots"][0]["path"], "new.png")

    def test_assets_clear(self):
        defaults, first = self._chain()
        policies = full_policies(bundle_policy="inherit", continuity="none",
                                 assets_policy="clear")
        res = policy.resolve_segment(index=1, policies=policies, previous=first,
                                     defaults=defaults)
        self.assertIsNone(res.assets["slots"][0]["path"])

    def test_assets_merge_by_slot(self):
        defaults, first = self._chain()
        override = {"slots": [{"slot": 2, "path": "new2.png"}]}
        policies = full_policies(bundle_policy="inherit", continuity="none",
                                 assets_policy="merge")
        res = policy.resolve_segment(index=1, policies=policies, previous=first,
                                     sockets={"assets": override}, defaults=defaults)
        self.assertEqual(res.assets["slots"][0]["path"], "a.png")     # 继承
        self.assertEqual(res.assets["slots"][1]["path"], "new2.png")  # 覆盖

    def test_explicit_policy_requires_socket(self):
        defaults, first = self._chain()
        policies = full_policies(bundle_policy="inherit", continuity="none",
                                 assets_policy="replace")
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(index=1, policies=policies, previous=first,
                                   defaults=defaults)
        self.assertEqual(ctx.exception.code, "DD-E002")


class CastTest(unittest.TestCase):
    def test_merge_by_character(self):
        defaults = base_defaults()
        defaults["cast"] = {"roles": [{"id": "girl", "name": "女主", "voice": "v1"},
                                      {"id": "boy", "name": "男主", "voice": "v1"}]}
        first = policy.resolve_segment(
            index=0, policies=full_policies(), sockets={"bundle": defaults["bundle"]},
            defaults=defaults)
        override = {"roles": [{"id": "girl", "name": "女主", "voice": "v2"}], "lock_audio": True}
        policies = full_policies(bundle_policy="inherit", continuity="none",
                                 cast_policy="merge_by_character")
        res = policy.resolve_segment(index=1, policies=policies, previous=first,
                                     sockets={"cast": override}, defaults=defaults)
        roles = {role["id"]: role for role in res.cast["roles"]}
        self.assertEqual(roles["girl"]["voice"], "v2")
        self.assertEqual(roles["boy"]["voice"], "v1")
        self.assertTrue(res.cast["lock_audio"])


class ConfigOverrideTest(unittest.TestCase):
    def test_allowed_override(self):
        defaults, first = None, None
        defaults = base_defaults()
        first = policy.resolve_segment(
            index=0, policies=full_policies(), sockets={"bundle": defaults["bundle"]},
            defaults=defaults)
        policies = full_policies(bundle_policy="inherit", continuity="none",
                                 config_policy="overrides")
        res = policy.resolve_segment(index=1, policies=policies, previous=first,
                                     sockets={"config_override": {"segment_seconds": 3.0,
                                                                  "preview": False}},
                                     defaults=defaults)
        self.assertEqual(res.config["segment_seconds"], 3.0)
        self.assertFalse(res.config["preview"])

    def test_disallowed_override(self):
        defaults = base_defaults()
        first = policy.resolve_segment(
            index=0, policies=full_policies(), sockets={"bundle": defaults["bundle"]},
            defaults=defaults)
        policies = full_policies(bundle_policy="inherit", continuity="none",
                                 config_policy="overrides")
        with self.assertRaises(DirectorError) as ctx:
            policy.resolve_segment(index=1, policies=policies, previous=first,
                                   sockets={"config_override": {"width": 1080}},
                                   defaults=defaults)
        self.assertEqual(ctx.exception.code, "DD-E006")


class SerializableTest(unittest.TestCase):
    """回归测试：曾经把 VAE 对象塞进 segment 元数据，ComfyUI 写 history 时 JSON 崩了。"""

    def test_canonical_is_json_safe(self):
        defaults = base_defaults()
        fake_bundle = {**defaults["bundle"], "bundle_id": "sha1:test",
                       "spec": {"fl2va_model": "m"}, "model": object(), "vae": object()}
        defaults["bundle"] = fake_bundle
        # 锁音 cast 里带运行期音频张量（用 object 模拟不可序列化对象），
        # canonical 必须把它摘掉，否则写 history 会炸。
        defaults["cast"] = {"roles": [{"id": "girl", "name": "女主", "start": 0.0,
                                       "voice": {"kind": "audio", "slot": 1},
                                       "audio_data": object()}],
                            "lock_audio": True}
        resolved = policy.resolve_segment(
            index=0, policies=full_policies(), sockets={"bundle": fake_bundle},
            defaults=defaults)
        text = json.dumps(resolved.canonical(), ensure_ascii=False)  # 不能抛 TypeError
        self.assertIn("sha1:test", text)
        self.assertIn("fl2va_model", text)
        self.assertIn("girl", text)
        self.assertNotIn("audio_data", text)


class HashTest(unittest.TestCase):
    def test_hash_changes_with_assets(self):
        defaults = base_defaults()
        first = policy.resolve_segment(
            index=0, policies=full_policies(), sockets={"bundle": defaults["bundle"]},
            defaults=defaults)
        defaults2 = base_defaults()
        defaults2["assets"] = {"slots": [{"slot": 1, "path": "different.png"}]}
        second = policy.resolve_segment(
            index=0, policies=full_policies(), sockets={"bundle": defaults2["bundle"]},
            defaults=defaults2)
        self.assertNotEqual(first.hash, second.hash)

    def test_hash_stable(self):
        defaults = base_defaults()
        run = lambda: policy.resolve_segment(
            index=0, policies=full_policies(), sockets={"bundle": defaults["bundle"]},
            defaults=defaults).hash
        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
