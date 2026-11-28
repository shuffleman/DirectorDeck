"""DirectorDeck 外部剧本 skill 的结构/共存/校验器单测（不依赖 ComfyUI）。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(REPO, "skills")
SKILL_DIR = os.path.join(SKILLS, "directordeck-screenplay-bridge")
SKILL_FILE = os.path.join(SKILL_DIR, "SKILL.md")
VALIDATOR = os.path.join(SKILL_DIR, "scripts", "validate_screenplay.py")


def read_frontmatter(path: str) -> dict:
    text = open(path, encoding="utf-8").read()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise AssertionError(f"{path} 缺 YAML frontmatter")
    data = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip().strip('"').strip("'")
        data[key.strip()] = value
    return data


def run_validator(text: str, fmt: str = "auto", suffix: str = ".txt") -> tuple[int, dict]:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "script" + suffix)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        proc = subprocess.run(
            [sys.executable, VALIDATOR, path, "--format", fmt, "--json"],
            capture_output=True, text=True, timeout=60,
            cwd=tmp, env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise AssertionError(f"校验器输出不是 JSON：{proc.stdout}\n{proc.stderr}")
        return proc.returncode, report


VALID_DD = """第1段（5秒）
[画面] 雨夜，女主撑着伞站在老宅台阶下，男主从门内走出 @图片1
女主：你终于回来了。
男主：这十年，我一直在找你。

第2段（5秒）
[画面] 两人在雨中对视，镜头缓慢推近女主的脸 @图片1
女主：先进屋吧。
"""

VALID_JSON = """{
  "title": "雨夜重逢",
  "characters": [
    {"id": "S1", "name": "女主", "image_slot": 1},
    {"id": "S2", "name": "男主", "image_slot": 2}
  ],
  "segments": [
    {"seconds": 5.0, "scene": "老宅台阶", "actions": "两人对视",
     "image_refs": [1, 2],
     "dialogue": [{"character": "女主", "text": "先进屋吧。"}]}
  ]
}"""

VALID_V6 = """【第1段｜5秒】
雨夜，女主撑着伞站在老宅台阶下，男主从门内走出。
(S1) 女主抬头 <d>[克制] 你终于回来了。</d>
(S2) 男主停在门口 <d>这十年，我一直在找你。</d>
<Picture 1> <Picture 2>

【第2段｜5秒】
两人在雨中对视，镜头缓慢推近。
(S1) <d>先进屋吧。</d>
<Picture 1>
"""


class SkillStructureTest(unittest.TestCase):
    def test_frontmatter_and_unique_name(self):
        meta = read_frontmatter(SKILL_FILE)
        self.assertEqual(meta.get("name"), "directordeck-screenplay-bridge")
        # Agent Skills 规范：小写字母/数字/连字符，避免和其他 skill 冲突。
        self.assertRegex(meta["name"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        self.assertLessEqual(len(meta["name"]), 64)
        self.assertTrue(meta.get("description", "").startswith("把任意来源的剧本草稿"))
        self.assertIn("DirectorDeck", meta["description"])
        self.assertIn("不接管", meta["description"])

        names = []
        if os.path.isdir(SKILLS):
            for name in os.listdir(SKILLS):
                path = os.path.join(SKILLS, name, "SKILL.md")
                if os.path.isfile(path):
                    names.append(read_frontmatter(path)["name"])
        self.assertEqual(names.count(meta["name"]), 1, f"skill 重名：{names}")

    def test_required_files_exist(self):
        for relative in (
            "SKILL.md",
            "references/directordeck-formats.md",
            "references/coexistence-rules.md",
            "references/handoff-schema.md",
            "scripts/validate_screenplay.py",
        ):
            self.assertTrue(os.path.isfile(os.path.join(SKILL_DIR, relative)), relative)

    def test_skill_declares_non_conflict_contract(self):
        text = open(SKILL_FILE, encoding="utf-8").read()
        for phrase in ("共存契约", "不接管世界观", "泛泛的", "不改写", "不要使用本 skill"):
            self.assertIn(phrase, text)
        # 不能自称通用编剧规则，避免和创作 skill 抢触发。
        self.assertNotIn("你是短剧/漫剧编剧", text)

    def test_no_duplicate_in_home_skill_dirs(self):
        meta = read_frontmatter(SKILL_FILE)
        candidates = [
            os.path.join(os.path.expanduser("~"), ".claude", "skills"),
            os.path.join(os.path.expanduser("~"), ".dsh", "skills"),
        ]
        for root in candidates:
            if not os.path.isdir(root):
                continue
            for name in os.listdir(root):
                path = os.path.join(root, name, "SKILL.md")
                if os.path.isfile(path):
                    try:
                        other = read_frontmatter(path).get("name")
                    except AssertionError:
                        continue
                    self.assertNotEqual(other, meta["name"],
                                        f"用户 skill 目录已有同名 skill：{path}")


class ValidatorTest(unittest.TestCase):
    def test_valid_dd(self):
        code, report = run_validator(VALID_DD)
        self.assertEqual(code, 0, report)
        self.assertTrue(report["ok"])
        self.assertEqual(report["segment_count"], 2)
        self.assertEqual(report["format"], "DirectorDeck 文本")

    def test_valid_json(self):
        code, report = run_validator(VALID_JSON, "json", ".json")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["format"], "JSON 剧本")

    def test_valid_v6(self):
        code, report = run_validator(VALID_V6, "v6")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["format"], "H3 V6 文本")

    def test_broken_dd_errors(self):
        broken = "第1段（5秒）\n[画面] 门 @图片10\n\n第3段（5秒）\n角色：台词。\n"
        code, report = run_validator(broken)
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertTrue(any("越界" in item for item in report["errors"]))
        self.assertTrue(any("不连续" in item for item in report["errors"]))

    def test_code_fence_is_error(self):
        code, report = run_validator("```text\n" + VALID_DD + "```")
        self.assertEqual(code, 1)
        self.assertTrue(any("代码围栏" in item for item in report["errors"]))

    def test_broken_json_is_error(self):
        code, report = run_validator('{"segments": [}', "json", ".json")
        self.assertEqual(code, 1)
        self.assertTrue(any("JSON 解析失败" in item for item in report["errors"]))

    def test_long_dialogue_is_warning_only(self):
        text = "第1段（5秒）\n[画面] 对话\n角色：这是一句明显超过五个字容量限制的台词。\n"
        code, report = run_validator(text)
        self.assertEqual(code, 0, report)
        self.assertTrue(report["warnings"])


if __name__ == "__main__":
    unittest.main()
