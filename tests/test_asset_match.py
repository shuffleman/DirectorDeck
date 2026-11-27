"""素材自动匹配单测（纯 Python）。"""

from __future__ import annotations

import unittest

from director_deck.core import asset_match as am
from director_deck.core import screenplay as sp
from director_deck.core import script as script_lib


def slots(*items):
    result = []
    for index, (name, role) in enumerate(items, start=1):
        result.append({"slot": index, "name": name, "role": role, "filled": True})
    return result


PLAN = {
    "characters": [
        {"id": "S1", "name": "女主", "image_slot": None, "audio_slot": None, "voice": ""},
        {"id": "S2", "name": "男主", "image_slot": None, "audio_slot": None, "voice": ""},
        {"id": "S3", "name": "林澈", "image_slot": None, "audio_slot": None, "voice": ""},
    ],
    "segments": [
        {"index": 1, "seconds": 5, "scene": "客厅", "actions": "女主和男主在客厅对视",
         "image_refs": [], "dialogue": [
             {"speaker_id": "S1", "speaker": "女主", "text": "你回来了。", "at": None},
             {"speaker_id": "S2", "speaker": "男主", "text": "嗯。", "at": None}]},
        {"index": 2, "seconds": 5, "scene": "卧室", "actions": "林澈推开门走进卧室",
         "image_refs": [], "dialogue": [
             {"speaker_id": "S3", "speaker": "林澈", "text": "我回来了。", "at": None}]},
    ],
}


class CharacterMatchTest(unittest.TestCase):
    def test_name_match(self):
        result = am.match_characters(
            PLAN, slots(("女主", "reference"), ("男主", "reference"),
                        ("林澈", "reference"), ("客厅", "scene"), ("卧室", "scene")))
        self.assertEqual(result["S1"]["image_slot"], 1)
        self.assertEqual(result["S2"]["image_slot"], 2)
        self.assertEqual(result["S3"]["image_slot"], 3)

    def test_order_fallback(self):
        result = am.match_characters(PLAN, slots(("图片1", ""), ("图片2", "")))
        self.assertEqual(result["S1"]["image_slot"], 1)
        self.assertEqual(result["S2"]["image_slot"], 2)
        self.assertIsNone(result["S3"]["image_slot"])
        self.assertIn("顺序兜底", result["S1"]["image_reason"])

    def test_audio_from_cast(self):
        cast = [{"id": "女主", "name": "女主", "voice": {"slot": 1}},
                {"id": "林澈", "name": "林澈", "voice": {"slot": 3}}]
        result = am.match_characters(PLAN, [], cast)
        self.assertEqual(result["S1"]["audio_slot"], 1)
        self.assertEqual(result["S3"]["audio_slot"], 3)
        self.assertEqual(result["S2"]["audio_slot"], None)

    def test_no_assets(self):
        result = am.match_characters(PLAN, [])
        self.assertIsNone(result["S1"]["image_slot"])
        self.assertIn("素材库为空", result["S1"]["image_reason"])


class SceneAndApplyTest(unittest.TestCase):
    def setUp(self):
        self.slot_list = slots(("女主", "reference"), ("男主", "reference"),
                               ("客厅", "scene"), ("卧室", "scene"))
        self.match = am.match_assets(PLAN, self.slot_list)
        self.plan, self.warnings = am.apply_matches(
            PLAN, self.match["characters"], self.match["scenes"])

    def test_scene_match(self):
        self.assertEqual(self.match["scenes"][1]["slot"], 3)
        self.assertEqual(self.match["scenes"][2]["slot"], 4)

    def test_refs_written_back(self):
        seg1 = self.plan["segments"][0]
        seg2 = self.plan["segments"][1]
        self.assertEqual(seg1["image_refs"], [1, 2, 3])
        self.assertEqual(seg2["image_refs"], [3, 4])  # 林澈 + 卧室背景

    def test_script_text_and_parse(self):
        text = sp.screenplay_to_script_text(self.plan)
        parsed = script_lib.parse_script(text, mode="header")
        self.assertEqual(len(parsed["segments"]), 2)
        self.assertIn(3, parsed["segments"][0]["refs"])
        self.assertIn(4, parsed["segments"][1]["refs"])

    def test_mapping_report(self):
        report = am.mapping_report(self.match["characters"], self.match["scenes"])
        self.assertIn("女主 | @图片1", report)
        self.assertIn("第1段 | @图片3", report)

    def test_explicit_refs_preserved(self):
        plan = {"characters": [], "segments": [
            {"index": 1, "seconds": 5, "scene": "", "actions": "空镜",
             "image_refs": [5], "dialogue": []}]}
        matched, _ = am.apply_matches(plan, {}, {})
        self.assertEqual(matched["segments"][0]["image_refs"], [5])


class FromParsedScriptTest(unittest.TestCase):
    def test_text_import_plan(self):
        text = ("第1段（5秒）\n[画面] 女主推开门走进客厅。\n女主：我回来了。\n\n"
                "第2段（5秒）\n[画面] 男主站在窗边。\n男主：欢迎回家。")
        parsed = script_lib.parse_script(text, mode="header")
        plan = sp.screenplay_from_parsed_script(parsed)
        self.assertEqual(len(plan["segments"]), 2)
        self.assertEqual([c["name"] for c in plan["characters"]], ["女主", "男主"])
        self.assertNotIn("女主：我回来了", plan["segments"][0]["actions"])


if __name__ == "__main__":
    unittest.main()
