#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 mock LLM（OpenAI 兼容），用于没有真实模型时联调 DirectorDeck 编剧台。

启动：
    python tools/mock_llm.py --port 18081

它实现两个接口：
    GET  /v1/models              -> {"data":[{"id":"mock-screenwriter"}]}
    POST /v1/chat/completions    -> 返回一段固定剧本（或 MOCK_RESPONSE_FILE 里的 JSON 文本）

然后在“编剧台”里：
    provider = 本地 OpenAI 兼容
    base_url = http://127.0.0.1:18081/v1
    model    = mock-screenwriter
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_SCREENPLAY = {
    "title": "雨夜重逢",
    "characters": [
        {"id": "S1", "name": "女主", "image_slot": 1, "audio_slot": 1,
         "voice": "二十岁女性，声音清亮温柔，语速偏慢"},
        {"id": "S2", "name": "男主", "image_slot": 2, "audio_slot": 2,
         "voice": "二十多岁男性，声音低沉沉稳，语速正常"},
    ],
    "segments": [
        {"seconds": 5, "scene": "雨夜老宅门口",
         "actions": "女主撑着伞站在台阶下，男主从门内走出，雨水打在青石板上",
         "image_refs": [1, 2],
         "dialogue": [
             {"speaker": "S1", "text": "你终于回来了。", "at": 0.8},
             {"speaker": "S2", "text": "这十年，我一直在找你。", "at": 2.6},
         ]}
    ],
}

V6_TEXT = """【第1段｜5秒】
integrated_multimodal_description: [Shot 1] 雨夜老宅门口，女主撑伞站在台阶下，男主从门内走出。<Picture 1><Picture 2>
0.0～0.8秒：女主抬头看向门内。
0.8～2.2秒：(S1) says: <d>[Chinese]你终于回来了。</d> 女主轻声说，男主停下脚步。
2.2～4.2秒：(S2) says: <d>[Chinese]这十年，我一直在找你。</d> 男主向前一步。
4.2～5.0秒：两人在雨中对视。

overall_soundscape: 雨声持续，脚踩积水声。
non_diegetic_music: 低沉弦乐渐入。
"""


class Handler(BaseHTTPRequestHandler):
    response_file = ""

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._send(200, {"data": [{"id": "mock-screenwriter"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send(400, {"error": "invalid json"})
            return
        messages = request.get("messages") or []
        prompt = "\n".join(str(m.get("content") or "") for m in messages)
        if "H3 V6" in prompt or "【输出契约：H3" in prompt:
            content = V6_TEXT
        elif self.response_file and os.path.isfile(self.response_file):
            content = open(self.response_file, "r", encoding="utf-8").read()
        else:
            content = json.dumps(DEFAULT_SCREENPLAY, ensure_ascii=False, indent=2)
        self._send(200, {
            "id": "mock-completion",
            "model": "mock-screenwriter",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(content) // 4,
                      "total_tokens": (len(prompt) + len(content)) // 4},
        })

    def log_message(self, fmt, *args):  # 安静一点
        print("[mock-llm]", fmt % args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--response-file", default=os.environ.get("MOCK_RESPONSE_FILE", ""))
    args = parser.parse_args()
    Handler.response_file = args.response_file
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[mock-llm] OpenAI-compatible mock on http://127.0.0.1:{args.port}/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
