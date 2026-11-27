"""DirectorDeck · 数字人锁音器（M3/M5.3）。

它干的事：
1. 把“角色 -> 音频槽 + 时间轴起点 + 增益 + 优先级”的映射整理成 DIRECTOR_CAST；
2. 把真实音频张量塞进 cast（运行期数据，不进 JSON）；
3. 生成器拿到 cast 后：按时间轴切出本段音轨 -> 自动 ducking/混音 -> 编码 -> 锁进 AV latent
   （noise_mask=0），于是模型只生成画面，声音完全用你给的。

角色行格式（后两个参数可省略）：
    女主: 1, 0.0            # 音频槽 1，时间轴 0 秒开始
    旁白: 2, 3.0, -3, 2     # 槽 2，3 秒开始，音量 -3dB，优先级 2

混音规则（mix_mode）：
- auto_duck：同一帧里谁最响谁不被压，其他同时说话的角色降 duck_db（默认 -8dB）；
- priority：按角色优先级决定谁不被压（旁白/主角可以设高一点）；
- sum：只叠加，不做自动压低（适合本来就分轨混好的素材）。
"""

from __future__ import annotations

import hashlib
import json
import re

from ..core import audio as audio_math
from ..core.types import CATEGORY, TYPE_CAST

# 每行一个角色：“名字: 音频槽, 起始秒, 增益dB, 优先级”，后两个可省略。
ROLE_RE = re.compile(
    r"^\s*(?P<name>[^:：=]+?)\s*[:：=]\s*(?P<slot>\d+)"
    r"\s*(?:[,，]\s*(?P<start>-?[0-9.]+))?"
    r"\s*(?:[,，]\s*(?P<gain>-?[0-9.]+))?"
    r"\s*(?:[,，]\s*(?P<priority>-?\d+))?\s*$")

DEFAULT_ROLES = "女主: 1, 0.0"


class DirectorDeckVoiceLock:
    """数字人锁音器：角色名 + 音频槽 + 时间轴起点（+ 增益/优先级）-> DIRECTOR_CAST。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "build"
    RETURN_TYPES = (TYPE_CAST, "STRING")
    RETURN_NAMES = ("cast", "summary")
    DESCRIPTION = ("把角色和音频对应起来（真锁音）：生成时音频流会被固定进 AV latent，"
                   "模型只生成画面。每行“角色名: 音频槽号, 起始秒, 增益dB, 优先级”。"
                   "多角色重叠时自动 ducking，避免两个声音互相盖住。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "roles": ("STRING", {"multiline": True, "default": DEFAULT_ROLES,
                                     "tooltip": "每行“角色名: 音频槽号, 起始秒, 增益dB, 优先级”（后两个可省略）"}),
                "lock_audio": ("BOOLEAN", {"default": True,
                                           "tooltip": "开=真锁音（noise_mask=0）；关=只记录角色表"}),
                "mix_mode": (list(audio_math.MIX_MODES), {"default": "auto_duck",
                                                         "tooltip": "auto_duck=谁响谁不被压 / priority=按优先级 / sum=只叠加"}),
                "duck_db": ("FLOAT", {"default": audio_math.DUCK_DB_DEFAULT,
                                      "min": -24.0, "max": 0.0, "step": 0.5,
                                      "tooltip": "同时说话时把其他角色压低多少 dB"}),
                "attack_ms": ("INT", {"default": int(audio_math.ATTACK_MS_DEFAULT),
                                      "min": 5, "max": 500,
                                      "tooltip": "压下去有多快（毫秒）"}),
                "release_ms": ("INT", {"default": int(audio_math.RELEASE_MS_DEFAULT),
                                       "min": 20, "max": 2000,
                                       "tooltip": "恢复有多快（毫秒）"}),
            },
            "optional": {
                "audio_1": ("AUDIO", {"tooltip": "第 1 条音频（roles 里写 1 对应它）"}),
                "audio_2": ("AUDIO", {"tooltip": "第 2 条音频"}),
                "audio_3": ("AUDIO", {"tooltip": "第 3 条音频"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 文本/布尔/混音参数变了都必须重算；音频对象用 id 判断（同一进程内稳定）。
        key = {
            "roles": kwargs.get("roles"),
            "lock_audio": kwargs.get("lock_audio"),
            "mix_mode": kwargs.get("mix_mode"),
            "duck_db": kwargs.get("duck_db"),
            "attack_ms": kwargs.get("attack_ms"),
            "release_ms": kwargs.get("release_ms"),
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
                raise ValueError(
                    f"第 {line_no} 行格式不对：{line!r}"
                    "（应形如“女主: 1, 0.0”或“旁白: 2, 3.0, -3, 2”）")
            name = match.group("name").strip()
            roles.append({
                "id": name,
                "name": name,
                "slot": int(match.group("slot")),
                "start": float(match.group("start") or 0.0),
                "gain_db": float(match.group("gain") or 0.0),
                "priority": int(match.group("priority") or 0),
            })
        return roles

    def build(self, roles, lock_audio=True, mix_mode="auto_duck",
              duck_db=audio_math.DUCK_DB_DEFAULT,
              attack_ms=int(audio_math.ATTACK_MS_DEFAULT),
              release_ms=int(audio_math.RELEASE_MS_DEFAULT),
              audio_1=None, audio_2=None, audio_3=None):
        if mix_mode not in audio_math.MIX_MODES:
            raise ValueError(f"未知混音模式 {mix_mode!r}（可选 {audio_math.MIX_MODES}）")
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
                "gain_db": role["gain_db"],
                "priority": role["priority"],
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
            "mix": {
                "mode": str(mix_mode),
                "duck_db": float(duck_db),
                "attack_ms": int(attack_ms),
                "release_ms": int(release_ms),
            },
        }
        desc = " / ".join(
            f"{r['name']}(槽{r['voice']['slot']}@{r['start']:.2f}s"
            f"{', %+.1fdB' % r['gain_db'] if abs(r['gain_db']) > 1e-6 else ''}"
            f"{', P%d' % r['priority'] if r['priority'] else ''})"
            for r in out_roles)
        summary = (f"{len(out_roles)} 个角色，锁音={'开' if lock_audio else '关'}，"
                   f"混音={mix_mode}({duck_db:+.1f}dB, {attack_ms}/{release_ms}ms)：{desc}"
                   if out_roles else "没有角色映射")
        return (cast, summary)
