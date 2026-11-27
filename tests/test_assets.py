"""素材槽位/引用/合并单测。"""

import unittest

from director_deck.core import assets
from director_deck.core.types import DirectorError


def make_assets(**slots):
    data = assets.empty_assets()
    for number, path in slots.items():
        idx = int(number.replace("slot", "")) - 1
        data["slots"][idx]["path"] = path
        data["slots"][idx]["name"] = path
    return data


class NormalizeTest(unittest.TestCase):
    def test_empty_has_nine_slots(self):
        data = assets.empty_assets()
        self.assertEqual(len(data["slots"]), 9)
        self.assertEqual([s["slot"] for s in data["slots"]], list(range(1, 10)))

    def test_normalize_is_stable(self):
        data = assets.normalize_assets({"slots": [{"slot": 3, "path": "a.png"}]})
        self.assertEqual(len(data["slots"]), 9)
        self.assertEqual(data["slots"][2]["path"], "a.png")
        self.assertIsNone(data["slots"][0]["path"])


class MergeTest(unittest.TestCase):
    def test_merge_by_slot(self):
        base = make_assets(slot1="a.png", slot2="b.png")
        override = make_assets(slot1="c.png")
        merged = assets.merge_assets(base, override)
        self.assertEqual(merged["slots"][0]["path"], "c.png")
        self.assertEqual(merged["slots"][1]["path"], "b.png")

    def test_merge_empty_override_keeps_base(self):
        base = make_assets(slot1="a.png")
        merged = assets.merge_assets(base, assets.empty_assets())
        self.assertEqual(merged["slots"][0]["path"], "a.png")


class RefTest(unittest.TestCase):
    def test_refs_in_text(self):
        refs = assets.refs_in_text("@图片1 和 @图片3，还有 @音频2")
        self.assertEqual(refs["images"], [1, 3])
        self.assertEqual(refs["audios"], [2])

    def test_validate_ok(self):
        data = make_assets(slot1="a.png")
        assets.validate_refs("@图片1", data)

    def test_validate_out_of_range(self):
        with self.assertRaises(DirectorError) as ctx:
            assets.validate_refs("@图片10", assets.empty_assets())
        self.assertEqual(ctx.exception.code, "DD-E010")

    def test_validate_empty_slot(self):
        with self.assertRaises(DirectorError) as ctx:
            assets.validate_refs("@图片2", make_assets(slot1="a.png"))
        self.assertEqual(ctx.exception.code, "DD-E011")

    def test_bind_prompt(self):
        data = make_assets(slot1="a.png", slot2="b.png")
        out = assets.bind_prompt("@图片1 的角色 与 @图片2", data)
        self.assertEqual(out, "<Picture 1> 的角色 与 <Picture 2>")

    def test_bound_slots(self):
        data = make_assets(slot2="b.png")
        self.assertEqual(assets.binds_assets(data), [2])

    def test_hash_changes_with_slot(self):
        self.assertNotEqual(assets.assets_hash(make_assets(slot1="a.png")),
                            assets.assets_hash(make_assets(slot1="b.png")))


if __name__ == "__main__":
    unittest.main()
