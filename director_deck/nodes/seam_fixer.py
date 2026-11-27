"""DirectorDeck · 接缝修正器（M2，独立工具节点）。

链式生成时，生成器内部已经会自动修正接缝（基于上一段的 delivery 尾巴）。
这个节点是给两种情况准备的：
1. 用户想拿已有的两段单独修接缝；
2. 想手动微调窗口/阈值。

实现思路：把帧转成 torch 张量后算逐帧平均亮度，交给 core.seam 算 gain/offset，
再只把“下一段的交付帧”乘上去；上一段和被引导的头帧不动（免得把参考画面改坏）。
"""

from __future__ import annotations

import hashlib
import json

import torch

from ..core import seam
from ..core.types import CATEGORY


class DirectorDeckSeamFixer:
    """把下一段的曝光/亮度对齐到上一段，减少段边界的跳变。"""

    CATEGORY = f"{CATEGORY}/后处理"
    FUNCTION = "fix"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "report")
    DESCRIPTION = ("接缝修正：用上一段尾部与下一段头部做线性曝光匹配，"
                   "只调整下一段交付帧；亮度差过大时判定硬切并跳过。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prev_images": ("IMAGE", {"tooltip": "上一段的帧（用其最后 window 帧）"}),
                "cur_images": ("IMAGE", {"tooltip": "下一段的帧（含衔接头）"}),
                "cur_head": ("INT", {"default": 22, "min": 0, "max": 56,
                                     "tooltip": "下一段开头有多少帧是衔接头（这些帧不参与修正）"}),
            },
            "optional": {
                "enabled": ("BOOLEAN", {"default": True}),
                "window": ("INT", {"default": seam.WINDOW_DEFAULT, "min": 2, "max": 48}),
                "max_add": ("FLOAT", {"default": seam.MAX_ADD_DEFAULT, "min": 0.0, "max": 0.5, "step": 0.01}),
                "gain_limit": ("FLOAT", {"default": seam.GAIN_LIMIT_DEFAULT, "min": 0.0, "max": 0.2, "step": 0.005}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return hashlib.sha1(json.dumps(kwargs, sort_keys=True, default=str)
                            .encode("utf-8")).hexdigest()

    @staticmethod
    def _means(images) -> list[float]:
        # 用 RGB 全通道均值当“亮度”的廉价近似；对曝光漂移已经够用。
        return [float(v) for v in images.detach().float().mean(dim=(1, 2, 3)).cpu().tolist()]

    def fix(self, prev_images, cur_images, cur_head, enabled=True,
            window=seam.WINDOW_DEFAULT, max_add=seam.MAX_ADD_DEFAULT,
            gain_limit=seam.GAIN_LIMIT_DEFAULT):
        if not enabled:
            return (cur_images, "接缝修正已关闭")
        plan = seam.exposure_plan(self._means(prev_images), self._means(cur_images),
                                  window=int(window), max_add=float(max_add),
                                  gain_limit=float(gain_limit))
        if plan.get("hard_cut"):
            return (cur_images, "判定为硬切，跳过修正：" + json.dumps(plan, ensure_ascii=False))
        if not plan.get("apply"):
            return (cur_images, "接缝误差很小，无需修正：" + json.dumps(plan, ensure_ascii=False))

        fixed = cur_images.clone()
        head = max(0, min(int(cur_head), fixed.shape[0]))
        tail = fixed[head:]
        if tail.shape[0] > 0:
            # new = gain * old + offset，并夹回 0~1 防止溢出。
            tail = tail * float(plan["gain"]) + float(plan["offset"])
            fixed[head:] = tail.clamp(0.0, 1.0)
        return (fixed, "已修正接缝：" + json.dumps(plan, ensure_ascii=False))
