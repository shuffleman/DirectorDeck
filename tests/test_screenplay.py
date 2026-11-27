"""剧本整理纯函数单测（不装 ComfyUI / 不联网）。"""

from __future__ import annotations

import unittest

from director_deck.core import screenplay as sp
from director_deck.core import script as script_lib


GOOD_JSON = {
    "title": "雨夜重逢",
    "characters": [
        {"id": "S1", "name": "女主", "image_slot": 1, "audio_slot": 1,
         "voice": "年轻女性，清亮温柔"},
        {"id": "S2", "name": "男主", "image_slot": 2, "audio_slot": 2,
         "voice": "年轻男性，低沉沉稳"},
    ],
    "segments": [
        {"seconds": 5, "scene": "雨夜老宅门口",
         "actions": "女主撑伞站在台阶下", "image_refs": [1, 2],
         "dialogue": [
             {"speaker": "S1", "text": "你终于回来了。", "at": 0.8},
             {"speaker": "S2", "text": "这十年我一直在找你。", "at": 2.6},
         ]},
        {"seconds": 5, "scene": "门内",
         "actions": "男主侧身让路", "image_refs": [],
         "dialogue": []},
    ],
}


class ExtractJsonTest(unittest.TestCase):
    def test_plain(self):
        import json
        self.assertEqual(sp.extract_json(json.dumps(GOOD_JSON, ensure_ascii=False))["title"], "雨夜重逢")

    def test_fenced(self):
        text = "```json\n{\"title\": \"x\", \"segments\": []}\n```"
        self.assertEqual(sp.extract_json(text)["title"], "x")

    def test_noisy_prefix(self):
        text = "好的，下面是剧本：\n{\"title\": \"y\", \"segments\": []}\n希望你喜欢"
        self.assertEqual(sp.extract_json(text)["title"], "y")

    def test_not_json(self):
        self.assertIsNone(sp.extract_json("抱歉，我不能这么做。"))


class NormalizeTest(unittest.TestCase):
    def test_normalize(self):
        data = dict(GOOD_JSON)
        data["segments"] = GOOD_JSON["segments"][:2]
        plan = sp.normalize_screenplay(data, default_seconds=5, max_segments=3, language="中文")
        self.assertEqual(len(plan["characters"]), 2)
        self.assertEqual(len(plan["segments"]), 2)
        self.assertEqual(plan["segments"][0]["image_refs"], [1, 2])
        self.assertEqual(plan["segments"][0]["dialogue"][0]["speaker"], "女主")

    def test_seconds_clamped_and_truncated(self):
        data = {"characters": [], "segments": [
            {"seconds": 999, "actions": "x", "dialogue": []},
            {"seconds": 2, "actions": "y", "dialogue": []},
        ]}
        plan = sp.normalize_screenplay(data, default_seconds=5, max_segments=1)
        self.assertEqual(len(plan["segments"]), 1)
        self.assertEqual(plan["segments"][0]["seconds"], 60)
        self.assertTrue(plan["warnings"])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            sp.normalize_screenplay({"segments": []})


class ScriptTextTest(unittest.TestCase):
    def test_script_text_roundtrip(self):
        plan = sp.normalize_screenplay(GOOD_JSON, default_seconds=5, max_segments=3)
        text = sp.screenplay_to_script_text(plan)
        self.assertIn("第1段（5秒）", text)
        self.assertIn("@图片1", text)
        self.assertIn("女主：你终于回来了。", text)
        parsed = script_lib.parse_script(text, mode="header", default_seconds=5)
        self.assertEqual(len(parsed["segments"]), 2)
        self.assertEqual(parsed["segments"][0]["refs"], [1, 2])
        self.assertEqual(parsed["segments"][0]["dialogue"][0]["character"], "女主")
        self.assertEqual(parsed["total_seconds"], 10)

    def test_action_colon_sanitized(self):
        plan = sp.normalize_screenplay(
            {"characters": [], "segments": [
                {"seconds": 5, "actions": "注意：门外有人", "dialogue": []}]},
            default_seconds=5, max_segments=1)
        text = sp.screenplay_to_script_text(plan)
        self.assertNotIn("注意：", text)  # 冒号被替换掉，避免被当成对白

    def test_voice_lines(self):
        plan = sp.normalize_screenplay(GOOD_JSON, default_seconds=5, max_segments=3)
        lines = sp.screenplay_to_voice_lines(plan)
        self.assertIn("女主 @0.80 |", lines)
        self.assertIn("男主 @2.60 |", lines)
        self.assertEqual(len(lines.splitlines()), 2)

    def test_character_map(self):
        plan = sp.normalize_screenplay(GOOD_JSON, default_seconds=5, max_segments=3)
        mapping = sp.screenplay_to_character_map(plan)
        self.assertIn("女主 | @图片1 | 音频槽1", mapping)


class V6Test(unittest.TestCase):
    def test_v6_to_plan(self):
        raw = (
            "【第1段｜5秒】\n"
            "integrated_multimodal_description: [Shot 1] 雨夜门口。<Picture 1><Picture 2>\n"
            "0.8～2.2秒：(S1) says: <d>[Chinese]你终于回来了。</d> 女主轻声说。\n"
            "2.6～4.2秒：(S2) says: <d>[Chinese]我一直在找你。</d> 男主向前一步。\n"
            "overall_soundscape: 雨声。\nnon_diegetic_music: N/A\n"
        )
        plan = sp.v6_to_screenplay(raw)
        self.assertEqual(len(plan["segments"]), 1)
        self.assertEqual(plan["segments"][0]["image_refs"], [1, 2])
        self.assertEqual(len(plan["segments"][0]["dialogue"]), 2)
        text = sp.screenplay_to_script_text(plan)
        parsed = script_lib.parse_script(text, mode="header", default_seconds=5)
        self.assertEqual(len(parsed["segments"]), 1)
        self.assertIn("你终于回来了。", text)

    def test_v6_without_header_raises(self):
        with self.assertRaises(ValueError):
            sp.v6_to_screenplay("没有段头的文本")


if __name__ == "__main__":
    unittest.main()
