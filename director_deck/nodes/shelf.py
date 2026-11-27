"""DirectorDeck · 资产管理器（M1）：最多 9 张参考图，槽位固定。

为什么槽位固定？
提示词里写 `@图片3`，它就代表第 3 槽；只有槽位稳定，才能做“段 2 只换第 3 张、
其他沿用段 1”的按槽覆盖。

M1 通过 IMAGE 输入收图（LoadImage 之类）；M4 会接前端素材画布，
到那时候 name/path 才会变成真实文件名。
"""

from __future__ import annotations

import hashlib
import json

from ..core import assets as assets_lib
from ..core.types import CATEGORY, TYPE_ASSETS


class DirectorDeckAssetShelf:
    """把 9 张图收进一个素材包，输出 DIRECTOR_ASSETS。"""

    CATEGORY = f"{CATEGORY}/素材"
    FUNCTION = "collect"
    RETURN_TYPES = (TYPE_ASSETS,)
    RETURN_NAMES = ("assets",)
    DESCRIPTION = ("最多 9 张参考图，槽位固定：第 N 槽 = @图片N。"
                   "资产管理器可被每段单独连接（覆盖）或沿用上一段（policy=inherit）。")

    @classmethod
    def INPUT_TYPES(cls):
        # 9 个可选 IMAGE 输入：没接的槽就是空槽，不算错误。
        optional = {}
        for index in range(1, assets_lib.ASSET_SLOT_COUNT + 1):
            optional[f"image_{index}"] = ("IMAGE", {
                "tooltip": f"第 {index} 槽素材（提示词里用 @图片{index} 引用）"})
        return {"required": {}, "optional": optional}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 只看“哪几个槽接了图”；图片内容变了通常也意味着上游 LoadImage 变了，
        # 那会由上游的缓存键带下来，这里不需要把整个张量写进哈希。
        return hashlib.sha1(json.dumps(
            {k: (None if v is None else id(v)) for k, v in kwargs.items()},
            sort_keys=True).encode("utf-8")).hexdigest()

    def collect(self, **kwargs):
        data = assets_lib.empty_assets()
        for index in range(1, assets_lib.ASSET_SLOT_COUNT + 1):
            image = kwargs.get(f"image_{index}")
            if image is None:
                continue
            slot = data["slots"][index - 1]
            # M1 没有真实文件名，先用占位 path；M4 前端会填真实文件名。
            slot["path"] = f"slot_{index}"
            slot["name"] = f"图片{index}"
            slot["role"] = "reference"
            data["images"][index - 1] = image
        return (data,)
