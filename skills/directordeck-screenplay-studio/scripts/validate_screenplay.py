#!/usr/bin/env python3
"""DirectorDeck 外部剧本校验器（独立脚本，不依赖 ComfyUI / torch）。

用法：
    python validate_screenplay.py 剧本.txt
    python validate_screenplay.py 剧本.json --format json
    python validate_screenplay.py - --format v6 < 剧本.txt
    python validate_screenplay.py 剧本.txt --json

退出码：0=无 error（可以有 warning）；1=有 error；2=用法/读文件错误。

它只做“能不能被 DirectorDeck 剧本导入节点正常解析”的格式检查，不判断剧情好坏。
"""

from __future__ import annotations

import argparse
import json
import re
import sys

MAX_SEGMENTS = 64
MAX_REF = 9
MIN_SECONDS, MAX_SECONDS = 1.0, 60.0

DD_HEADER = re.compile(r"^第\s*(\d+)\s*段\s*[（(]\s*([0-9]+(?:\.[0-9]+)?)\s*秒\s*[）)]\s*$")
DIALOGUE = re.compile(r"^\s*(?P<char>[^\s:：」』“”\"]{1,12})\s*[:：]\s*(?P<text>.+)$")
REF = re.compile(r"@图片\s*(\d{1,2})")
V6_HEADER = re.compile(r"【\s*第\s*(\d+)\s*段\s*[｜|]\s*([0-9]+(?:\.[0-9]+)?)\s*秒\s*】")
V6_DIALOGUE = re.compile(r"\((?P<sid>S\d+)\)[^<\n]*?<d>\s*(?:\[[^\]]+\])?\s*(?P<text>[^<]+?)\s*</d>")
V6_PICTURE = re.compile(r"<Picture\s*(\d+)>", re.IGNORECASE)


class Report:
    def __init__(self, fmt: str):
        self.format = fmt
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.segment_count = 0

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def as_dict(self) -> dict:
        return {
            "format": self.format,
            "ok": not self.errors,
            "segment_count": self.segment_count,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _seconds_ok(seconds: float, report: Report, where: str) -> bool:
    if not (MIN_SECONDS <= seconds <= MAX_SECONDS):
        report.error(f"{where} 秒数 {seconds:g} 不在 {MIN_SECONDS:g}–{MAX_SECONDS:g} 秒范围")
        return False
    return True


def _check_dialogue_length(text: str, seconds: float, report: Report, where: str) -> None:
    # 粗略按“每秒 3.2 个中文字”估算；只是警告，不替用户改台词。
    limit = max(6, int(round(seconds * 3.2)))
    compact = re.sub(r"\s+", "", text)
    if len(compact) > limit:
        report.warn(
            f"{where} 台词 {len(compact)} 字，按 {seconds:g} 秒估算建议 ≤{limit} 字：{text[:18]}…"
        )


def _check_refs(text: str, report: Report, where: str) -> None:
    for value in REF.findall(text):
        slot = int(value)
        if not (1 <= slot <= MAX_REF):
            report.error(f"{where} 素材引用 @图片{slot} 越界（只允许 1..{MAX_REF}）")


def detect_format(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") or '"segments"' in stripped:
        return "json"
    if V6_HEADER.search(stripped):
        return "v6"
    if DD_HEADER.search(stripped):
        return "dd"
    return "dd"


def validate_dd(text: str, report: Report, default_seconds: float, max_segments: int) -> None:
    report.format = "DirectorDeck 文本"
    if "```" in text:
        report.error("不要用 Markdown 代码围栏包裹剧本（导入节点会把 ``` 当正文）")
    lines = text.strip().splitlines()
    if not lines:
        report.error("剧本为空")
        return

    blocks: list[tuple[int, float, list[str], int]] = []  # index, seconds, body, line_no
    current = None
    for line_no, line in enumerate(lines, start=1):
        match = DD_HEADER.match(line.strip())
        if match:
            if current is not None:
                blocks.append(current)
            current = (int(match.group(1)), float(match.group(2)), [], line_no)
            continue
        if current is None:
            if line.strip():
                report.error(f"第 {line_no} 行出现在第一个段头之前：{line.strip()[:40]}")
            continue
        current[2].append(line)
    if current is not None:
        blocks.append(current)
    report.segment_count = len(blocks)
    if not blocks:
        report.error("没有找到 `第N段（X秒）` 段头")
        return
    if len(blocks) > max_segments:
        report.error(f"段数 {len(blocks)} 超过导入上限 {max_segments}")

    for expected, (index, seconds, body, line_no) in enumerate(blocks, start=1):
        where = f"第{index}段（第 {line_no} 行）"
        if index != expected:
            report.error(f"{where} 段号不连续，应为第{expected}段")
        _seconds_ok(seconds, report, where)
        if not any(line.strip() for line in body):
            report.error(f"{where} 是空段")
            continue
        for offset, line in enumerate(body):
            stripped = line.strip()
            if not stripped:
                continue
            line_where = f"{where} 第 {offset + 1} 行"
            dialogue = DIALOGUE.match(stripped)
            if dialogue:
                _check_dialogue_length(dialogue.group("text"), seconds, report, line_where)
            elif "：" in stripped or ":" in stripped:
                # 有冒号却不是合法对白（通常是名字超长/带空格），导入器会当成画面行。
                report.warn(f"{line_where} 含冒号但没识别成对白（检查角色名是否 ≤12 字且无空格）")
            _check_refs(stripped, report, line_where)

    if not DD_HEADER.match(lines[0].strip()):
        report.warn("第一行不是段头；导入器能容忍，但建议从 `第1段（X秒）` 开始")


def _json_seconds(value, default_seconds: float, report: Report, where: str) -> float:
    try:
        seconds = float(value if value is not None else default_seconds)
    except (TypeError, ValueError):
        report.error(f"{where} seconds 不是数字：{value!r}")
        return default_seconds
    return seconds


def validate_json(text: str, report: Report, default_seconds: float, max_segments: int) -> None:
    report.format = "JSON 剧本"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        report.error(f"JSON 解析失败：{exc}")
        return
    if not isinstance(data, dict):
        report.error("JSON 顶层必须是对象")
        return
    segments = data.get("segments") or data.get("shots") or []
    if not isinstance(segments, list) or not segments:
        report.error("JSON 里没有非空 segments 数组")
        return
    report.segment_count = len(segments)
    if len(segments) > max_segments:
        report.error(f"段数 {len(segments)} 超过导入上限 {max_segments}")

    characters = data.get("characters") or []
    if characters and not isinstance(characters, list):
        report.error("characters 必须是数组")
    for char in characters if isinstance(characters, list) else []:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name") or char.get("character") or "")
        if not name:
            report.warn("characters 里有一项缺 name")
        for key in ("image_slot", "audio_slot"):
            value = char.get(key)
            if value in (None, "", 0):
                continue
            try:
                slot = int(value)
            except (TypeError, ValueError):
                report.error(f"角色 {name} 的 {key} 不是整数：{value!r}")
                continue
            if not (1 <= slot <= MAX_REF):
                report.error(f"角色 {name} 的 {key}={slot} 越界（1..{MAX_REF}）")

    for index, segment in enumerate(segments, start=1):
        where = f"第{index}段"
        if not isinstance(segment, dict):
            report.error(f"{where} 不是对象")
            continue
        seconds = _json_seconds(segment.get("seconds"), default_seconds, report, where)
        _seconds_ok(seconds, report, where)
        actions = str(segment.get("actions") or segment.get("description") or "").strip()
        scene = str(segment.get("scene") or segment.get("location") or "").strip()
        dialogue = segment.get("dialogue") or segment.get("lines") or []
        if not (actions or scene or dialogue):
            report.error(f"{where} 既没有 actions/scene 也没有 dialogue")
        refs = segment.get("image_refs") or segment.get("refs") or []
        if refs and not isinstance(refs, list):
            report.error(f"{where} image_refs 必须是数组")
        for value in refs if isinstance(refs, list) else []:
            try:
                slot = int(value)
            except (TypeError, ValueError):
                report.error(f"{where} image_refs 里有非整数槽号：{value!r}")
                continue
            if not (1 <= slot <= MAX_REF):
                report.error(f"{where} image_refs 槽号 {slot} 越界（1..{MAX_REF}）")
        if isinstance(dialogue, list):
            for line in dialogue:
                if not isinstance(line, dict):
                    report.error(f"{where} dialogue 里有一项不是对象")
                    continue
                speaker = str(line.get("character") or line.get("speaker") or "").strip()
                content = str(line.get("text") or line.get("line") or "").strip()
                if not speaker or not content:
                    report.error(f"{where} 有一条对白缺 character 或 text")
                    continue
                _check_dialogue_length(content, seconds, report,
                                       f"{where} 对白（{speaker}）")


def validate_v6(text: str, report: Report, max_segments: int) -> None:
    report.format = "H3 V6 文本"
    headers = list(V6_HEADER.finditer(text))
    if not headers:
        report.error("没有找到 `【第N段｜X秒】` 段头")
        return
    report.segment_count = len(headers)
    if len(headers) > max_segments:
        report.error(f"段数 {len(headers)} 超过导入上限 {max_segments}")

    for expected, match in enumerate(headers, start=1):
        index = int(match.group(1))
        seconds = float(match.group(2))
        where = f"第{index}段"
        if index != expected:
            report.error(f"{where} 段号不连续，应为第{expected}段")
        _seconds_ok(seconds, report, where)
        start = match.end()
        end = headers[expected].start() if expected < len(headers) else len(text)
        body = text[start:end]
        dialogue_count = 0
        for line in V6_DIALOGUE.finditer(body):
            dialogue_count += 1
            _check_dialogue_length(line.group("text").strip(), seconds, report,
                                   f"{where} 对白（{line.group('sid')}）")
        for picture in V6_PICTURE.findall(body):
            slot = int(picture)
            if not (1 <= slot <= MAX_REF):
                report.error(f"{where} <Picture {slot}> 槽号越界（1..{MAX_REF}）")
        if not body.strip():
            report.error(f"{where} 是空段")
        if dialogue_count == 0 and "<d>" not in body:
            report.warn(f"{where} 没有对白（V6 允许，但确认是有意的）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DirectorDeck 外部剧本格式校验")
    parser.add_argument("path", nargs="?", default="-", help="剧本文件路径，- 表示 stdin")
    parser.add_argument("--format", choices=["auto", "dd", "json", "v6"], default="auto")
    parser.add_argument("--max-segments", type=int, default=MAX_SEGMENTS)
    parser.add_argument("--default-seconds", type=float, default=5.0)
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)

    try:
        if args.path == "-":
            text = sys.stdin.read()
        else:
            with open(args.path, "r", encoding="utf-8") as handle:
                text = handle.read()
    except OSError as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 2

    fmt = detect_format(text) if args.format == "auto" else args.format
    report = Report(fmt)
    if not text.strip():
        report.error("剧本为空")
    elif fmt == "json":
        validate_json(text, report, args.default_seconds, args.max_segments)
    elif fmt == "v6":
        validate_v6(text, report, args.max_segments)
    else:
        validate_dd(text, report, args.default_seconds, args.max_segments)

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"格式：{report.format}；段数：{report.segment_count}")
        for message in report.errors:
            print(f"[ERROR] {message}")
        for message in report.warnings:
            print(f"[WARN] {message}")
        print("结论：通过（无 error）" if not report.errors else
              f"结论：未通过（{len(report.errors)} 个 error）")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
