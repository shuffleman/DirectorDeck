"""DirectorDeck — ComfyUI 短剧导演台节点库。

给 ComfyUI 用的入口在仓库根目录的 __init__.py，这里负责：
- 版本号；
- 汇总节点映射（ComfyUI 靠 NODE_CLASS_MAPPINGS 认节点）；
- 暴露 WEB_DIRECTORY（M4 前端扩展用）；
- 在非 ComfyUI 环境（比如跑单测）里优雅降级，别因为 import 不到 comfy 就炸。

M1 已实现：模型加载器 / 全局配置 / 资产管理器 / 剧本加载器 / 段级剧本 / 视频生成器（单段）。
"""

from __future__ import annotations

import os
import traceback

__version__ = "0.1.0"

NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

try:
    # 注意：导入节点层会连带 import ComfyUI 的模块（适配层）；
    # 在纯 Python 单测环境里这会失败，所以用 try 包住并降级。
    from .nodes import NODE_CLASS_MAPPINGS as _classes
    from .nodes import NODE_DISPLAY_NAME_MAPPINGS as _names

    NODE_CLASS_MAPPINGS.update(_classes)
    NODE_DISPLAY_NAME_MAPPINGS.update(_names)
except Exception:  # ComfyUI 未就绪（例如纯 Python 单测环境）时允许只有 core
    print("[DirectorDeck] 节点层未加载（非 ComfyUI 环境或依赖缺失）：")
    traceback.print_exc()

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
WEB_DIRECTORY = "./web" if os.path.isdir(_WEB_DIR) else None

try:
    print(f"[DirectorDeck] v{__version__} loaded (nodes: {len(NODE_CLASS_MAPPINGS)})")
except Exception:
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY", "__version__"]
