"""DirectorDeck —— ComfyUI 短剧导演台节点库。

M0：仅暴露包结构与核心纯函数；节点从 M1 开始注册。
"""

from __future__ import annotations

import os

__version__ = "0.1.0"

# M1 起填充：
NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
WEB_DIRECTORY = "./web" if os.path.isdir(_WEB_DIR) else None

try:  # ComfyUI 加载时可见；单独 import 时静默
    print(f"[DirectorDeck] v{__version__} loaded (nodes: {len(NODE_CLASS_MAPPINGS)})")
except Exception:
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY", "__version__"]
