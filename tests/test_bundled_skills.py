"""预置 skill 的可用性检查（仓库里带了漫剧老李全集 + V6 模板）。"""

from __future__ import annotations

import unittest

from director_deck.adapters import skill
from director_deck.core import screenplay as sp
from director_deck.core import script as script_lib


class BundledSkillsTest(unittest.TestCase):
    def test_choices_include_bundled(self):
        ids = [item["id"] for item in skill.discover()]
        self.assertIn("manju_laoli/short-drama-director", ids)
        self.assertIn("manju_laoli/sd-script-engine", ids)
        self.assertIn("minimax_h3_v6", ids)
        self.assertIn("directordeck_screenwriter", ids)

    def test_load_v6_template(self):
        data = skill.load("minimax_h3_v6")
        self.assertIn("MiniMax H3", data["text"])
        self.assertIn("【第N段｜X秒】", data["text"])
        # V6 模板自带示例段头，转回剧本结构应能解析
        plan = sp.v6_to_screenplay(data["text"])
        self.assertGreaterEqual(len(plan["segments"]), 1)
        text = sp.screenplay_to_script_text(plan)
        parsed = script_lib.parse_script(text, mode="header")
        self.assertGreaterEqual(len(parsed["segments"]), 1)

    def test_load_manju_director(self):
        data = skill.load("manju_laoli/short-drama-director", max_chars=60000)
        self.assertGreater(len(data["text"]), 5000)
        self.assertIn("短剧", data["text"])

    def test_load_manju_script_with_refs(self):
        data = skill.load("manju_laoli/sd-script-engine", include_refs=True,
                          max_chars=120000)
        self.assertIn("参考资料", data["text"])
        self.assertTrue(any("references/" in name for name in data["files"]))


if __name__ == "__main__":
    unittest.main()
