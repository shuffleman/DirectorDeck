"""DirectorDeck · 后端路由（M4）。

只做三件小事，给前端面板用：
- GET /directordeck/segments  ：最近的段元数据（从 output/DirectorDeck/segments 读）
- GET /directordeck/manifests ：最近的成片清单
- GET /directordeck/health    ：面板自检用

为什么放后端而不是前端直接读文件？浏览器没有文件系统权限，
而 ComfyUI 的 /view 只能拿媒体文件；元数据 JSON 走一个小接口最省事。
"""

from __future__ import annotations

import json
import os
import time

try:  # 只有真的在 ComfyUI 进程里才 import 得到
    from aiohttp import web
    from server import PromptServer
except Exception:  # 单测/纯 Python 环境下允许 import 失败
    web = None
    PromptServer = None


def _output_root() -> str:
    """output 目录（懒 import folder_paths，避免非 ComfyUI 环境报错）。"""
    import folder_paths
    return os.path.join(folder_paths.get_output_directory(), "DirectorDeck")


def _read_json_dir(path: str, limit: int = 50) -> list[dict]:
    """读一个目录下所有 JSON，按修改时间倒序；坏文件直接跳过。"""
    items = []
    if not os.path.isdir(path):
        return items
    files = [os.path.join(path, name) for name in os.listdir(path)
             if name.lower().endswith(".json")]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for file_path in files[:limit]:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data["_file"] = os.path.basename(file_path)
            data["_mtime"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(os.path.getmtime(file_path)))
            items.append(data)
        except Exception:
            continue
    return items


def setup_routes() -> None:
    """把路由挂到 ComfyUI 的 aiohttp 上；不可用时静默跳过。"""
    if web is None or PromptServer is None:
        return
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return
    routes = instance.routes

    @routes.get("/directordeck/health")
    async def health(request):
        return web.json_response({"ok": True, "time": time.time(),
                                  "version": "0.2.3"})

    @routes.get("/directordeck/segments")
    async def segments(request):
        try:
            limit = int(request.query.get("limit", 50))
        except Exception:
            limit = 50
        root = _output_root()
        items = _read_json_dir(os.path.join(root, "segments"), limit=limit)
        return web.json_response({"ok": True, "count": len(items), "segments": items})

    @routes.get("/directordeck/manifests")
    async def manifests(request):
        try:
            limit = int(request.query.get("limit", 20))
        except Exception:
            limit = 20
        root = _output_root()
        items = _read_json_dir(os.path.join(root, "manifests"), limit=limit)
        return web.json_response({"ok": True, "count": len(items), "manifests": items})
