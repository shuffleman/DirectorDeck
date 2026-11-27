"""Breeze-TTS-2 可选适配层（DirectorDeck 不硬依赖它）。

为什么单独放一个 adapter：
- Breeze-TTS-2 是第三方节点包，装不装由用户决定；DirectorDeck 不应该 import 失败；
- 这里的做法是“运行时去已加载的节点映射表里找 Breeze 的节点类”，找到就调用，
  找不到就抛 DD-E050，提示装包。
- 只依赖它公开的节点方法（VoiceDesign.design），不碰内部权重/加载逻辑。

这段代码只在 ComfyUI 进程里跑（节点执行时），所以能找到 custom_nodes 的映射表。
"""

from __future__ import annotations

import sys
from typing import Any

from ..core.types import error

# 用哪个节点来“文字 + 音色描述 -> AUDIO”，VoiceDesign 不需要参考音频，最适合台词表。
VOICE_DESIGN_NODE = "BreezeTTS2VoiceDesign"

_mapping_cache: dict | None = None


def find_breeze_nodes() -> dict:
    """在已经加载的 ComfyUI 节点映射表里找 Breeze-TTS-2。"""
    global _mapping_cache
    if _mapping_cache is not None:
        return _mapping_cache
    for module in list(sys.modules.values()):
        mapping = getattr(module, "NODE_CLASS_MAPPINGS", None)
        if isinstance(mapping, dict) and VOICE_DESIGN_NODE in mapping:
            _mapping_cache = mapping
            return mapping
    raise error("DD-E050", "没找到 BreezeTTS2VoiceDesign 节点，请安装 ComfyUI-Breeze-TTS-2 并重启 ComfyUI")


def available() -> bool:
    """给节点/文档判断用：当前进程里 Breeze-TTS-2 能不能用。"""
    try:
        find_breeze_nodes()
        return True
    except Exception:
        return False


def voice_design(breeze_model: Any, *, text: str, instruction: str,
                 cfg_scale: float = 4.0, max_new_tokens: int = 1500,
                 temperature: float = 0.9, top_k: int = 50, top_p: float = 1.0,
                 repetition_penalty: float = 1.1, depth_temperature: float = 0.9,
                 depth_top_k: int = 50, depth_top_p: float = 1.0,
                 seed: int = 0) -> dict:
    """调 Breeze 的 VoiceDesign 生成一段 AUDIO（24kHz 单声道）。

    直接实例化它的节点类并调用 `design()`——这等价于你在画布上点一次
    “Breeze TTS 2 Voice Design”节点，参数一一对应。
    """
    node_class = find_breeze_nodes()[VOICE_DESIGN_NODE]
    node = node_class()
    result = node.design(
        breeze_model=breeze_model,
        text=text,
        instruction=instruction,
        cfg_scale=float(cfg_scale),
        max_new_tokens=int(max_new_tokens),
        temperature=float(temperature),
        top_k=int(top_k),
        top_p=float(top_p),
        repetition_penalty=float(repetition_penalty),
        depth_temperature=float(depth_temperature),
        depth_top_k=int(depth_top_k),
        depth_top_p=float(depth_top_p),
        seed=int(seed),
    )
    # ComfyUI 节点的 FUNCTION 约定返回 tuple；这里只要 AUDIO 本身。
    if isinstance(result, tuple):
        return result[0]
    return result
