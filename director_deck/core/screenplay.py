"""剧本数据整理（纯 Python，方便单测）。

这层不关心“模型怎么调用”，只负责把 LLM 返回的剧本（JSON 或 H3 V6 文本）
整理成 DirectorDeck 能直接吃的东西：

- `normalize_screenplay`：把 JSON 剧本校验/补默认值/截断；
- `screenplay_to_script_text`：转成剧本加载器认的“第N段（X秒）”格式；
- `screenplay_to_voice_lines`：转成 TTS 台词表节点认的“角色 @秒 | 音色 | 台词”；
- `screenplay_to_character_map`：角色 -> 图片槽/音频槽/音色 对照表；
- `v6_to_screenplay`：把 `【第N段｜X秒】` + `<d>` 标签的 V6 文本转回上述结构。

所有函数只依赖标准库，测试不用装 ComfyUI/torch。
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_SECONDS = 60.0
MIN_SECONDS = 1.0
DEFAULT_LINE_AT = 0.6  # 没给 at 时，第一句默认从段内 0.6s 开始

_V6_HEADER = re.compile(r"【\s*第\s*(\d+)\s*段\s*[｜|]\s*([0-9]+(?:\.[0-9]+)?)\s*秒\s*】")
_V6_DIALOGUE = re.compile(
    r"\((?P<sid>S\d+)\)[^<\n]*?<d>\s*(?:\[[^\]]+\])?\s*(?P<text>[^<]+?)\s*</d>")
_V6_PICTURE = re.compile(r"<Picture\s*(\d+)>", re.IGNORECASE)
_AT_REF = re.compile(r"@图片\s*(\d{1,2})")


def strip_code_fence(text: str) -> str:
    """去掉 ```json ... ``` 这种代码围栏（模型很爱包一层）。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_+-]*\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return raw.strip()


def extract_json(text: str) -> dict | None:
    """从模型输出里尽量抠出第一个 JSON 对象；抠不出返回 None。"""
    raw = strip_code_fence(text)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            data, _end = decoder.raw_decode(raw[index:])
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp_seconds(value: float, default: float) -> float:
    seconds = _as_float(value, default)
    return max(MIN_SECONDS, min(MAX_SECONDS, seconds))


def _slot_numbers(value: Any) -> list[int]:
    """把 [1,2] / "1,2" / "@图片1 @图片2" 统一成去重升序槽号。"""
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [int(value)] if int(value) > 0 else []
    if isinstance(value, str):
        return sorted({int(n) for n in _AT_REF.findall(value)})
    numbers = set()
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            numbers.update(int(n) for n in _AT_REF.findall(str(item)))
        else:
            if number > 0:
                numbers.add(number)
    return sorted(numbers)


def normalize_screenplay(data: dict, *, default_seconds: float = 5.0,
                         max_segments: int = 64, language: str = "中文") -> dict:
    """校验并整理 LLM 生成的剧本 JSON（缺的补默认值，多的截断并记警告）。"""
    warnings: list[str] = []
    characters: list[dict] = []
    name_by_id: dict[str, str] = {}

    for index, item in enumerate(data.get("characters") or []):
        if not isinstance(item, dict):
            continue
        char_id = str(item.get("id") or item.get("character_id") or f"S{index + 1}").strip()
        name = str(item.get("name") or item.get("character") or char_id).strip()
        image_slot = int(_as_float(item.get("image_slot"), 0)) or None
        audio_slot = int(_as_float(item.get("audio_slot"), 0)) or None
        voice = str(item.get("voice") or item.get("voice_description") or "").strip()
        entry = {"id": char_id, "name": name, "image_slot": image_slot,
                 "audio_slot": audio_slot, "voice": voice}
        characters.append(entry)
        name_by_id[char_id] = name
        name_by_id.setdefault(name, name)

    segments: list[dict] = []
    title = str(data.get("title") or "").strip()
    raw_segments = data.get("segments") or data.get("shots") or []
    if len(raw_segments) > max_segments:
        warnings.append(f"剧本段数 {len(raw_segments)} 超过上限 {max_segments}，已截断")
    for index, item in enumerate(raw_segments[:max_segments]):
        if not isinstance(item, dict):
            continue
        seconds = _clamp_seconds(item.get("seconds"), default_seconds)
        scene = str(item.get("scene") or item.get("location") or "").strip()
        actions = str(item.get("actions") or item.get("description")
                      or item.get("action") or "").strip()
        refs = _slot_numbers(item.get("image_refs") or item.get("refs"))
        if not refs:
            refs = _slot_numbers(actions + " " + scene)
        dialogue = []
        for line in item.get("dialogue") or item.get("lines") or []:
            if not isinstance(line, dict):
                continue
            speaker_raw = str(line.get("speaker") or line.get("character") or "").strip()
            speaker = name_by_id.get(speaker_raw, speaker_raw)
            text = str(line.get("text") or line.get("line") or "").strip()
            if not speaker or not text:
                continue
            at = line.get("at", line.get("start"))
            dialogue.append({"speaker_id": speaker_raw, "speaker": speaker,
                             "text": text,
                             "at": None if at is None else max(0.0, _as_float(at, 0.0))})
        segments.append({"index": index + 1, "seconds": seconds, "scene": scene,
                         "actions": actions, "image_refs": refs,
                         "dialogue": dialogue})

    if not segments:
        raise ValueError("模型返回的剧本里没有 segments（至少 1 段）")
    return {"schema": "DIRECTOR_SCREENPLAY@1", "title": title,
            "language": language, "characters": characters,
            "segments": segments, "warnings": warnings}


def _action_line(segment: dict, images_mentioned: set[int]) -> str:
    """拼动作/画面行：去掉冒号（避免被剧本解析器当对白），补 @图片N 引用。"""
    parts = []
    if segment.get("scene"):
        parts.append(f"场景：{segment['scene']}".replace("：", "，"))
    if segment.get("actions"):
        parts.append(segment["actions"].replace("：", "，"))
    text = "；".join(part for part in parts if part).strip()
    refs = [n for n in segment.get("image_refs") or [] if n not in images_mentioned]
    if refs:
        text = (text + " " if text else "") + " ".join(f"@图片{n}" for n in refs)
    return f"[画面] {text}" if text else ""


def screenplay_to_script_text(screenplay: dict) -> str:
    """整理后的剧本 -> `第N段（X秒）` 文本（剧本加载器 header 模式直接吃）。"""
    blocks = []
    for segment in screenplay.get("segments") or []:
        lines = [f"第{int(segment['index'])}段（{segment['seconds']:g}秒）"]
        action = _action_line(segment, set())
        if action:
            lines.append(action)
        for line in segment.get("dialogue") or []:
            lines.append(f"{line['speaker']}：{line['text']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def screenplay_to_voice_lines(screenplay: dict) -> str:
    """整理后的剧本 -> TTS 台词表文本：`角色 @全局秒 | 音色描述 | 台词`。"""
    voice_by_name = {c["name"]: c.get("voice") or "" for c in screenplay.get("characters") or []}
    lines = []
    timeline = 0.0
    for segment in screenplay.get("segments") or []:
        seconds = float(segment["seconds"])
        for order, line in enumerate(segment.get("dialogue") or []):
            at = line.get("at")
            if at is None:
                at = DEFAULT_LINE_AT + order * 1.4
            at = max(0.0, min(seconds - 0.2, float(at)))
            start = timeline + at
            voice = voice_by_name.get(line["speaker"]) or "自然、清晰、适合剧集对白的说话声音。"
            safe_text = str(line["text"]).replace("|", "｜").replace("\n", " ")
            safe_voice = str(voice).replace("|", "｜").replace("\n", " ")
            lines.append(f"{line['speaker']} @{start:.2f} | {safe_voice} | {safe_text}")
        timeline += seconds
    return "\n".join(lines)


def screenplay_to_character_map(screenplay: dict) -> str:
    """角色 -> 图片槽/音频槽/音色 对照表（给人看/复核用）。"""
    rows = []
    for char in screenplay.get("characters") or []:
        image = f"@图片{char['image_slot']}" if char.get("image_slot") else "（未绑定图片）"
        audio = f"音频槽{char['audio_slot']}" if char.get("audio_slot") else "（未绑定音频槽）"
        voice = char.get("voice") or "（未指定音色）"
        rows.append(f"{char['name']} | {image} | {audio} | {voice}")
    return "\n".join(rows)


def screenplay_from_parsed_script(parsed: dict, *, default_seconds: float = 5.0) -> dict:
    """把剧本加载器解析出来的 segments 转成 screenplay 结构（供素材匹配用）。

    外部剧本可能没有 JSON，只有“第N段 + 角色：台词”的文本；这里把对白抽成
    dialogue、其余行留作 actions，角色按首次出现顺序编号 S1/S2...
    """
    char_ids: dict[str, str] = {}
    characters: list[dict] = []
    segments: list[dict] = []
    dialogue_line = re.compile(r"^\s*[^\s:：]{1,12}\s*[:：]")
    for segment in parsed.get("segments") or []:
        text = str(segment.get("text") or "")
        action_lines = []
        for line in text.splitlines():
            if not line.strip():
                continue
            if dialogue_line.match(line):
                continue
            action_lines.append(line.strip())
        dialogue = []
        for line in segment.get("dialogue") or []:
            name = str(line.get("character") or "").strip() or "旁白"
            if name not in char_ids:
                char_ids[name] = f"S{len(characters) + 1}"
                characters.append({"id": char_ids[name], "name": name, "image_slot": None,
                                   "audio_slot": len(characters) + 1, "voice": ""})
            dialogue.append({"speaker_id": char_ids[name], "speaker": name,
                             "text": str(line.get("text") or "").strip(), "at": None})
        segments.append({"index": len(segments) + 1,
                         "seconds": float(segment.get("seconds") or default_seconds),
                         "scene": "", "actions": "；".join(action_lines)[:800],
                         "image_refs": list(segment.get("refs") or []),
                         "dialogue": dialogue})
    return {"schema": "DIRECTOR_SCREENPLAY@1", "title": "", "language": "",
            "characters": characters, "segments": segments, "warnings": []}


def v6_to_screenplay(raw: str, *, language: str = "中文") -> dict:
    """把 H3 V6 分段提示词文本转成 screenplay 结构（粗解析，够用就好）。"""
    text = (raw or "").strip()
    matches = list(_V6_HEADER.finditer(text))
    if not matches:
        raise ValueError("V6 文本里没有找到【第N段｜X秒】段头")
    segments = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        speaker_ids = []
        dialogue = []
        for line in _V6_DIALOGUE.finditer(body):
            sid = line.group("sid")
            speaker_ids.append(sid)
            dialogue.append({"speaker": sid, "text": line.group("text").strip(), "at": None})
        refs = sorted({int(n) for n in _V6_PICTURE.findall(body)})
        actions = _V6_DIALOGUE.sub("", body)
        actions = re.sub(r"^\s*(integrated_multimodal_description|overall_soundscape|non_diegetic_music)\s*[:：]\s*", "", actions, flags=re.MULTILINE)
        actions = re.sub(r"^[0-9.]+[～~][0-9.]+秒\s*[:：]\s*", "", actions, flags=re.MULTILINE)
        segments.append({"index": index + 1, "seconds": float(match.group(2)),
                         "scene": "", "actions": " ".join(actions.split())[:800],
                         "image_refs": refs, "dialogue": dialogue})
    characters = [{"id": f"S{i}", "name": f"S{i}", "image_slot": i,
                   "audio_slot": i, "voice": ""}
                  for i in range(1, max(2, len({d["speaker"] for s in segments for d in s["dialogue"]}) + 1))]
    return {"schema": "DIRECTOR_SCREENPLAY@1", "title": "", "language": language,
            "characters": characters, "segments": segments, "warnings": ["由 V6 文本转换"]}
