"""素材槽位与引用解析（纯函数，能在 ComfyUI 外单测）。

为什么素材要“固定 9 个槽”？
因为提示词里写的是 `@图片3`，它就代表第 3 槽——槽位必须稳定，
这样“段 2 只换第 5 张图、其他沿用段 1”才能按槽号精准覆盖（merge）。

几个概念：
- slots：9 个槽的元数据（有没有图、名字、用途、是否启用）；
- images：9 个 IMAGE 张量（运行期数据，不参与哈希/落盘）；
- audios / videos：额外的音视频素材（M3 锁音会用到）；
- `@图片N` 在送进模型前会转成 H3 认识的 `<Picture N>`。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Mapping

from .types import ASSET_SLOT_COUNT, SCHEMA_VERSION, error

# 两类写法都要认：提示词里写 @图片1（我们自己的语法），或者直接写 <Picture 1>（H3 原生）。
_IMG_REF = re.compile(r"@图片\s*(\d{1,2})")
_AUD_REF = re.compile(r"@音频\s*(\d{1,2})")
_VID_REF = re.compile(r"@视频\s*(\d{1,2})")


def empty_slot(slot: int) -> dict:
    """生成一个空槽。空槽不是错误，只是“这个位置暂时没图”。"""
    return {"slot": int(slot), "path": None, "name": "", "role": "", "enabled": True}


def empty_assets() -> dict:
    """一份干净的空素材包（9 个空槽，没有任何音视频）。"""
    return {
        "schema": f"DIRECTOR_ASSETS@{SCHEMA_VERSION}",
        "slots": [empty_slot(i + 1) for i in range(ASSET_SLOT_COUNT)],
        # images 里放运行期的 IMAGE 张量；落盘/算哈希时会主动剔除。
        "images": [None] * ASSET_SLOT_COUNT,
        "audios": [],
        "videos": [],
    }


def normalize_assets(data: Mapping[str, Any] | None) -> dict:
    """把任何形状的素材数据“扶正”成标准 9 槽结构。

    为什么要 normalize：
    - 工作流里存的可能是旧版本结构、或者只填了第 3 槽；
    - merge / 哈希 / UI 都要求 slots 永远是 1..9 的顺序，不能缺不能乱。
    """
    base = empty_assets()
    if not data:
        return base

    # 先把传进来的槽按 slot 号对号入座；没给的槽后面补空槽。
    slots = {int(s.get("slot", 0)): s for s in (data.get("slots") or []) if s}
    out_slots = []
    for i in range(ASSET_SLOT_COUNT):
        item = dict(slots.get(i + 1) or empty_slot(i + 1))
        item["slot"] = i + 1
        item.setdefault("path", None)
        # 没给名字就用人话兜底：path 的文件名，或者干脆空字符串。
        item.setdefault("name", os.path.basename(item["path"] or "") if item.get("path") else "")
        item.setdefault("role", "")
        item.setdefault("enabled", True)
        out_slots.append(item)

    base["slots"] = out_slots

    # 张量：补齐到 9 个位置，多出来的直接砍掉（超过 9 张本来就不合法）。
    images = list(data.get("images") or [])
    base["images"] = (images + [None] * ASSET_SLOT_COUNT)[:ASSET_SLOT_COUNT]
    base["audios"] = list(data.get("audios") or [])
    base["videos"] = list(data.get("videos") or [])
    return base


def slot_path(assets: Mapping[str, Any], number: int) -> str | None:
    """取第 N 槽的文件路径；槽不存在/被禁用就返回 None。"""
    if not 1 <= int(number) <= ASSET_SLOT_COUNT:
        return None
    for item in assets.get("slots") or []:
        if int(item.get("slot", 0)) == int(number) and item.get("enabled", True):
            return item.get("path") or None
    return None


def merge_assets(base: Mapping[str, Any] | None, override: Mapping[str, Any] | None) -> dict:
    """按槽位合并：override 里哪一槽有图，就用它替换 base 的同号槽；其余保持 base。

    这就是“段 2 只换第 2 张参考图、第 1 张继续用段 1”的实现方式。
    注意：override 的空槽不会清空 base（要清空请用 policy=clear / replace）。
    """
    base_n = normalize_assets(base)
    over_n = normalize_assets(override)
    out = normalize_assets(base_n)
    for i in range(ASSET_SLOT_COUNT):
        over = over_n["slots"][i]
        if over.get("path"):
            out["slots"][i] = dict(over)
            out["slots"][i]["slot"] = i + 1
            out["images"][i] = over_n["images"][i]
    # 音视频目前是整包覆盖（数量少，按槽合并没有意义）。
    if over_n.get("audios"):
        out["audios"] = list(over_n["audios"])
    if over_n.get("videos"):
        out["videos"] = list(over_n["videos"])
    return out


def image_tensors(assets: Mapping[str, Any]) -> list:
    """按槽号顺序取出非空的 IMAGE 张量，给 H3 的参考条件用。"""
    tensors = list((assets or {}).get("images") or [])
    out = []
    for i in range(ASSET_SLOT_COUNT):
        if i < len(tensors) and tensors[i] is not None and assets["slots"][i].get("enabled", True):
            out.append(tensors[i])
    return out


def refs_in_text(text: str) -> dict:
    """扫出提示词里所有的 @图片N / @音频N / @视频N 引用。

    返回 {"images": [...], "audios": [...], "videos": [...]}，数字就是槽号。
    """
    return {
        "images": [int(n) for n in _IMG_REF.findall(text or "")],
        "audios": [int(n) for n in _AUD_REF.findall(text or "")],
        "videos": [int(n) for n in _VID_REF.findall(text or "")],
    }


def validate_refs(text: str, assets: Mapping[str, Any]) -> list[str]:
    """校验提示词里的引用是否有效。

    两种情况会让用户当场翻车，所以必须提前报清楚：
    - @图片10：越界（只有 9 槽）→ DD-E010；
    - @图片2 但第 2 槽是空的 → DD-E011。
    返回值目前恒为空列表，留给以后放“警告级”问题（比如图片尺寸不对）。
    """
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
    """哪些槽是“有图”的，按槽号升序返回。调试/预览用。"""
    return [i + 1 for i in range(ASSET_SLOT_COUNT) if slot_path(assets, i + 1)]


def bind_prompt(text: str, assets: Mapping[str, Any]) -> str:
    """把提示词里的 @图片N 换成 H3 原生的 <Picture N>（音频/视频同理）。

    换之前会先 validate_refs，避免把“空槽引用”带进模型里变成玄学报错。
    """
    validate_refs(text, assets)

    def _img(match: re.Match) -> str:
        return f"<Picture {int(match.group(1))}>"

    out = _IMG_REF.sub(_img, text or "")
    out = _AUD_REF.sub(lambda m: f"<Audio {int(m.group(1))}>", out)
    out = _VID_REF.sub(lambda m: f"<Video {int(m.group(1))}>", out)
    return out


def assets_hash(assets: Mapping[str, Any]) -> str:
    """素材包指纹：只算元数据，不算图片张量（张量没法稳定哈希，也太大）。"""
    meta = {k: v for k, v in normalize_assets(assets).items() if k != "images"}
    canonical = json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha1:" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()
