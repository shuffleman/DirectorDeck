"""剧本解析（契约 §2.5 / §7）。

把一段剧本文本拆成结构化段落：{index, text, seconds, dialogue, refs}。

支持模式：auto / header / blank / divider / line / regex。
- header：`第N段`、`第N幕`、`镜头N`、`Shot N`、`N.`、`N、` 等标题；
- blank ：空行分段；
- divider：`---` 分隔线分段；
- line  ：每行一段；
- regex ：自定义正则（外部传入 pattern）；
- auto  ：有标题用标题，否则有分隔线用分隔线，否则空行，否则整段。

时长解析：`（5秒）`、`5秒`、`5s`、`0:05`。
对白解析：`角色: 台词`、`角色：台词`、`「台词」`（无角色绑定）。
素材引用：正文中的 `@图片N` 收集到 refs（正文保留原文，绑定由 assets.bind_prompt 做）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .types import MAX_SEGMENTS, SCHEMA_VERSION, error

MODES = ("auto", "header", "blank", "divider", "line", "regex")

_HEADER_RE = re.compile(
    r"^\s*[#>*\-—]*\s*(?:"
    r"第\s*(?P<num>[0-9]{1,3}|[一二三四五六七八九十]{1,3})\s*[段幕镜场]"
    r"|镜头\s*(?P<shot>[0-9]{1,3})"
    r"|shot\s*(?P<shot_en>[0-9]{1,3})"
    r"|(?P<num2>[0-9]{1,3})\s*[.、)）]"
    r")\s*[）)]?\s*(?P<rest>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_SEC_RE = re.compile(r"(?:[（(]\s*)?(?P<sec>[0-9]{1,2}(?:\.[0-9])?)\s*(?:秒|s|S)(?:\s*[）)])?")
_SEC_CLOCK_RE = re.compile(r"(?<![0-9])(?P<min>[0-9]{1,2}):(?P<sec>[0-9]{2})(?![0-9])")
_DIVIDER_RE = re.compile(r"^\s*[-=_*~—]{3,}\s*$", re.MULTILINE)
_DIALOGUE_RE = re.compile(r"^\s*(?P<char>[^\s:：」』“”\"]{1,12})\s*[:：]\s*(?P<text>.+)$")
_QUOTE_RE = re.compile(r"[「『“](?P<text>[^」』”]+)[」』”]")
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn_to_int(value: str) -> int | None:
    value = (value or "").strip()
    if value.isdigit():
        return int(value)
    if not value:
        return None
    if value in _CN_DIGITS:
        return _CN_DIGITS[value]
    if value.startswith("十") and len(value) == 2 and value[1] in _CN_DIGITS:
        return 10 + _CN_DIGITS[value[1]]
    if len(value) == 2 and value[0] in _CN_DIGITS and value[1] == "十":
        return _CN_DIGITS[value[0]] * 10
    if len(value) == 3 and value[0] in _CN_DIGITS and value[1] == "十" and value[2] in _CN_DIGITS:
        return _CN_DIGITS[value[0]] * 10 + _CN_DIGITS[value[2]]
    return None


def parse_seconds(text: str, default: float = 5.0) -> float:
    """从任意文本中解析时长；找不到返回 default。"""
    if not text:
        return float(default)
    clock = _SEC_CLOCK_RE.search(text)
    if clock:
        return int(clock.group("min")) * 60 + int(clock.group("sec"))
    match = _SEC_RE.search(text)
    if match:
        try:
            value = float(match.group("sec"))
            if 0.2 <= value <= 60:
                return value
        except ValueError:
            pass
    return float(default)


def parse_dialogue(text: str) -> list[dict]:
    """解析对白行，返回 [{character, text}]。"""
    lines: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _DIALOGUE_RE.match(line)
        if match:
            character = match.group("char").strip("（）()[]【】")
            lines.append({"character": character, "text": match.group("text").strip()})
            continue
        quote = _QUOTE_RE.search(line)
        if quote:
            lines.append({"character": "", "text": quote.group("text").strip()})
    return lines


def refs_in_text(text: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"@图片\s*(\d{1,2})", text or "")})


def _make_segment(index: int, text: str, seconds: float) -> dict:
    text = (text or "").strip()
    return {
        "index": index,
        "text": text,
        "seconds": float(seconds),
        "dialogue": parse_dialogue(text),
        "refs": refs_in_text(text),
    }


def _split_header(raw: str, default_seconds: float, keep_header: bool) -> list[dict]:
    segments: list[dict] = []
    current: list[str] = []
    current_seconds = float(default_seconds)

    def flush():
        nonlocal current
        if not current:
            return
        body = "\n".join(current).strip()
        if body:
            segments.append(_make_segment(len(segments) + 1, body, current_seconds))
        current = []

    for line in raw.splitlines():
        match = _HEADER_RE.match(line)
        if match:
            flush()
            current_seconds = parse_seconds(line, default_seconds)
            if keep_header:
                current = [line.strip()]
            else:
                rest = (match.group("rest") or "").strip()
                rest = _SEC_RE.sub("", rest).strip("（）() ：:，,、")
                rest = rest.lstrip("）)")
                rest = rest.strip()
                current = [rest] if rest else []
        else:
            current.append(line)
    flush()
    return segments


def _split_blank(raw: str, default_seconds: float) -> list[dict]:
    blocks = re.split(r"\n\s*\n+", raw.strip())
    return [_make_segment(i + 1, block, default_seconds)
            for i, block in enumerate(b for b in blocks if b.strip())]


def _split_divider(raw: str, default_seconds: float) -> list[dict]:
    parts = _DIVIDER_RE.split(raw)
    return [_make_segment(i + 1, part, default_seconds)
            for i, part in enumerate(p for p in parts if p.strip())]


def _split_line(raw: str, default_seconds: float) -> list[dict]:
    lines = [line for line in raw.splitlines() if line.strip()]
    return [_make_segment(i + 1, line, default_seconds) for i, line in enumerate(lines)]


def parse_script(text: str, *, mode: str = "auto", default_seconds: float = 5.0,
                 max_segments: int = MAX_SEGMENTS, keep_header: bool = False,
                 regex_pattern: str | None = None) -> dict:
    """把剧本文本解析成 DIRECTOR_SCRIPT dict。"""
    raw = text or ""
    if not raw.strip():
        return {"schema": f"DIRECTOR_SCRIPT@{SCHEMA_VERSION}", "raw": raw,
                "mode": mode, "segments": [], "warnings": ["剧本为空"]}
    if mode not in MODES:
        raise error("DD-E004", f"未知分段模式 {mode!r}，可选：{MODES}")

    warnings: list[str] = []
    resolved_mode = mode
    if mode == "auto":
        if _HEADER_RE.search(raw):
            resolved_mode = "header"
        elif _DIVIDER_RE.search(raw):
            resolved_mode = "divider"
        else:
            resolved_mode = "blank"

    if resolved_mode == "header":
        segments = _split_header(raw, default_seconds, keep_header)
    elif resolved_mode == "blank":
        segments = _split_blank(raw, default_seconds)
    elif resolved_mode == "divider":
        segments = _split_divider(raw, default_seconds)
    elif resolved_mode == "line":
        segments = _split_line(raw, default_seconds)
    else:  # regex
        if not regex_pattern:
            raise error("DD-E004", "mode=regex 需要提供 regex_pattern")
        parts = re.split(regex_pattern, raw)
        segments = [_make_segment(i + 1, part, default_seconds)
                    for i, part in enumerate(p for p in parts if p.strip())]

    if len(segments) > max_segments:
        warnings.append(f"段落数 {len(segments)} 超过上限 {max_segments}，已截断")
        segments = segments[:max_segments]
    total = 0.0
    for index, segment in enumerate(segments, start=1):
        segment["index"] = index
        total += segment["seconds"]

    return {
        "schema": f"DIRECTOR_SCRIPT@{SCHEMA_VERSION}",
        "raw": raw,
        "mode": resolved_mode if mode == "auto" else mode,
        "segments": segments,
        "total_seconds": round(total, 3),
        "warnings": warnings,
    }
