"""把示例工作流 POST 给 ComfyUI，等它跑完并把产物拉回本地。

用途：M1 真机验收。节点加载需要 ComfyUI 重启，所以这里用“独立实例 8189 + 示例 JSON”
的方式跑，不打扰用户正在用的 8188。

用法：
    python tools/run_example.py examples/m1_single_segment_api.json
可选参数：--server http://127.0.0.1:8189 --timeout 1800
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DIR = os.path.join(REPO, "runs", "m1_server")


def http_json(url: str, payload: dict | None = None, timeout: int = 60):
    """极简 HTTP JSON：GET 用 urllib，POST 用 JSON body。临时脚本不引第三方库。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", "replace")
    return json.loads(body) if body else {}


def wait_done(server: str, prompt_id: str, timeout: float) -> dict:
    """轮询 /history，直到这次 prompt 完成（或超时）。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        time.sleep(5)
        history = http_json(f"{server}/history/{prompt_id}", timeout=30)
        record = history.get(prompt_id)
        if not record:
            # 还没进 history：看看是排队还是正在跑
            queue = http_json(f"{server}/queue", timeout=15)
            running = len(queue.get("queue_running") or [])
            pending = len(queue.get("queue_pending") or [])
            print(f"[run] 等待中… running={running} pending={pending}", flush=True)
            continue
        status = record.get("status", {})
        if status.get("status_str") == "error" or status.get("completed") is False:
            return record
        if status.get("completed") is True:
            return record
        last = record
    raise TimeoutError(f"等待 {timeout}s 仍未完成（prompt_id={prompt_id}）")


def download_outputs(server: str, record: dict) -> list[str]:
    """把输出节点 generated 的视频/图片拉到 runs/m1_server/。"""
    saved: list[str] = []
    for node_id, item in (record.get("outputs") or {}).items():
        for key in ("images", "gifs", "videos"):
            for file in item.get(key) or []:
                filename = file.get("filename")
                if not filename:
                    continue
                query = urllib.parse.urlencode({
                    "filename": filename,
                    "subfolder": file.get("subfolder", ""),
                    "type": file.get("type", "output"),
                })
                url = f"{server}/view?{query}"
                target = os.path.join(RUN_DIR, os.path.basename(filename))
                try:
                    with urllib.request.urlopen(url, timeout=120) as resp:
                        with open(target, "wb") as fh:
                            fh.write(resp.read())
                    saved.append(target)
                    print(f"[run] 已下载 {target}", flush=True)
                except Exception as exc:  # 某个文件拉失败不影响整体结果
                    print(f"[run] 下载失败 {filename}: {exc}", flush=True)
    return saved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("example", help="示例工作流 JSON 路径")
    parser.add_argument("--server", default="http://127.0.0.1:8189")
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()

    os.makedirs(RUN_DIR, exist_ok=True)
    with open(args.example, "r", encoding="utf-8") as fh:
        graph = json.load(fh)
    print(f"[run] 提交示例：{args.example}（节点 {len(graph)} 个）", flush=True)

    response = http_json(f"{args.server}/prompt",
                         {"prompt": graph, "client_id": "directordeck-m1"}, timeout=60)
    if response.get("node_errors"):
        print("[run] 校验失败 node_errors:", json.dumps(response["node_errors"],
                                                        ensure_ascii=False, indent=2), flush=True)
        with open(os.path.join(RUN_DIR, "node_errors.json"), "w", encoding="utf-8") as fh:
            json.dump(response, fh, ensure_ascii=False, indent=2)
        return 2
    prompt_id = response.get("prompt_id")
    print(f"[run] prompt_id={prompt_id}，开始等待（模型加载+采样，约 5 分钟）…", flush=True)

    record = wait_done(args.server, prompt_id, args.timeout)
    with open(os.path.join(RUN_DIR, "history.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2, default=str)
    status = record.get("status", {})
    print("[run] status:", json.dumps(status, ensure_ascii=False)[:800], flush=True)
    if status.get("status_str") == "error":
        print("[run] 失败，详情见 history.json", flush=True)
        return 3

    saved = download_outputs(args.server, record)
    segments = {}
    for node_id, item in (record.get("outputs") or {}).items():
        # 我们的 Take 节点会把 DIRECTOR_SEGMENT 塞在 ui 里吗？没有——它是 socket 输出，
        # 这里只取文件产物；segment 元数据由节点自己 print，M2 会落盘。
        if item.get("text"):
            segments[node_id] = item["text"]
    summary = {"prompt_id": prompt_id, "status": status.get("status_str"),
               "saved": saved, "texts": segments}
    with open(os.path.join(RUN_DIR, "run_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print("[run] DONE:", json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
