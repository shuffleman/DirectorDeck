"""Skill 规则库加载（纯标准库，可单测）。

Skill 就是一个“给编剧/导演看的规则包”，可以是：
- 一个目录：里面放 `SKILL.md`（或 `PROMPT.md`），`references/` 下放扩展资料；
- 一个单文件：`xxx.md` 提示词模板。

DirectorDeck 的约定：
- 仓库根目录的 `skills/` 是默认技能库；
- 用 `tools/import_skill.py` 把外部 skill（比如漫剧老李的 SKILL.md、V6 提示词模板）导进来；
- 节点面板里选 skill 名，节点会把 SKILL.md（可选 references）塞进 LLM 的 system prompt。
"""

from __future__ import annotations

import os
import re
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_ROOT = os.path.join(REPO_ROOT, "skills")
ENTRY_FILES = ("SKILL.md", "PROMPT.md", "prompt.md", "skill.md")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def skills_root(root: str | None = None) -> str:
    return os.path.abspath(root or SKILLS_ROOT)


def _meta(text: str) -> dict:
    """抠出 YAML frontmatter 里的 name/description（不引第三方 YAML）。"""
    match = _FRONTMATTER.match(text or "")
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta


def _entry_file(folder: str) -> str | None:
    for name in ENTRY_FILES:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def discover(root: str | None = None) -> list[dict]:
    """扫描 skills 目录，返回 [{id,label,path,kind}]（目录在前、文件在后）。"""
    base = skills_root(root)
    found: list[dict] = []
    if not os.path.isdir(base):
        return found
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if os.path.isdir(path):
            entry = _entry_file(path)
            if entry:
                text = _read(entry)
                meta = _meta(text)
                found.append({"id": name, "label": meta.get("name") or name,
                              "path": entry, "kind": "dir",
                              "description": meta.get("description", "")})
        elif name.lower().endswith(".md"):
            if name.lower() in ("readme.md", "license.md"):
                continue
            text = _read(path)
            meta = _meta(text)
            found.append({"id": os.path.splitext(name)[0],
                          "label": meta.get("name") or os.path.splitext(name)[0],
                          "path": path, "kind": "file",
                          "description": meta.get("description", "")})
    return found


def choices(root: str | None = None) -> list[str]:
    """给 ComfyUI combo 用的选项（id 列表，去重保序）。"""
    ids = [item["id"] for item in discover(root)]
    return ids or ["directordeck_screenwriter"]


def resolve(identifier: str | None, override_path: str = "",
            root: str | None = None) -> str:
    """把 combo 选项/路径解析成实际文件路径；找不到抛 FileNotFoundError。"""
    if (override_path or "").strip():
        path = os.path.expanduser(override_path.strip())
        if not os.path.isabs(path):
            path = os.path.join(REPO_ROOT, path)
        if os.path.isdir(path):
            entry = _entry_file(path)
            if not entry:
                raise FileNotFoundError(f"目录里没有 SKILL.md/PROMPT.md：{path}")
            return entry
        if not os.path.isfile(path):
            raise FileNotFoundError(f"skill 文件不存在：{path}")
        return path
    for item in discover(root):
        if item["id"] == identifier:
            return item["path"]
    # 允许直接写 “目录名” 而 combo 里没有的情况，再兜底扫一次
    base = skills_root(root)
    candidate = os.path.join(base, str(identifier or ""))
    entry = _entry_file(candidate) if os.path.isdir(candidate) else None
    if entry:
        return entry
    raise FileNotFoundError(f"没找到 skill：{identifier!r}（skills 目录：{base}）")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER.sub("", text, count=1).strip()


def load(identifier: str | None, override_path: str = "",
         include_refs: bool = False, max_chars: int = 60000,
         root: str | None = None) -> dict:
    """加载 skill 正文，可选带上 references 扩展资料；超长自动截断并标记。"""
    path = resolve(identifier, override_path, root)
    text = _strip_frontmatter(_read(path))
    files = [os.path.basename(path)]
    folder = os.path.dirname(path)
    ref_dir = os.path.join(folder, "references")
    if include_refs and os.path.isdir(ref_dir):
        refs = sorted(name for name in os.listdir(ref_dir)
                      if name.lower().endswith(".md"))
        for name in refs:
            ref_path = os.path.join(ref_dir, name)
            chunk = f"\n\n## 参考资料：{name}\n\n" + _strip_frontmatter(_read(ref_path))
            if len(text) + len(chunk) > int(max_chars):
                text += "\n\n（后面的参考资料因上下文长度限制已省略）"
                break
            text += chunk
            files.append(f"references/{name}")
    truncated = False
    if len(text) > int(max_chars):
        text = text[: int(max_chars)] + "\n\n（skill 内容因上下文长度限制已截断）"
        truncated = True
    return {"id": os.path.basename(folder) if os.path.isfile(path) else path,
            "path": path, "text": text, "files": files, "truncated": truncated}
