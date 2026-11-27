"""DirectorDeck · TTS 台词表（一键多角色配音 -> CAST）。

它解决的问题：以前要在画布上手摆 N 个 Breeze TTS 节点、再一个个接进锁音器；
现在只写一张“台词表”，节点自动：
1. 按行解析 `角色 @起始秒 | 音色描述 | 台词`；
2. 每个角色复用同一音色描述，逐条调 Breeze-TTS-2 的 VoiceDesign 生成 AUDIO；
3. 把同一角色的多条台词按起始秒摆到同一条音轨上；
4. 输出可直接喂给视频生成器的 CAST（角色名/起点/优先级/混音规则全带好），
   以及 3 路可试听/保存的 AUDIO。

台词表格式（每行一条台词，`|` 分隔三列）：
    女主 @0.0 | 一位年轻女性，声音清澈温柔，语速偏慢。 | 你好，我是这部剧的女主角。
    男主 @1.2 | 一位年轻男性，声音低沉沉稳，语气干练。 | 收到，我去检查船桨，五分钟以后开拍。

注意：
- 角色名相同 = 同一角色，会共用同一条音轨；起始秒可以各不相同。
- 优先级按“第一次出现的顺序”给：越靠前的角色优先级越高（ducking 时不容易被压）。
- 需要装 ComfyUI-Breeze-TTS-2 节点包；没装会在执行时报 DD-E050。
"""

from __future__ import annotations

import hashlib
import json
import re

import torch

from ..adapters import breeze_tts
from ..core import audio as audio_math
from ..core.types import CATEGORY, TYPE_CAST, error

# 每行：角色 @起始秒 | 音色描述 | 台词
LINE_RE = re.compile(
    r"^\s*(?P<role>[^@|]+?)\s*@\s*(?P<start>-?[0-9.]+)\s*"
    r"\|\s*(?P<instruction>[^|]*)\|\s*(?P<text>.+?)\s*$")

DEFAULT_LINES = (
    "女主 @0.0 | 一位年轻女性，声音清澈温柔，语速偏慢，情绪平静。 | 你好，我是这部剧的女主角。\n"
    "男主 @1.2 | 一位年轻男性，声音低沉沉稳，语气干练。 | 收到，我去检查船桨，五分钟以后开拍。"
)


class DirectorDeckTTSBooth:
    """台词表 -> 多角色 TTS -> CAST（可直接接视频生成器锁音）。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "build"
    RETURN_TYPES = (TYPE_CAST, "AUDIO", "AUDIO", "AUDIO", "STRING")
    RETURN_NAMES = ("cast", "audio_1", "audio_2", "audio_3", "summary")
    DESCRIPTION = (
        "一张台词表搞定多角色配音：每行“角色 @起始秒 | 音色描述 | 台词”，"
        "自动调 Breeze-TTS-2 生成并拼接成角色音轨，输出可直接锁音的 CAST。"
        "角色顺序即 ducking 优先级（越靠前越高）。需要安装 ComfyUI-Breeze-TTS-2。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "breeze_model": ("BREEZE_TTS2_MODEL", {
                    "tooltip": "接 Breeze TTS 2 Load Model 的输出"}),
                "lines": ("STRING", {"multiline": True, "default": DEFAULT_LINES,
                                     "tooltip": "每行：角色 @起始秒 | 音色描述 | 台词"}),
                "mix_mode": (list(audio_math.MIX_MODES),
                             {"default": "auto_duck",
                              "tooltip": "auto_duck=谁响谁不被压 / priority=按角色顺序 / sum=只叠加"}),
                "duck_db": ("FLOAT", {"default": audio_math.DUCK_DB_DEFAULT,
                                      "min": -24.0, "max": 0.0, "step": 0.5,
                                      "tooltip": "同时说话时把其他角色压低多少 dB"}),
                "attack_ms": ("INT", {"default": int(audio_math.ATTACK_MS_DEFAULT),
                                      "min": 5, "max": 500, "tooltip": "压下去有多快（毫秒）"}),
                "release_ms": ("INT", {"default": int(audio_math.RELEASE_MS_DEFAULT),
                                       "min": 20, "max": 2000, "tooltip": "恢复有多快（毫秒）"}),
                "cfg_scale": ("FLOAT", {"default": 4.0, "min": 0.1, "max": 10.0, "step": 0.1,
                                        "tooltip": "Breeze 指令跟随强度，4.0 推荐"}),
                "max_new_tokens": ("INT", {"default": 1500, "min": 64, "max": 3000, "step": 8,
                                           "tooltip": "单条台词最大音频帧数（12.5 帧/秒）"}),
                "temperature": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 2.0, "step": 0.05}),
                "top_k": ("INT", {"default": 50, "min": 0, "max": 1024}),
                "top_p": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "repetition_penalty": ("FLOAT", {"default": 1.1, "min": 0.0, "max": 2.0, "step": 0.05}),
                "depth_temperature": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 2.0, "step": 0.05}),
                "depth_top_k": ("INT", {"default": 50, "min": 0, "max": 1024}),
                "depth_top_p": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "seed": ("INT", {"default": 20261128, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                                 "tooltip": "基础种子；第 n 条台词用 seed+n，固定即可复现/命中缓存"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        key = {k: kwargs.get(k) for k in (
            "lines", "mix_mode", "duck_db", "attack_ms", "release_ms", "cfg_scale",
            "max_new_tokens", "temperature", "top_k", "top_p", "repetition_penalty",
            "depth_temperature", "depth_top_k", "depth_top_p", "seed")}
        key["model_id"] = id(kwargs.get("breeze_model"))
        return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_lines(text: str) -> list[dict]:
        """解析台词表；格式错直接报清楚哪一行。"""
        entries = []
        for line_no, line in enumerate((text or "").splitlines(), start=1):
            if not line.strip() or line.strip().startswith("#"):
                continue
            match = LINE_RE.match(line)
            if not match:
                raise ValueError(
                    f"台词表第 {line_no} 行格式不对：{line!r}"
                    "（应形如“女主 @0.0 | 音色描述 | 台词”）")
            entries.append({
                "role": match.group("role").strip(),
                "start": max(0.0, float(match.group("start"))),
                "instruction": match.group("instruction").strip(),
                "text": match.group("text").strip(),
            })
        if not entries:
            raise ValueError("台词表是空的：至少写一行“角色 @起始秒 | 音色描述 | 台词”")
        return entries

    @staticmethod
    def _to_mono(audio: dict) -> tuple[torch.Tensor, int]:
        """把 Breeze 返回的 AUDIO 统一成 [1,1,N] 单声道（拼接不受声道数影响）。"""
        waveform = audio["waveform"].detach().float().cpu()
        rate = int(audio.get("sample_rate", 24000))
        if waveform.dim() == 1:
            waveform = waveform.view(1, 1, -1)
        elif waveform.dim() == 2:
            waveform = waveform.unsqueeze(0) if waveform.shape[0] == 1 else waveform.mean(0, keepdim=True).unsqueeze(0)
        elif waveform.dim() == 3:
            if waveform.shape[0] != 1:
                waveform = waveform.mean(0, keepdim=True)
            if waveform.shape[1] > 1:
                waveform = waveform.mean(dim=1, keepdim=True)
        else:
            raise error("DD-E050", f"TTS 返回了无法识别的波形维度：{tuple(waveform.shape)}")
        return waveform, rate

    def build(self, breeze_model, lines, mix_mode="auto_duck",
              duck_db=audio_math.DUCK_DB_DEFAULT,
              attack_ms=int(audio_math.ATTACK_MS_DEFAULT),
              release_ms=int(audio_math.RELEASE_MS_DEFAULT),
              cfg_scale=4.0, max_new_tokens=1500, temperature=0.9,
              top_k=50, top_p=1.0, repetition_penalty=1.1,
              depth_temperature=0.9, depth_top_k=50, depth_top_p=1.0, seed=20261128):
        if mix_mode not in audio_math.MIX_MODES:
            raise ValueError(f"未知混音模式 {mix_mode!r}（可选 {audio_math.MIX_MODES}）")
        if not breeze_tts.available():
            raise error("DD-E050", "没找到 Breeze-TTS-2 节点：请先安装 ComfyUI-Breeze-TTS-2 并重启 ComfyUI")
        entries = self._parse_lines(lines)

        # 1) 逐条生成 AUDIO，并记录归属角色/起始秒。
        generated: list[dict] = []
        for index, entry in enumerate(entries):
            audio = breeze_tts.voice_design(
                breeze_model,
                text=entry["text"],
                instruction=entry["instruction"] or "自然、清晰、适合剧集对白的说话声音。",
                cfg_scale=cfg_scale, max_new_tokens=max_new_tokens,
                temperature=temperature, top_k=top_k, top_p=top_p,
                repetition_penalty=repetition_penalty,
                depth_temperature=depth_temperature,
                depth_top_k=depth_top_k, depth_top_p=depth_top_p,
                seed=int(seed) + index)
            waveform, rate = self._to_mono(audio)
            generated.append({"role": entry["role"], "start": entry["start"],
                              "waveform": waveform, "rate": rate})

        # 2) 统一采样率（正常情况下同一个模型都是 24k；万一不一致就重采样）。
        rate = generated[0]["rate"]
        for item in generated[1:]:
            if item["rate"] == rate:
                continue
            import comfy.audio  # 只在真的不一致时才用 ComfyUI 的重采样
            item["waveform"] = comfy.audio.resample(
                item["waveform"], item["rate"], rate).cpu()
            item["rate"] = rate

        # 3) 同一角色的多条台词 -> 一条完整音轨（按起始秒摆放）。
        order: list[str] = []
        grouped: dict[str, list[dict]] = {}
        for item in generated:
            if item["role"] not in grouped:
                grouped[item["role"]] = []
                order.append(item["role"])
            grouped[item["role"]].append(item)

        tracks: dict[str, torch.Tensor] = {}
        role_lengths: dict[str, float] = {}
        for role in order:
            items = grouped[role]
            total = max(int(round(item["start"] * rate)) + int(item["waveform"].shape[-1])
                        for item in items)
            track = torch.zeros((1, 1, max(1, total)), dtype=torch.float32)
            for item in items:
                offset = int(round(item["start"] * rate))
                count = min(int(item["waveform"].shape[-1]), total - offset)
                if count > 0:
                    track[..., offset:offset + count] += item["waveform"][..., :count]
            tracks[role] = track
            role_lengths[role] = track.shape[-1] / float(rate)

        # 4) 组装 CAST：角色起点都归零（音轨里已经按台词起点摆好了）。
        roles = []
        for index, role in enumerate(order):
            roles.append({
                "id": role,
                "name": role,
                "start": 0.0,
                "gain_db": 0.0,
                "priority": len(order) - index,  # 越靠前优先级越高
                "voice": {"kind": "audio", "slot": index + 1},
                "audio_data": {"waveform": tracks[role], "sample_rate": rate},
            })
        cast = {
            "schema": "DIRECTOR_CAST@1",
            "lock_audio": True,
            "roles": roles,
            "mix": {"mode": str(mix_mode), "duck_db": float(duck_db),
                    "attack_ms": int(attack_ms), "release_ms": int(release_ms)},
        }

        # 5) 3 路预览音频（超过 3 个角色只给前 3 路；不足补静音）。
        previews = []
        for index in range(3):
            if index < len(order):
                previews.append({"waveform": tracks[order[index]], "sample_rate": rate})
            else:
                previews.append({"waveform": torch.zeros((1, 1, 1)), "sample_rate": rate})

        desc = " / ".join(f"{role}({len(grouped[role])}条, {role_lengths[role]:.2f}s, P{len(order)-i})"
                          for i, role in enumerate(order))
        summary = (f"台词 {len(entries)} 条，{len(order)} 个角色（优先级按出现顺序）：{desc}；"
                   f"混音={mix_mode}({duck_db:+.1f}dB, {attack_ms}/{release_ms}ms)")
        print(f"[DirectorDeck] TTS 台词表：{summary}")
        return (cast, previews[0], previews[1], previews[2], summary)
