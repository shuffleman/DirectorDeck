"""OpenAI 兼容的 LLM 客户端（本地/远程都走同一套协议）。

为什么要自己写一个：DirectorDeck 不想依赖某个特定 LLM 节点包。
只要对方提供 `POST /v1/chat/completions`，就能用：

- 本地：LM Studio（默认 127.0.0.1:1234/v1）、Ollama（127.0.0.1:11434/v1）、vLLM 等；
- 远程：OpenAI、DeepSeek、通义、Moonshot、各种中转站（填 base_url 即可）。

API Key 只从**环境变量**读（节点上填变量名，不把密钥写进工作流文件）。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..core.types import error

DEFAULT_BASE_URLS = {
    "local": "http://127.0.0.1:1234/v1",
    "remote": "https://api.openai.com/v1",
}


def resolve_base_url(provider: str, base_url: str = "") -> str:
    """provider=local/remote + 用户填的 base_url（空则用默认）。"""
    raw = (base_url or "").strip()
    if not raw:
        raw = DEFAULT_BASE_URLS.get(provider, DEFAULT_BASE_URLS["local"])
    raw = raw.rstrip("/")
    if raw.endswith("/chat/completions"):
        raw = raw[: -len("/chat/completions")]
    return raw


def _api_key(api_key_env: str) -> str:
    name = (api_key_env or "").strip()
    return os.environ.get(name, "") if name else ""


def _request(url: str, payload: dict | None, api_key: str, timeout: int) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise error("DD-E060", f"LLM 接口返回 HTTP {exc.code}：{body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise error("DD-E060", f"连不上 LLM 接口 {url}：{exc.reason}") from exc
    except Exception as exc:  # JSON 解析失败等
        raise error("DD-E060", f"LLM 接口请求失败：{exc}") from exc


def list_models(provider: str, base_url: str = "", api_key_env: str = "OPENAI_API_KEY",
                timeout: int = 60) -> list[str]:
    """拉取 /models 列表（本地模型用来实现“model 留空自动选第一个”）。"""
    url = resolve_base_url(provider, base_url) + "/models"
    data = _request(url, None, _api_key(api_key_env), timeout)
    models = []
    for item in data.get("data") or data.get("models") or []:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name")
        else:
            name = item
        if name:
            models.append(str(name))
    return models


def chat(provider: str, base_url: str, model: str, messages: list[dict],
         api_key_env: str = "OPENAI_API_KEY", temperature: float = 0.7,
         max_tokens: int = 4096, timeout: int = 180) -> dict:
    """调用 chat/completions，返回 {text, model, usage, raw}。"""
    base = resolve_base_url(provider, base_url)
    key = _api_key(api_key_env)
    if provider == "remote" and not key:
        raise error("DD-E060", f"远程模型需要 API Key：请设置环境变量 {api_key_env or 'OPENAI_API_KEY'}")
    chosen = (model or "").strip()
    if not chosen:
        models = list_models(provider, base_url, api_key_env, timeout)
        if not models:
            raise error("DD-E060", "model 留空且接口没返回任何模型，请手动填 model")
        chosen = models[0]
    payload = {"model": chosen, "messages": messages,
               "temperature": float(temperature),
               "max_tokens": int(max_tokens), "stream": False}
    data = _request(base + "/chat/completions", payload, key, timeout)
    try:
        message = data["choices"][0]["message"]
        content = message.get("content") or message.get("reasoning_content") or ""
    except Exception as exc:
        raise error("DD-E060", f"LLM 返回格式不认识：{str(data)[:300]}") from exc
    return {"text": content, "model": chosen,
            "usage": data.get("usage") or {}, "raw": data}
