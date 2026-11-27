"""素材槽位与引用解析（契约 §2.4 / §6）。

- 固定 9 槽：slots[i]["slot"] == i+1，`@图片N` 直接对应第 N 槽；
- merge 按槽位覆盖；空槽合法；
- 引用校验：越界 DD-E010，空槽/文件缺失 DD-E011。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Iterable, Mapping

from .types import ASSET_SLOT_COUNT, SCHEMA_VERSION, error

_IMG_REF = re.compile(r"@图片\s*(\d{1,2})")
_AUD_REF = re.compile(r"@音频\s*(\d{1,2})")
_VID_REF = re.compile(r"@视频\s*(\d{1,2})")
_IMG_TAG = re.compile(r"<Picture\s*(\d{1,2})>")
_AUD_TAG = re.compile(r"<Audio\s*(\d{1,2})>")
_VID_TAG = re.compile(r"<Video\s*(\d{1,2})>")


def empty_slot(slot: int) -> dict:
    return {"slot": int(slot), "path": None, "name": "", "role": "", "enabled": True}


def empty_assets() -> dict:
    return {
        "schema": f"DIRECTOR_ASSETS@{SCHEMA_VERSION}",
        "slots": [empty_slot(i + 1) for i in range(ASSET_SLOT_COUNT)],
        "audios": [],
        "videos": [],
    }


def normalize_assets(data: Mapping[str, Any] | None) -> dict:
    """补齐 schema/槽位，保证 slots 恒为 1..9 且顺序稳定。"""
    base = empty_assets()
    if not data:
        return base
    slots = {int(s.get("slot", 0)): s for s in (data.get("slots") or []) if s}
    out_slots = []
    for i in range(ASSET_SLOT_COUNT):
        item = dict(slots.get(i + 1) or empty_slot(i + 1))
        item["slot"] = i + 1
        item.setdefault("path", None)
        item.setdefault("name", os.path.basename(item["path"] or "") if item.get("path") else "")
        item.setdefault("role", "")
        item.setdefault("enabled", True)
        out_slots.append(item)
    base["slots"] = out_slots
    base["audios"] = list(data.get("audios") or [])
    base["videos"] = list(data.get("videos") or [])
    return base


def slot_path(assets: Mapping[str, Any], number: int) -> str | None:
    if not 1 <= int(number) <= ASSET_SLOT_COUNT:
        return None
    for item in assets.get("slots") or []:
        if int(item.get("slot", 0)) == int(number) and item.get("enabled", True):
            return item.get("path") or None
    return None


def merge_assets(base: Mapping[str, Any] | None, override: Mapping[str, Any] | None) -> dict:
    """按槽位覆盖：override 中非空槽替换 base 的对应槽，其余保持 base。"""
    base_n = normalize_assets(base)
    over_n = normalize_assets(override)
    out = normalize_assets(base_n)
    for i in range(ASSET_SLOT_COUNT):
        over = over_n["slots"][i]
        if over.get("path"):
            out["slots"][i] = dict(over)
            out["slots"][i]["slot"] = i + 1
    if over_n.get("audios"):
        out["audios"] = list(over_n["audios"])
    if over_n.get("videos"):
        out["videos"] = list(over_n["videos"])
    return out


def refs_in_text(text: str) -> dict:
    return {
        "images": [int(n) for n in _IMG_REF.findall(text or "")],
        "audios": [int(n) for n in _AUD_REF.findall(text or "")],
        "videos": [int(n) for n in _VID_REF.findall(text or "")],
    }


def validate_refs(text: str, assets: Mapping[str, Any]) -> list[str]:
    """返回警告列表；越界/空槽抛出 DirectorError。"""
    refs = refs_in_text(text)
    warnings: list[str] = []
    for number in refs["images"]:
        if not 1 <= number <= ASSET_SLOT_COUNT:
            raise error("DD-E010", f"@图片{number} 越界（只允许 1-{ASSET_SLOT_COUNT}）")
        if not slot_path(assets, number):
            raise error("DD-E011", f"@图片{number} 引用的是空槽")
    for kind, key in (("音频", "audios"), ("视频", "videos")):
        for number in refs[key]:
            items = assets.get(key) or []
            if not 1 <= number <= len(items):
                raise error("DD-E010", f"@{kind}{number} 越界（当前只有 {len(items)} 个）")
    return warnings


def binds_assets(assets: Mapping[str, Any]) -> list[int]:
    """返回所有非空槽号（提示词绑定顺序）。"""
    return [i + 1 for i in range(ASSET_SLOT_COUNT) if slot_path(assets, i + 1)]


def bind_prompt(text: str, assets: Mapping[str, Any]) -> str:
    """把 @图片N 转成 H3 的 <Picture N>；空槽在 validate_refs 时已报错。"""
    validate_refs(text, assets)

    def _img(match: re.Match) -> str:
        return f"<Picture {int(match.group(1))}>"

    out = _IMG_REF.sub(_img, text or "")
    out = _AUD_REF.sub(lambda m: f"<Audio {int(m.group(1))}>", out)
    out = _VID_REF.sub(lambda m: f"<Video {int(m.group(1))}>", out)
    return out


def assets_hash(assets: Mapping[str, Any]) -> str:
    canonical = json.dumps(normalize_assets(assets), ensure_ascii=False,
                           sort_keys=True, separators=(",", ":"))
    return "sha1:" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()
