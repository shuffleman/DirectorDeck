#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把外部 skill 导入 DirectorDeck 的 skills/ 目录。

用法：
    python tools/import_skill.py <路径> [--name 名字]

支持两种来源：
- 目录：里面有 SKILL.md / PROMPT.md（整目录复制，references 一起带走）；
- 单个 .md 文件：复制成 skills/<名字>/SKILL.md（适合 V6 提示词模板这种单文件 skill）。

导入后重启 ComfyUI，节点面板的 skill 下拉框里就会出现。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(REPO, "skills")
ENTRY_FILES = ("SKILL.md", "PROMPT.md", "prompt.md", "skill.md")


def slugify(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value, flags=re.UNICODE)
    return value.strip("_").lower() or "skill"


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 skill 到 DirectorDeck/skills")
    parser.add_argument("source", help="skill 目录或单个 .md 文件")
    parser.add_argument("--name", default="", help="导入后的名字（默认取源目录/文件名）")
    args = parser.parse_args()

    source = os.path.abspath(os.path.expanduser(args.source))
    if not os.path.exists(source):
        print(f"[-] 路径不存在：{source}")
        return 2
    os.makedirs(SKILLS, exist_ok=True)

    if os.path.isdir(source):
        entry = next((os.path.join(source, name) for name in ENTRY_FILES
                      if os.path.isfile(os.path.join(source, name))), None)
        if not entry:
            print(f"[-] 目录里没有 {'/'.join(ENTRY_FILES)}：{source}")
            print("    如果是整包 skill 仓库，请指向具体的 skill 子目录，例如：")
            print("    python tools/import_skill.py <repo>/short-drama-director")
            return 2
        name = slugify(args.name or os.path.basename(source.rstrip("\\/")))
        target = os.path.join(SKILLS, name)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(source, target)
        print(f"[+] 已导入目录 skill：{target}")
        return 0

    if not source.lower().endswith((".md", ".txt")):
        print("[-] 只支持目录或 .md/.txt 文件")
        return 2
    name = slugify(args.name or os.path.splitext(os.path.basename(source))[0])
    target_dir = os.path.join(SKILLS, name)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "SKILL.md")
    shutil.copyfile(source, target)
    print(f"[+] 已导入单文件 skill：{target}")
    print("    重启 ComfyUI 后，在“编剧台”的 skill 下拉框里选择它。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
