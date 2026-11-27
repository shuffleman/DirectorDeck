"""段运行期存储（进程内存，按 store_key 存取）。

为什么需要它？
链式生成时，下一段要拿到上一段的“画面尾巴/音轨尾巴”做 AddGuide；
但 DIRECTOR_SEGMENT 这个 socket 必须是可 JSON 序列化的（不然 ComfyUI 写 history 会崩），
不能把 tensors 塞进去。所以：
- segment 只带一个 store_key 字符串；
- 真正的张量（尾帧/音轨/素材张量）放在这个进程内仓库里，用 store_key 取。

注意：这是“内存仓库”，ComfyUI 重启后旧 store_key 就失效了——此时会明确报错，
让用户重跑上一段，而不是悄悄生成一段接不上的视频。
"""

from __future__ import annotations

import threading
from collections import OrderedDict

# 最多留 24 段；一段只存尾帧+尾音+素材，体量很小（几十 MB 级）。
_MAX_ENTRIES = 24
_STORE: "OrderedDict[str, dict]" = OrderedDict()
_LOCK = threading.Lock()


def put(key: str, value: dict) -> None:
    """存一段运行期数据（超出容量就丢最旧的，避免吃内存）。"""
    if not key:
        return
    with _LOCK:
        _STORE[key] = value
        _STORE.move_to_end(key)
        while len(_STORE) > _MAX_ENTRIES:
            _STORE.popitem(last=False)


def get(key: str) -> dict | None:
    """取一段运行期数据；没有就返回 None（调用方负责报错提示重跑）。"""
    if not key:
        return None
    with _LOCK:
        value = _STORE.get(key)
        if value is not None:
            _STORE.move_to_end(key)
        return value


def drop(key: str) -> None:
    """手动清掉一段（抽卡/重跑时用）。"""
    with _LOCK:
        _STORE.pop(key, None)


def clear() -> None:
    """清空整个仓库（测试/长会话时用）。"""
    with _LOCK:
        _STORE.clear()


def size() -> int:
    with _LOCK:
        return len(_STORE)
