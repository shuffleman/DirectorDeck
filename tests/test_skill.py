"""Skill 加载器单测（临时目录，不依赖仓库里的具体 skill）。"""

from __future__ import annotations

import os
import tempfile
import unittest

from director_deck.adapters import skill


class SkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "writer"))
        with open(os.path.join(self.root, "writer", "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nname: 编剧\n---\n\n# 规则\n写短剧。\n")
        os.makedirs(os.path.join(self.root, "writer", "references"))
        with open(os.path.join(self.root, "writer", "references", "a.md"), "w", encoding="utf-8") as fh:
            fh.write("# 参考 A\n补充资料\n")
        with open(os.path.join(self.root, "single.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nname: 单文件\n---\n单文件提示词\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_nested_suite_discovery(self):
        os.makedirs(os.path.join(self.root, "suite", "engine_a"))
        with open(os.path.join(self.root, "suite", "engine_a", "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("# 子技能 A\n")
        ids = [item["id"] for item in skill.discover(self.root)]
        self.assertIn("suite/engine_a", ids)

    def test_load_nested_suite(self):
        os.makedirs(os.path.join(self.root, "suite", "engine_a"))
        with open(os.path.join(self.root, "suite", "engine_a", "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("# 子技能 A\n内容\n")
        data = skill.load("suite/engine_a", root=self.root)
        self.assertIn("子技能 A", data["text"])

    def test_discover_and_choices(self):
        entries = skill.discover(self.root)
        ids = [item["id"] for item in entries]
        self.assertIn("writer", ids)
        self.assertIn("single", ids)
        favorites = skill.choices(self.root)
        self.assertEqual(favorites, ids)

    def test_load_strips_frontmatter(self):
        data = skill.load("writer", root=self.root)
        self.assertNotIn("name: 编剧", data["text"])
        self.assertIn("写短剧", data["text"])
        self.assertEqual(data["files"], ["SKILL.md"])

    def test_load_with_refs(self):
        data = skill.load("writer", include_refs=True, root=self.root)
        self.assertIn("参考资料：a.md", data["text"])
        self.assertIn("references/a.md", data["files"])

    def test_load_truncates(self):
        data = skill.load("writer", include_refs=True, max_chars=20, root=self.root)
        self.assertTrue(data["truncated"])
        self.assertIn("已截断", data["text"])

    def test_load_single_file(self):
        data = skill.load("single", root=self.root)
        self.assertIn("单文件提示词", data["text"])

    def test_override_path(self):
        path = os.path.join(self.root, "single.md")
        data = skill.load("writer", override_path=path, root=self.root)
        self.assertIn("单文件提示词", data["text"])

    def test_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            skill.load("nope", root=self.root)


if __name__ == "__main__":
    unittest.main()
