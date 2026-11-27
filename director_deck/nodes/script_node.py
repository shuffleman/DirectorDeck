"""DirectorDeck · 剧本加载器（M1）：一大段文本 -> 结构化段落。

和 SegmentBrief 的分工：
- 本节点处理“整部剧本”，输出 DIRECTOR_SCRIPT（所有段落）；
- 想单独改某一段，用 SegmentBrief 接到生成器的 brief 输入上覆盖。
"""

from __future__ import annotations

import hashlib
import json

from ..core import script as script_lib
from ..core.types import CATEGORY, MAX_SEGMENTS, TYPE_SCRIPT

# 默认给一段能直接跑的示例剧本，省得用户新建节点后一片空白不知道写什么。
EXAMPLE_SCRIPT = """第1段（5秒）
清晨的湖面，薄雾浮动，一叶小舟缓缓划过，镜头从远处缓慢推进，暖金色晨光。

第2段（5秒）
特写：船夫粗糙的手握住船桨，水珠从桨叶落下，逆光里的水雾，镜头极慢推近。
"""


class DirectorDeckScriptDesk:
    """剧本/脚本加载器：输出 DIRECTOR_SCRIPT + 一段给人看的中文摘要。"""

    CATEGORY = f"{CATEGORY}/剧本"
    FUNCTION = "parse_text"
    RETURN_TYPES = (TYPE_SCRIPT, "STRING")
    RETURN_NAMES = ("script", "summary")
    DESCRIPTION = ("把剧本拆成结构化段落。支持 第N段/镜头N/空行/分隔线/每行 等分段；"
                   "标题可带时长（（5秒）/5s/0:05）；正文可用 @图片N 引用素材。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": EXAMPLE_SCRIPT,
                                    "tooltip": "剧本/脚本全文"}),
                "mode": (list(script_lib.MODES), {"default": "auto",
                                                  "tooltip": "分段模式；auto=智能判断"}),
                "default_seconds": ("FLOAT", {"default": 5.0, "min": 0.5, "max": 60.0,
                                              "step": 0.1, "tooltip": "段落没写时长时用它"}),
                "max_segments": ("INT", {"default": MAX_SEGMENTS, "min": 1,
                                         "max": MAX_SEGMENTS, "tooltip": "防呆上限，超出会截断并警告"}),
                "keep_header": ("BOOLEAN", {"default": False,
                                            "tooltip": "是否把“第N段”标题也留在正文里"}),
            },
            "optional": {
                "regex_pattern": ("STRING", {"default": "",
                                             "tooltip": "mode=regex 时生效"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 文本/参数一变就重新解析；没变就用缓存。
        return hashlib.sha1(json.dumps(kwargs, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    def parse_text(self, text, mode="auto", default_seconds=5.0,
                   max_segments=MAX_SEGMENTS, keep_header=False,
                   regex_pattern=""):
        data = script_lib.parse_script(
            text, mode=mode, default_seconds=default_seconds,
            max_segments=int(max_segments), keep_header=bool(keep_header),
            regex_pattern=regex_pattern or None)
        # 摘要只取前 6 段，避免节点上显示一大坨。
        lines = [f"{s['index']}. {s['seconds']}s: {s['text'][:40].replace(chr(10), ' ')}"
                 for s in data["segments"][:6]]
        summary = f"{len(data['segments'])} 段 / {data.get('total_seconds', 0)}s" + (
            "\n" + "\n".join(lines) if lines else "")
        if data["warnings"]:
            summary += "\n⚠ " + "；".join(data["warnings"])
        return (data, summary)
