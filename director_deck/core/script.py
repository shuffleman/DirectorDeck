"""剧本解析：把一大段文本拆成“第 1 段、第 2 段……”这种结构化数据。

为什么要自己解析，不直接丢给模型？
因为“分几段、每段几秒、哪句台词属于哪个角色、哪段用了几张参考图”这些信息
后面生成器、锁音、合并器都要用，必须结构化成数据，不能靠模型猜。

支持的分段方式（mode）：
- auto  ：智能判断。有“第N段/镜头N”标题就按标题分，没有就看分隔线，再没有就按空行；
- header：只看标题（第N段、第N幕、镜头N、Shot N、1.、2、……）；
- blank ：空行分段；
- divider：`---` 这类分隔线分段；
- line  ：一行一段（适合逐句脚本）；
- regex ：自己给正则（高级玩法）。

时长写法都认：`（5秒）`、`5秒`、`5s`、`0:05`。标题里没写就吃默认值。
对白写法也认几种：`女主：你好`、`男主: 再见`、`「无名台词」`。
素材引用：正文里写 `@图片1`，解析时会把槽号收进这一段的 refs，
真正替换成 `<Picture 1>` 是 assets.bind_prompt 干的活（职责分开）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .types import MAX_SEGMENTS, SCHEMA_VERSION, error

MODES = ("auto", "header", "blank", "divider", "line", "regex")

# 标题正则：一开头可能是 Markdown 的 #/*/-，也可能是全角符号，后面接
#   “第N段 / 第N幕 / 第N镜 / 第N场 / 镜头N / Shot N / 1. / 2、” 这些都算标题。
_HEADER_RE = re.compile(
    r"^\s*[#>*\-—]*\s*(?:"
    r"第\s*(?P<num>[0-9]{1,3}|[一二三四五六七八九十]{1,3})\s*[段幕镜场]"
    r"|镜头\s*(?P<shot>[0-9]{1,3})"
    r"|shot\s*(?P<shot_en>[0-9]{1,3})"
    r"|(?P<num2>[0-9]{1,3})\s*[.、)）]"
    r")\s*[）)]?\s*(?P<rest>.*)$",
    re.IGNORECASE | re.MULTILINE,
)

# 秒数：`（5秒）`、`5s`、`5.5秒` 都吃。
_SEC_RE = re.compile(r"(?:[（(]\s*)?(?P<sec>[0-9]{1,2}(?:\.[0-9])?)\s*(?:秒|s|S)(?:\s*[）)])?")
# 时钟写法：0:05。
_SEC_CLOCK_RE = re.compile(r"(?<![0-9])(?P<min>[0-9]{1,2}):(?P<sec>[0-9]{2})(?![0-9])")
# 分隔线：---、===、***、~~~ 之类，长度至少 3。
_DIVIDER_RE = re.compile(r"^\s*[-=_*~—]{3,}\s*$", re.MULTILINE)
# 对白：`角色: 台词`（中英文冒号都行，角色名最多 12 个字）。
_DIALOGUE_RE = re.compile(r"^\s*(?P<char>[^\s:：」』“”\"]{1,12})\s*[:：]\s*(?P<text>.+)$")
# 引号台词：没有角色名时，至少把「」、『』、双引号里的内容标成对白。
_QUOTE_RE = re.compile(r"[「『“](?P<text>[^」』”]+)[」』”]")

# 中文数字只支持到 99，够用了（一段视频拆不出 100 段）。
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn_to_int(value: str) -> int | None:
    """把“一/十二/二十三”转成数字；转不了返回 None。"""
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
    """从一段文字里找时长；找不到就用默认值。

    先认 0:05 这种时钟写法，再认“5秒/5s”。太离谱的值（<0.2 或 >60 秒）
    当没写，避免把“第5段”里的 5 误当成 5 秒。
    """
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
    """把一段文本里的对白行抽出来，返回 [{"character": 角色, "text": 台词}]。"""
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
    """这一段引用了哪几张图（槽号升序、去重）。"""
    return sorted({int(n) for n in re.findall(r"@图片\s*(\d{1,2})", text or "")})


def _make_segment(index: int, text: str, seconds: float) -> dict:
    """拼一个标准段落对象：正文 + 时长 + 对白 + 素材引用。"""
    text = (text or "").strip()
    return {
        "index": index,
        "text": text,
        "seconds": float(seconds),
        "dialogue": parse_dialogue(text),
        "refs": refs_in_text(text),
    }


def _split_header(raw: str, default_seconds: float, keep_header: bool) -> list[dict]:
    """按“第N段”这类标题分段。

    keep_header=False（默认）时，标题只用来定位，不进正文；
    如果标题后面还跟了内容（比如“第1段：开门”），那部分会保留。
    注意要把标题里的“（5秒）”抠掉，别让它混进提示词。
    """
    segments: list[dict] = []
    current: list[str] = []
    current_seconds = float(default_seconds)

    def flush():
        # 把攒下来的行收成一段；空段（标题后面没内容）直接丢。
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
                # 标题剩下的部分：去掉时长、括号、冒号，剩下的当正文开头。
                rest = (match.group("rest") or "").strip()
                rest = _SEC_RE.sub("", rest).strip("（）() ：:，,、")
                rest = rest.lstrip("）)").strip()
                current = [rest] if rest else []
        else:
            current.append(line)
    flush()
    return segments


def _split_blank(raw: str, default_seconds: float) -> list[dict]:
    """空行分段：连续两个换行算一段。"""
    blocks = re.split(r"\n\s*\n+", raw.strip())
    return [_make_segment(i + 1, block, default_seconds)
            for i, block in enumerate(b for b in blocks if b.strip())]


def _split_divider(raw: str, default_seconds: float) -> list[dict]:
    """分隔线分段：--- / === / *** 这类。"""
    parts = _DIVIDER_RE.split(raw)
    return [_make_segment(i + 1, part, default_seconds)
            for i, part in enumerate(p for p in parts if p.strip())]


def _split_line(raw: str, default_seconds: float) -> list[dict]:
    """每行一段（适合逐镜头的短脚本）。"""
    lines = [line for line in raw.splitlines() if line.strip()]
    return [_make_segment(i + 1, line, default_seconds) for i, line in enumerate(lines)]


def parse_script(text: str, *, mode: str = "auto", default_seconds: float = 5.0,
                 max_segments: int = MAX_SEGMENTS, keep_header: bool = False,
                 regex_pattern: str | None = None) -> dict:
    """主入口：剧本文本 -> DIRECTOR_SCRIPT 字典。

    返回结构见 docs/CONTRACTS.md：raw / mode / segments / total_seconds / warnings。
    """
    raw = text or ""
    if not raw.strip():
        return {"schema": f"DIRECTOR_SCRIPT@{SCHEMA_VERSION}", "raw": raw,
                "mode": mode, "segments": [], "warnings": ["剧本为空"]}
    if mode not in MODES:
        raise error("DD-E004", f"未知分段模式 {mode!r}，可选：{MODES}")

    warnings: list[str] = []
    resolved_mode = mode
    if mode == "auto":
        # 智能判断顺序：标题 > 分隔线 > 空行。都没有就整段当一段。
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

    # 段数防呆：超过上限就截断（同时给用户一个警告，别让用户以为全解析了）。
    if len(segments) > max_segments:
        warnings.append(f"段落数 {len(segments)} 超过上限 {max_segments}，已截断")
        segments = segments[:max_segments]

    # 重排一次序号并累加总时长（严格 1 起，方便生成器用 segment_index）。
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
