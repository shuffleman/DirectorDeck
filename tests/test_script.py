"""剧本解析单测。"""

import unittest

from director_deck.core import script
from director_deck.core.types import DirectorError


class SecondsTest(unittest.TestCase):
    def test_seconds_formats(self):
        self.assertEqual(script.parse_seconds("（5秒）"), 5.0)
        self.assertEqual(script.parse_seconds("5s"), 5.0)
        self.assertEqual(script.parse_seconds("0:05"), 5.0)
        self.assertEqual(script.parse_seconds("（3.5秒）"), 3.5)

    def test_seconds_default(self):
        self.assertEqual(script.parse_seconds("没有时长", default=6.0), 6.0)

    def test_cn_numbers(self):
        self.assertEqual(script.cn_to_int("一"), 1)
        self.assertEqual(script.cn_to_int("十"), 10)
        self.assertEqual(script.cn_to_int("十二"), 12)
        self.assertEqual(script.cn_to_int("三"), 3)


class DialogueTest(unittest.TestCase):
    def test_dialogue_lines(self):
        lines = script.parse_dialogue("女主：你好\n男主: 再见\n「无名台词」\n普通描述")
        self.assertEqual(lines[0], {"character": "女主", "text": "你好"})
        self.assertEqual(lines[1], {"character": "男主", "text": "再见"})
        self.assertEqual(lines[2]["text"], "无名台词")
        self.assertEqual(len(lines), 3)


class ParseScriptTest(unittest.TestCase):
    HEADER_TEXT = "第1段（5秒）\n女主：你好\n第2段（3秒）\n男主：再见"

    def test_header_mode(self):
        data = script.parse_script(self.HEADER_TEXT)
        self.assertEqual(data["mode"], "header")
        self.assertEqual(len(data["segments"]), 2)
        self.assertEqual(data["segments"][0]["seconds"], 5.0)
        self.assertEqual(data["segments"][1]["seconds"], 3.0)
        self.assertEqual(data["segments"][0]["dialogue"][0]["character"], "女主")
        self.assertAlmostEqual(data["total_seconds"], 8.0)

    def test_shot_headers(self):
        data = script.parse_script("镜头1（5秒）\nA\n镜头2（5秒）\nB")
        self.assertEqual(len(data["segments"]), 2)
        self.assertEqual(data["segments"][0]["text"], "A")

    def test_blank_mode(self):
        data = script.parse_script("第一幕：开场\n\n第二幕：冲突", mode="blank")
        self.assertEqual(len(data["segments"]), 2)
        self.assertEqual(data["segments"][0]["seconds"], 5.0)

    def test_divider_mode(self):
        data = script.parse_script("A 段\n---\nB 段", mode="divider")
        self.assertEqual(len(data["segments"]), 2)
        self.assertEqual(data["segments"][1]["text"], "B 段")

    def test_line_mode(self):
        data = script.parse_script("A\nB\nC", mode="line")
        self.assertEqual([s["text"] for s in data["segments"]], ["A", "B", "C"])

    def test_regex_mode_requires_pattern(self):
        with self.assertRaises(DirectorError):
            script.parse_script("A X B", mode="regex")

    def test_auto_divider(self):
        data = script.parse_script("场景 A\n---\n场景 B")
        self.assertEqual(data["mode"], "divider")

    def test_refs_collected(self):
        data = script.parse_script("第1段（5秒）\n@图片1 的女孩和 @图片3", mode="header")
        self.assertEqual(data["segments"][0]["refs"], [1, 3])

    def test_keep_header(self):
        data = script.parse_script("第1段（5秒）\n内容", keep_header=True)
        self.assertIn("第1段", data["segments"][0]["text"])

    def test_empty_script(self):
        data = script.parse_script("   ")
        self.assertEqual(data["segments"], [])
        self.assertTrue(data["warnings"])

    def test_max_segments(self):
        text = "\n".join(f"第{i}段（5秒）\n内容{i}" for i in range(1, 8))
        data = script.parse_script(text, max_segments=3)
        self.assertEqual(len(data["segments"]), 3)
        self.assertTrue(data["warnings"])


if __name__ == "__main__":
    unittest.main()
