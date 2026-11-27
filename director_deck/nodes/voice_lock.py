"""DirectorDeck · 数字人锁音器（M3）。

它干的事：
1. 把“角色 -> 音频槽 + 时间轴起点”的映射整理成 DIRECTOR_CAST；
2. 把真实音频张量塞进 cast（运行期数据，不进 JSON）；
3. 生成器拿到 cast 后：按时间轴切出本段音轨 -> 编码 -> 锁进 AV latent（noise_mask=0），
   于是模型只生成画面，声音完全用你给的。

注意：这才是真锁音。AddGuide(audio) 只是“条件锚定”，声音还是会被重采样。
"""

from __future__ import annotations

import hashlib
import json
import re

from ..core.types import CATEGORY, TYPE_CAST

# 每行一个角色：“女主: 1, 0.0” = 角色名、音频槽号（audio_1 就是 1）、时间轴起点秒。
ROLE_RE = re.compile(
    r"^\s*(?P<name>[^:：=]+?)\s*[:：=]\s*(?P<slot>\d+)\s*(?:[,，]\s*(?P<start>[0-9.]+))?\s*$")

DEFAULT_ROLES = "女主: 1, 0.0"


class DirectorDeckVoiceLock:
    """数字人锁音器：角色名 + 音频槽 + 时间轴起点 -> DIRECTOR_CAST。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "build"
    RETURN_TYPES = (TYPE_CAST, "STRING")
    RETURN_NAMES = ("cast", "summary")
    DESCRIPTION = ("把角色和音频对应起来（真锁音）：生成时音频流会被固定进 AV latent，"
                   "模型只生成画面。每行“角色名: 音频槽号, 起始秒”。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "roles": ("STRING", {"multiline": True, "default": DEFAULT_ROLES,
                                     "tooltip": "每行“角色名: 音频槽号, 时间轴起点秒”"}),
                "lock_audio": ("BOOLEAN", {"default": True,
                                           "tooltip": "开=真锁音（noise_mask=0）；关=只记录角色表"}),
            },
            "optional": {
                "audio_1": ("AUDIO", {"tooltip": "第 1 条音频（roles 里写 1 对应它）"}),
                "audio_2": ("AUDIO", {"tooltip": "第 2 条音频"}),
                "audio_3": ("AUDIO", {"tooltip": "第 3 条音频"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 文本/布尔自不必说；音频对象变了也必须重算（不能用 id 之外的稳定哈希，
        # 因为波形张量没法序列化；id 在同一个进程里是稳定的，够用）。
        key = {
            "roles": kwargs.get("roles"),
            "lock_audio": kwargs.get("lock_audio"),
            "audio_ids": [id(kwargs.get(f"audio_{i}")) for i in (1, 2, 3)],
        }
        return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_roles(text: str) -> list[dict]:
        """解析角色行；格式错的直接报清楚，别静默跳过。"""
        roles = []
        for line_no, line in enumerate((text or "").splitlines(), start=1):
            if not line.strip() or line.strip().startswith("#"):
                continue
            match = ROLE_RE.match(line)
            if not match:
                raise ValueError(f"第 {line_no} 行格式不对：{line!r}（应形如“女主: 1, 0.0”）")
            name = match.group("name").strip()
            roles.append({
                "id": name,
                "name": name,
                "slot": int(match.group("slot")),
                "start": float(match.group("start") or 0.0),
            })
        return roles

    def build(self, roles, lock_audio=True, audio_1=None, audio_2=None, audio_3=None):
        parsed = self._parse_roles(roles)
        audio_inputs = {1: audio_1, 2: audio_2, 3: audio_3}
        out_roles = []
        for role in parsed:
            audio = audio_inputs.get(role["slot"])
            if lock_audio and audio is None:
                raise ValueError(f"角色“{role['name']}”指定了音频槽 {role['slot']}，但该槽没接音频")
            voice = {"kind": "audio" if audio is not None else "none",
                     "slot": role["slot"]}
            entry = {
                "id": role["id"],
                "name": role["name"],
                "start": role["start"],
                "voice": voice,
            }
            if audio is not None:
                # audio_data 是运行期张量（不进 JSON），生成器靠它切音轨。
                entry["audio_data"] = audio
            out_roles.append(entry)
        cast = {
            "schema": "DIRECTOR_CAST@1",
            "lock_audio": bool(lock_audio),
            "roles": out_roles,
        }
        desc = " / ".join(
            f"{r['name']}(槽{r['voice']['slot']}@{r['start']:.2f}s)" for r in out_roles)
        summary = (f"{len(out_roles)} 个角色，锁音={'开' if lock_audio else '关'}：{desc}"
                   if out_roles else "没有角色映射")
        return (cast, summary)
