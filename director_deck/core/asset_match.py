"""素材自动匹配（纯 Python，可单测）。

外部剧本导入后，需要把剧本里的“角色 / 场景 / 音色”对上素材库和角色音色库：

- 角色：按名字相似度匹配素材槽（槽名/用途），匹配不上按顺序兜底；
- 场景：按段落的场景/画面关键词匹配剩余素材槽；
- 音频：角色名匹配角色/音色库里的角色，拿到音频槽号；没有角色库就按顺序给建议槽号；
- 最后把匹配到的图片槽写回每段的 `image_refs`（去重、只保留 1..9）。

匹配结果全部可解释（带匹配理由），节点会输出一份对照表供用户复核。
"""

from __future__ import annotations

import copy
import difflib
import re

ASSET_SLOT_COUNT = 9
MIN_SCORE = 0.55
_PUNCT = re.compile(r"[\s\-_/\\|,，.。:：;；!！?？()（）【】\[\]\"'“”‘’]+")


def normalize_text(value: str) -> str:
    """统一名字：小写、去标点空格、去“角色/人物/场景”这类前后缀。"""
    text = _PUNCT.sub("", str(value or "").lower())
    for prefix in ("角色", "人物", "主角", "配角", "场景", "背景"):
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix):]
    return text


def similarity(a: str, b: str) -> float:
    """名字相似度：完全一致 1；包含关系 0.85；否则 difflib 比例。"""
    left, right = normalize_text(a), normalize_text(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return max(0.85, difflib.SequenceMatcher(None, left, right).ratio())
    return difflib.SequenceMatcher(None, left, right).ratio()


def available_slots(slots: list[dict] | None) -> list[dict]:
    """把素材槽整理成“已填、可用”的列表（只保留 1..9）。"""
    result = []
    for item in slots or []:
        try:
            slot = int(item.get("slot") or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= slot <= ASSET_SLOT_COUNT or not item.get("filled", True):
            continue
        result.append({"slot": slot,
                       "name": str(item.get("name") or f"图片{slot}"),
                       "role": str(item.get("role") or "")})
    return sorted(result, key=lambda item: item["slot"])


def _best_match(name: str, candidates: list[dict], used: set[int],
                min_score: float, allow_used: bool = False) -> tuple[dict | None, float, str]:
    best, best_score = None, 0.0
    for item in candidates:
        if not allow_used and item["slot"] in used:
            continue
        score = max(similarity(name, item["name"]), similarity(name, item["role"]))
        if score > best_score:
            best, best_score = item, score
    if best is not None and best_score >= min_score:
        return best, best_score, "名字/用途匹配"
    return None, best_score, "顺序兜底"


def match_characters(plan: dict, slots: list[dict], cast_roles: list[dict] | None = None,
                     min_score: float = MIN_SCORE) -> dict:
    """给每个角色分配图片槽 + 音频槽，返回 {char_id: {...}}。"""
    usable = available_slots(slots)
    used: set[int] = set()
    roles = list(cast_roles or [])
    result: dict[str, dict] = {}
    for index, char in enumerate(plan.get("characters") or []):
        image_slot, image_reason = None, "素材库为空"
        if usable:
            best, score, reason = _best_match(char.get("name") or "", usable, used, min_score)
            if best is None:
                # 顺序兜底：拿一个还没被占用的槽
                for item in usable:
                    if item["slot"] not in used:
                        best, score, reason = item, 0.0, "顺序兜底"
                        break
            if best is not None:
                image_slot = best["slot"]
                used.add(image_slot)
                image_reason = f"{reason}（{score:.2f}）" if score else reason
        audio_slot, audio_reason = None, "未连接角色/音色库"
        matched_role = None
        if roles:
            best_role, best_score = None, 0.0
            for role in roles:
                score = similarity(char.get("name") or "", role.get("name") or role.get("id") or "")
                if score > best_score:
                    best_role, best_score = role, score
            if best_role is not None and best_score >= min_score:
                matched_role = best_role
                slot = (matched_role.get("voice") or {}).get("slot")
                audio_slot = int(slot) if slot else None
                audio_reason = f"角色库匹配（{best_score:.2f}）"
            else:
                audio_reason = "角色库里没有同名角色"
        if audio_slot is None and not roles:
            audio_slot = index + 1
            audio_reason = f"未接角色库，按顺序建议音频槽{audio_slot}"
        result[str(char.get("id"))] = {"name": char.get("name") or "",
                                       "image_slot": image_slot,
                                       "image_reason": image_reason,
                                       "audio_slot": audio_slot,
                                       "audio_reason": audio_reason,
                                       "cast_role": matched_role.get("name") if matched_role else None}
    return result


def match_scenes(plan: dict, slots: list[dict], used_slots: set[int],
                 min_score: float = 0.62) -> dict:
    """按段落的场景/画面关键词匹配背景图槽，返回 {段号: {...}}。"""
    usable = available_slots(slots)
    if not usable:
        return {}
    result = {}
    for segment in plan.get("segments") or []:
        text = f"{segment.get('scene') or ''} {segment.get('actions') or ''}"
        best, best_score = None, 0.0
        for item in usable:
            # 场景优先用“没被角色占用”的槽；如果角色槽名字明显是同一个场景也可以借用
            if item["slot"] in used_slots and item["role"] not in ("scene", "background", "场景", "背景"):
                continue
            score = max(similarity(text, item["name"]), similarity(text, item["role"]))
            if score > best_score:
                best, best_score = item, score
        if best is not None and best_score >= min_score:
            result[int(segment.get("index", 0))] = {
                "slot": best["slot"], "score": round(best_score, 3),
                "name": best["name"]}
    return result


def apply_matches(plan: dict, char_map: dict, scene_map: dict) -> tuple[dict, list[str]]:
    """把匹配结果写回剧本：角色图片槽、段内角色/场景引用。"""
    warnings: list[str] = []
    result = copy.deepcopy(plan)
    by_id = {str(item.get("id")): item for item in result.get("characters") or []}
    for char_id, match in (char_map or {}).items():
        char = by_id.get(str(char_id))
        if not char:
            continue
        char["image_slot"] = match.get("image_slot")
        char["audio_slot"] = match.get("audio_slot")
    for segment in result.get("segments") or []:
        refs = {int(n) for n in segment.get("image_refs") or [] if 1 <= int(n) <= ASSET_SLOT_COUNT}
        names = " ".join([segment.get("scene") or "", segment.get("actions") or ""])
        for line in segment.get("dialogue") or []:
            names += " " + str(line.get("speaker") or "")
            char = by_id.get(str(line.get("speaker_id") or "")) or next(
                (c for c in result.get("characters") or [] if c.get("name") == line.get("speaker")), None)
            if char and char.get("image_slot"):
                refs.add(int(char["image_slot"]))
        for char_id, match in (char_map or {}).items():
            name = match.get("name") or ""
            if name and name in names and match.get("image_slot"):
                refs.add(int(match["image_slot"]))
        scene = (scene_map or {}).get(int(segment.get("index", 0)))
        if scene and scene.get("slot"):
            refs.add(int(scene["slot"]))
        segment["image_refs"] = sorted(refs)
        if len(refs) > 4:
            warnings.append(f"第{segment.get('index')}段匹配到 {len(refs)} 张图，可能过多")
    return result, warnings


def mapping_report(char_map: dict, scene_map: dict, slots: list[dict] | None = None) -> str:
    """生成给人看的对照表（节点输出）。"""
    lines = ["【角色 → 图片/音频】"]
    for char_id, match in (char_map or {}).items():
        image = f"@图片{match['image_slot']}" if match.get("image_slot") else "（未匹配到图片）"
        audio = f"音频槽{match['audio_slot']}" if match.get("audio_slot") else "（未匹配音频）"
        cast = f"，角色库={match['cast_role']}" if match.get("cast_role") else ""
        lines.append(
            f"{match.get('name') or char_id} | {image}（{match.get('image_reason')}） | "
            f"{audio}（{match.get('audio_reason')}）{cast}")
    if scene_map:
        lines.append("【段落 → 背景/场景图】")
        for index, match in sorted(scene_map.items()):
            lines.append(f"第{index}段 | @图片{match['slot']}（匹配分 {match.get('score')}）")
    if not char_map:
        lines.append("（没有角色可匹配）")
    return "\n".join(lines)


def match_assets(plan: dict, slots: list[dict] | None,
                 cast_roles: list[dict] | None = None,
                 match_scenes_enabled: bool = True,
                 min_score: float = MIN_SCORE) -> dict:
    """总入口：角色 + 场景匹配，返回 {characters, scenes, warnings}。"""
    char_map = match_characters(plan, slots or [], cast_roles, min_score)
    used = {match["image_slot"] for match in char_map.values() if match.get("image_slot")}
    scenes = match_scenes(plan, slots or [], used) if match_scenes_enabled else {}
    warnings = []
    if not available_slots(slots):
        warnings.append("没有已填素材槽，未做图片匹配")
    return {"characters": char_map, "scenes": scenes, "warnings": warnings}
