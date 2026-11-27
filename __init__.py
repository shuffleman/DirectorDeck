"""DirectorDeck 的 ComfyUI 入口。

ComfyUI 加载 custom_nodes 时，会把“插件目录本身”当成 Python 包来 import，
所以这个目录根部必须有 __init__.py；真正的实现都在 director_deck/ 子包里。

这里只做一件事：把子包里的节点映射、显示名、前端目录暴露出去。
"""

from __future__ import annotations

import os

try:
    from .director_deck import (
        NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS,
        __version__,
    )

    # 前端面板放在 director_deck/web/（这样 pip 安装也能把它带进包里）。
    # ComfyUI 会把它映射到 /extensions/DirectorDeck/directordeck.js。
    _web = os.path.join(os.path.dirname(os.path.abspath(__file__)), "director_deck", "web")
    WEB_DIRECTORY = "./director_deck/web" if os.path.isdir(_web) else None
except Exception:  # 加载失败时也要让 ComfyUI 继续启动，同时把原因打出来
    import traceback

    print("[DirectorDeck] 入口加载失败：")
    traceback.print_exc()
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}
    WEB_DIRECTORY = None
    __version__ = "0.1.0"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
    "__version__",
]
