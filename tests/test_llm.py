"""OpenAI 兼容 LLM 客户端单测（起一个本地假服务，不联网）。"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from director_deck.adapters import llm


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            self._send(200, {"data": [{"id": "fake-model"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        if request.get("model") == "bad-model":
            self._send(500, {"error": "boom"})
            return
        self._send(200, {"model": request.get("model"), "choices": [
            {"message": {"role": "assistant", "content": "你好"}}],
            "usage": {"total_tokens": 3}})

    def log_message(self, *args):
        pass


class LlmTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_resolve_base_url(self):
        self.assertEqual(llm.resolve_base_url("local"), "http://127.0.0.1:1234/v1")
        self.assertEqual(llm.resolve_base_url("local", self.base), self.base)
        self.assertEqual(llm.resolve_base_url("local", self.base + "/chat/completions"), self.base)

    def test_list_models(self):
        self.assertEqual(llm.list_models("local", self.base, "NOPE_KEY"), ["fake-model"])

    def test_chat_auto_model(self):
        result = llm.chat("local", self.base, "", [{"role": "user", "content": "hi"}],
                          api_key_env="NOPE_KEY")
        self.assertEqual(result["text"], "你好")
        self.assertEqual(result["model"], "fake-model")
        self.assertEqual(result["usage"]["total_tokens"], 3)

    def test_chat_http_error(self):
        with self.assertRaises(Exception) as ctx:
            llm.chat("local", self.base, "bad-model", [{"role": "user", "content": "hi"}])
        self.assertIn("DD-E060", str(getattr(ctx.exception, "code", "")) + str(ctx.exception))

    def test_remote_requires_key(self):
        with self.assertRaises(Exception) as ctx:
            llm.chat("remote", self.base, "fake-model", [], api_key_env="DEFINITELY_MISSING_KEY")
        self.assertIn("API Key", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
