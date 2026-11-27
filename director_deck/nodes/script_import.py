"""DirectorDeck · 剧本导入 / 素材自动匹配。

剧本由外部（任意工具/模型）生成，这里只负责“导入 + 对齐 + 喂给生成器”：

1. **导入**：支持三种文本
   - DirectorDeck 剧本（`第N段（X秒）` + `角色：台词` + `@图片N`）；
   - JSON 剧本（character/segments 结构，见 docs/CONTRACTS.md）；
   - H3 V6 分段提示词（`【第N段｜X秒】` + `<d>` 台词）。
2. **匹配素材**：
   - 角色 → 素材库图片槽（按槽名/用途相似度，匹配不上按顺序兜底）；
   - 场景 → 段落里的场景/画面关键词匹配背景槽；
   - 音频 → 角色名匹配角色/音色库，拿音频槽号（没接角色库就给顺序建议）；
   - 匹配结果写回每段的 `@图片N`，并输出对照表。
3. **输出**：`script` 直接接视频生成器（或前端“一键建生成器”按钮），
   `segment_count` 用来告诉前端要建几段。
"""

from __future__ import annotations

import hashlib
import json
import re

from ..core import asset_match as match_lib
from ..core import assets as assets_lib
from ..core import screenplay as screenplay_lib
from ..core import script as script_lib
from ..core.types import (CATEGORY, MAX_SEGMENTS, TYPE_ASSETS, TYPE_CAST, TYPE_SCRIPT, error)

FORMAT_LABELS = ("自动识别", "DirectorDeck 剧本", "JSON 剧本", "H3 V6 文本")
_V6_HEADER = re.compile(r"【\s*第\s*\d+\s*段")

DEFAULT_SCRIPT = """第1段（5秒）
[画面] 雨夜，女主撑着伞站在老宅台阶下，男主从门内走出，雨水打在青石板上。
女主：你终于回来了。
男主：这十年，我一直在找你。

第2段（5秒）
[画面] 两人在雨中对视，镜头缓慢推近女主的脸。
女主：先进屋吧。"""


class DirectorDeckScriptImport:
    """外部剧本导入 + 角色/场景/音频素材自动匹配。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "import_script"
    RETURN_TYPES = (TYPE_SCRIPT, "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("script", "script_text", "mapping", "summary", "segment_count")
    DESCRIPTION = (
        "导入外部剧本（DirectorDeck 文本 / JSON / H3 V6），按素材库和角色音色库"
        "自动匹配角色、场景、音频，输出可直接接视频生成器的剧本和匹配对照表。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "script": ("STRING", {"multiline": True, "default": DEFAULT_SCRIPT,
                                      "tooltip": "粘贴外部生成好的剧本：DirectorDeck 文本 / JSON / H3 V6"}),
                "format": (list(FORMAT_LABELS), {"default": FORMAT_LABELS[0],
                                                 "tooltip": "自动识别会看 JSON / V6 段头 / DirectorDeck 段头"}),
                "segment_seconds": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 20.0, "step": 0.5,
                                              "tooltip": "文本没写秒数时的默认段长"}),
                "match_assets": ("BOOLEAN", {"default": True,
                                             "tooltip": "按素材库自动匹配角色/场景图片槽"}),
                "match_scenes": ("BOOLEAN", {"default": True,
                                             "tooltip": "按段落关键词匹配背景/场景图槽"}),
                "min_score": ("FLOAT", {"default": match_lib.MIN_SCORE,
                                        "min": 0.3, "max": 1.0, "step": 0.05,
                                        "tooltip": "名字/关键词相似度门槛，低于它就走顺序兜底"}),
            },
            "optional": {
                "assets": (TYPE_ASSETS, {"tooltip": "素材库（9 图槽）：用于自动匹配图片"}),
                "cast": (TYPE_CAST, {"tooltip": "角色/音色库：用于匹配角色名和音频槽"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        key = {k: kwargs.get(k) for k in (
            "script", "format", "segment_seconds", "match_assets",
            "match_scenes", "min_score")}
        key["assets"] = id(kwargs.get("assets"))
        key["cast"] = id(kwargs.get("cast"))
        return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    @staticmethod
    def _asset_slots(assets: dict | None) -> list[dict]:
        """把 AssetShelf 的素材包变成“槽位 + 是否已填 + 名字/用途”。"""
        if not assets:
            return []
        data = assets_lib.normalize_assets(assets)
        images = data.get("images") or []
        slots = []
        for index, slot in enumerate(data.get("slots") or [], start=1):
            filled = index <= len(images) and images[index - 1] is not None
            slots.append({"slot": index,
                          "name": slot.get("name") or f"图片{index}",
                          "role": slot.get("role") or "",
                          "filled": filled})
        return slots

    def _parse(self, text: str, fmt: str, default_seconds: float) -> tuple[dict, str]:
        """按格式解析成 screenplay；返回 (screenplay, 实际使用的格式名)。"""
        raw = (text or "").strip()
        if not raw:
            raise ValueError("剧本内容为空：请先粘贴外部生成的剧本")
        if fmt == FORMAT_LABELS[0]:
            if raw.startswith("{") or '"segments"' in raw:
                fmt = FORMAT_LABELS[2]
            elif _V6_HEADER.search(raw):
                fmt = FORMAT_LABELS[3]
            else:
                fmt = FORMAT_LABELS[1]
        if fmt == FORMAT_LABELS[2]:
            data = screenplay_lib.extract_json(raw)
            if data is None:
                raise error("DD-E061", "看起来是 JSON 剧本，但没有解析出合法 JSON")
            plan = screenplay_lib.normalize_screenplay(
                data, default_seconds=default_seconds,
                max_segments=MAX_SEGMENTS, language="")
            return plan, fmt
        if fmt == FORMAT_LABELS[3]:
            try:
                return screenplay_lib.v6_to_screenplay(raw), fmt
            except ValueError as exc:
                raise error("DD-E061", f"V6 文本解析失败：{exc}") from exc
        parsed = script_lib.parse_script(raw, mode="auto",
                                         default_seconds=float(default_seconds))
        if not parsed.get("segments"):
            raise error("DD-E061", "没有解析出任何段落，请检查段头/格式")
        return screenplay_lib.screenplay_from_parsed_script(
            parsed, default_seconds=float(default_seconds)), FORMAT_LABELS[1]

    def import_script(self, script, format, segment_seconds, match_assets,
                      match_scenes, min_score, assets=None, cast=None):
        plan, detected = self._parse(script, format, float(segment_seconds))
        slots = self._asset_slots(assets)
        cast_roles = list((cast or {}).get("roles") or [])
        warnings = list(plan.get("warnings") or [])

        if match_assets:
            match = match_lib.match_assets(
                plan, slots, cast_roles,
                match_scenes_enabled=bool(match_scenes),
                min_score=float(min_score))
            matched_plan, apply_warnings = match_lib.apply_matches(
                plan, match["characters"], match["scenes"])
            warnings.extend(match.get("warnings") or [])
            warnings.extend(apply_warnings)
            mapping = match_lib.mapping_report(
                match["characters"], match["scenes"], slots)
        else:
            match = {"characters": {}, "scenes": {}}
            matched_plan = plan
            mapping = "（已关闭素材匹配：保留剧本里原有的 @图片N 引用）"

        script_text = screenplay_lib.screenplay_to_script_text(matched_plan)
        parsed = script_lib.parse_script(script_text, mode="header",
                                         default_seconds=float(segment_seconds))
        segment_count = len(parsed.get("segments") or [])
        matched_chars = sum(1 for item in match["characters"].values()
                            if item.get("image_slot"))
        matched_audio = sum(1 for item in match["characters"].values()
                            if item.get("audio_slot"))
        summary = (
            f"格式={detected}；角色 {len(plan.get('characters') or [])} 个；"
            f"段数 {segment_count}；时长 {parsed.get('total_seconds', 0):.1f}s；"
            f"匹配图片角色 {matched_chars} 个、音频槽 {matched_audio} 个、"
            f"场景 {len(match['scenes'])} 段；"
            f"素材槽 {len([s for s in slots if s['filled']])}/9；"
            f"角色库 {len(cast_roles)} 个")
        if warnings:
            summary += "；提醒：" + " / ".join(warnings)
        print(f"[DirectorDeck] 剧本导入：{summary}")
        return (parsed, script_text, mapping, summary, int(segment_count))
