"""DirectorDeck · 段级剧本覆盖（SegmentBrief）。

什么时候用？
- 整部剧本由 ScriptDesk 管，但“第 3 段我想单独改文案/秒数”；
- 或者某一段要用完全不同的提示词（比如插入一个特写）。

用法：把这个节点接到生成器的 `brief` 输入，并把 `brief_policy` 选成 `replace`。
不接的时候 policy 选 `inherit`，就会继续用剧本里那一段。
"""

from __future__ import annotations

import hashlib
import json

from ..core import assets as assets_lib
from ..core import script as script_lib
from ..core.types import CATEGORY, TYPE_BRIEF


class DirectorDeckSegmentBrief:
    """单段剧本：输出 DIRECTOR_BRIEF。"""

    CATEGORY = f"{CATEGORY}/剧本"
    FUNCTION = "build"
    RETURN_TYPES = (TYPE_BRIEF,)
    RETURN_NAMES = ("brief",)
    DESCRIPTION = ("给某一段单独的剧本：正文/秒数/对白/素材引用。"
                   "接到生成器的 brief 输入并把 brief_policy 设为 replace 才会生效。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "",
                                    "tooltip": "本段提示词/剧本，可写 @图片N 引用素材"}),
                "seconds": ("FLOAT", {"default": 5.0, "min": 0.5, "max": 60.0, "step": 0.1,
                                      "tooltip": "本段秒数；生成时会吸附到 17k+5 帧栅格"}),
            },
            "optional": {
                "dialogue": ("STRING", {"multiline": True, "default": "",
                                        "tooltip": "本段对白，每行“角色: 台词”"}),
                "refs": ("STRING", {"default": "",
                                    "tooltip": "额外素材引用，如 1,2；正文里的 @图片N 也会自动收集"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return hashlib.sha1(json.dumps(kwargs, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    def build(self, text, seconds=5.0, dialogue="", refs=""):
        # 对白优先用用户手填的；没填就从正文里自动抽。
        dialogue_lines = script_lib.parse_dialogue(dialogue) if dialogue.strip() else []
        if not dialogue_lines:
            dialogue_lines = script_lib.parse_dialogue(text)
        # 引用：正文 @图片N + 手填的逗号列表，去重排序。
        ref_numbers = set(script_lib.refs_in_text(text))
        for part in str(refs or "").replace("，", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ref_numbers.add(int(part))
        brief = {
            "schema": "DIRECTOR_BRIEF@1",
            "text": str(text or ""),
            "seconds": float(seconds),
            "dialogue": dialogue_lines,
            "refs": sorted(ref_numbers),
        }
        return (brief,)
