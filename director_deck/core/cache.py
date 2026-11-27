"""抽卡缓存的指纹计算（纯函数，可单测）。

“画面级秒复用”要解决的第一件事：**怎么判断两次生成是同一段**。
我们的做法是把所有会影响画面的输入拼成一个稳定 JSON（resolved 哈希、提示词、
种子、采样参数、引导来源、锁音信息……），再算 sha1。只要 fingerprint 一样，
就能直接拿上次缓存的 mp4/npz，不用再跑采样。

为什么把 `cache_schema` 也算进去？将来缓存格式升级时让旧缓存自动失效，避免读到
半旧半新的数据。
"""

from __future__ import annotations

import hashlib
import json

# 缓存格式版本：改了缓存文件结构/指纹组成就 +1，旧缓存自动失效。
# 0.2.5：锁音段的指纹加入“实际音频内容哈希”（TTS 每次生成可能不同）。
CACHE_SCHEMA = 2


def canonical_json(value) -> str:
    """稳定序列化（key 排序、紧凑分隔符），保证同样内容得到同样字符串。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=str)


def segment_fingerprint(payload: dict) -> str:
    """生成一段的缓存指纹（sha1，带 schema 版本）。"""
    data = dict(payload or {})
    data["cache_schema"] = CACHE_SCHEMA
    digest = hashlib.sha1(canonical_json(data).encode("utf-8")).hexdigest()
    return "sha1:" + digest


def cache_stem(fingerprint: str) -> str:
    """把 `sha1:xxxx` 变成文件名安全的 stem。"""
    return str(fingerprint).replace("sha1:", "").replace(":", "_")[:32] or "unknown"


def is_valid_fingerprint(fingerprint: str) -> bool:
    text = str(fingerprint or "")
    if not text.startswith("sha1:"):
        return False
    return len(text) == 45  # "sha1:" + 40 位 hex
