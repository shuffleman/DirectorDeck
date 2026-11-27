#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把两个外部 skill 源预置/同步到 DirectorDeck 的 skills/ 目录。

1) 漫剧老李 AIGC 全流程 Skill（MIT）
   https://github.com/lixiaoxiao9888-create/manju-laoli-skill
   -> skills/manju_laoli/<子技能>/SKILL.md + references/

2) MiniMax H3 分段无限视频生成提示词模板 V6（用户提供）
   -> skills/minimax_h3_v6/SKILL.md

用法（维护者本地有源目录时）：
    python tools/preset_bundled_skills.py \
        --manju-repo F:\\Comfy-Desktop\\_skill_repo \
        --v6-file "F:\\AI-Video\\Test\\MiniMax H3 分段无限视频生成提示词模板 V6.md"

仓库里已经预置了一份拷贝；这个脚本用于以后重新同步上游。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(REPO, "skills")


def sync_manju(src_repo: str) -> list[str]:
    manju = os.path.join(SKILLS, "manju_laoli")
    if os.path.isdir(manju):
        shutil.rmtree(manju)
    os.makedirs(manju)
    engines = [name for name in sorted(os.listdir(src_repo))
               if os.path.isdir(os.path.join(src_repo, name))
               and os.path.isfile(os.path.join(src_repo, name, "SKILL.md"))]
    for engine in engines:
        src = os.path.join(src_repo, engine)
        dst = os.path.join(manju, engine)
        os.makedirs(dst)
        shutil.copyfile(os.path.join(src, "SKILL.md"), os.path.join(dst, "SKILL.md"))
        refs = os.path.join(src, "references")
        if os.path.isdir(refs):
            shutil.copytree(refs, os.path.join(dst, "references"))
    for name in ("LICENSE", "README.md"):
        path = os.path.join(src_repo, name)
        if os.path.isfile(path):
            shutil.copyfile(path, os.path.join(manju, name))
    commit = subprocess.run(["git", "-C", src_repo, "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    notice = f"""# 漫剧老李 AIGC 全流程 Skill（预置副本）

- 来源：https://github.com/lixiaoxiao9888-create/manju-laoli-skill
- 版本：V8.2.0-SLIM（README 标注）
- 提交：`{commit}`
- 许可：MIT（见本目录 LICENSE）
- 预置内容：{len(engines)} 个 skill 的 `SKILL.md` + `references/`
  （未包含 scripts/assets/CI；编剧台只读 Markdown 规则，不需要脚本）。

## 子技能列表

""" + "\n".join(f"- `manju_laoli/{engine}`" for engine in engines) + """

## 用法

在「编剧台」的 skill 下拉框选择 `manju_laoli/<子技能>`：
- 只要创作规则：`include_refs=False`（默认）；
- 需要扩展资料：打开 `include_refs`，并用 `max_context_chars` 控制上下文大小
  （主控 SKILL.md 本身约 7.6 万字符，建议 6 万~12 万，超长会截断）。
"""
    with open(os.path.join(manju, "NOTICE.md"), "w", encoding="utf-8") as handle:
        handle.write(notice)
    return engines


def sync_v6(v6_file: str) -> None:
    target = os.path.join(SKILLS, "minimax_h3_v6")
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)
    shutil.copyfile(v6_file, os.path.join(target, "SKILL.md"))
    notice = """# MiniMax H3 分段无限视频生成提示词模板 V6（预置副本）

- 来源：用户提供的本地文件 `MiniMax H3 分段无限视频生成提示词模板 V6.md`
- 许可：未标明，按“用户自有资料”随仓库预置，仅用于编剧台的规则加载
- 适用：H3 分段提示词（`【第N段｜X秒】` + `<d>` 对白标签）

## 用法

在「编剧台」：
1. `skill` 选 `minimax_h3_v6`；
2. `output_format` 选 **H3 V6 分段提示词**；
3. 可选 `include_refs=False`（单文件无 references）。

节点会把 V6 文本自动转换成 DirectorDeck 剧本 / TTS 台词表，方便直接接视频生成器。
"""
    with open(os.path.join(target, "NOTICE.md"), "w", encoding="utf-8") as handle:
        handle.write(notice)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manju-repo", default=r"F:\Comfy-Desktop\_skill_repo")
    parser.add_argument("--v6-file", default=os.path.join(
        r"F:\AI-Video\Test", "MiniMax H3 分段无限视频生成提示词模板 V6.md"))
    args = parser.parse_args()
    os.makedirs(SKILLS, exist_ok=True)
    if os.path.isdir(args.manju_repo):
        engines = sync_manju(args.manju_repo)
        print(f"[+] 已同步 manju_laoli：{len(engines)} 个子技能")
    else:
        print(f"[!] 跳过 manju 源目录（不存在）：{args.manju_repo}")
    if os.path.isfile(args.v6_file):
        sync_v6(args.v6_file)
        print("[+] 已同步 minimax_h3_v6")
    else:
        print(f"[!] 跳过 V6 文件（不存在）：{args.v6_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
