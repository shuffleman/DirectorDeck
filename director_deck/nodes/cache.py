"""DirectorDeck · 抽卡缓存（M2 轻量版）。

抽卡的本质是“同样的输入 + 不同 seed 重新生成某一段”。ComfyUI 自己会按 IS_CHANGED
缓存上游节点（所以重抽第 2 段时，第 1 段不会重跑，这点是白送的）。

这个节点负责“跨运行记住每一段的抽卡结果”：
- store：把当前段的结果摘要（不含张量）写到 output/DirectorDeck/cache/；
- status：查询这一段的指纹之前有没有跑过；
- clear：删掉缓存记录，强制重新抽。

注意：M2 只缓存元数据，不复用画面；真正的“秒级复用”会在 M4 前端里做。
"""

from __future__ import annotations

import hashlib
import json
import os

import folder_paths

from ..core.types import CATEGORY, TYPE_SEGMENT

MODES = ["status", "store", "clear"]


class DirectorDeckSegmentCache:
    """抽卡缓存：记录/查询/清除某一段的生成指纹。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "operate"
    RETURN_TYPES = (TYPE_SEGMENT, "STRING")
    RETURN_NAMES = ("segment", "report")
    DESCRIPTION = ("按段指纹记录/查询/清除抽卡缓存；只存元数据，不存画面。"
                   "mode=store 写记录，status 查命中，clear 删除记录。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "segment": (TYPE_SEGMENT, {"tooltip": "生成器输出的段"}),
                "mode": (MODES, {"default": "status"}),
            },
            "optional": {
                "scope": ("STRING", {"default": "default",
                                     "tooltip": "缓存命名空间，多项目/多工作流用不同的值"}),
            },
        }

    @staticmethod
    def _cache_dir() -> str:
        base = os.path.join(folder_paths.get_output_directory(), "DirectorDeck", "cache")
        os.makedirs(base, exist_ok=True)
        return base

    def operate(self, segment, mode="status", scope="default"):
        chain_key = str(segment.get("chain_key") or "unknown")
        seed = segment.get("seed")
        # 指纹 = 解析结果哈希 + seed；改文案/素材/种子都会变成新指纹（新抽卡）。
        fingerprint = hashlib.sha1(
            f"{scope}|{chain_key}|{seed}".encode("utf-8")).hexdigest()
        path = os.path.join(self._cache_dir(), f"{fingerprint[:16]}.json")

        if mode == "store":
            payload = {
                "scope": scope,
                "chain_key": chain_key,
                "seed": seed,
                "prompt": segment.get("prompt"),
                "frames": segment.get("frames"),
                "store_key": segment.get("store_key"),
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            return (segment, f"已记录本次抽卡：{os.path.basename(path)}")

        if mode == "clear":
            removed = False
            if os.path.isfile(path):
                os.remove(path)
                removed = True
            return (segment, "已清除记录（下次同参数会重新抽）" if removed else "没有找到记录，无需清除")

        # status
        if os.path.isfile(path):
            return (segment, f"命中缓存记录：{os.path.basename(path)}（同指纹跑过）")
        return (segment, f"未命中缓存记录：{os.path.basename(path)}（这段是新抽卡）")
