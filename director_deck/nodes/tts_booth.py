"""DirectorDeck · TTS 台词表（一键多角色配音 -> CAST）。

它解决的问题：以前要在画布上手摆 N 个 Breeze TTS 节点、再一个个接进锁音器；
现在只写一张“台词表”，节点自动：
1. 按行解析 `角色 @起始秒 | 音色描述 | 台词`（`@起始秒` 可以省略或写 `@auto`）；
2. 可选按句自动分段，再逐条调 Breeze-TTS-2 的 VoiceDesign 生成 AUDIO；
3. 没有写起始秒的句子按“上一句结束 + 停顿”自动往后排（以真实音频长度为准）；
4. 把同一角色的多句拼到同一条音轨上，输出可直接锁音的 CAST，
   以及 3 路可试听/保存的 AUDIO 和总时长。

台词表格式（每行一条台词，`|` 分隔三列）：
    女主 @0.0 | 一位年轻女性，声音清澈温柔，语速偏慢。 | 你好，我是这部剧的女主角。
    男主 | 一位年轻男性，声音低沉沉稳，语气干练。 | 收到，我去检查船桨，五分钟以后开拍。

注意：
- 起始秒可以省略（自动排期）或写 `@auto`；写死的人话就按写死的来。
- 角色名相同 = 同一角色，会共用同一条音轨。
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

# 行首：“角色”或“角色 @起始秒”/“角色 @auto”
HEAD_RE = re.compile(
    r"^\s*(?P<role>[^@|]+?)\s*(?:@\s*(?P<start>auto|-?[0-9.]+))?\s*$", re.IGNORECASE)

DEFAULT_LINES = (
    "女主 | 一位年轻女性，声音清澈温柔，语速偏慢，情绪平静。 | 你好，我是这部剧的女主角。\n"
    "男主 | 一位年轻男性，声音低沉沉稳，语气干练。 | 收到，我去检查船桨，五分钟以后开拍。"
)


class DirectorDeckTTSBooth:
    """台词表 -> 多角色 TTS -> CAST（可直接接视频生成器锁音）。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "build"
    RETURN_TYPES = (TYPE_CAST, "AUDIO", "AUDIO", "AUDIO", "STRING", "FLOAT")
    RETURN_NAMES = ("cast", "audio_1", "audio_2", "audio_3", "summary", "total_seconds")
    DESCRIPTION = (
        "一张台词表搞定多角色配音：每行“角色 @起始秒 | 音色描述 | 台词”，"
        "起始秒可省略（自动按句排期）；自动调 Breeze-TTS-2 生成并拼成角色音轨，"
        "输出可直接锁音的 CAST、总时长。角色顺序即 ducking 优先级。需要 ComfyUI-Breeze-TTS-2。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "breeze_model": ("BREEZE_TTS2_MODEL", {
                    "tooltip": "接 Breeze TTS 2 Load Model 的输出"}),
                "lines": ("STRING", {"multiline": True, "default": DEFAULT_LINES,
                                     "tooltip": "每行：角色 [@起始秒] | 音色描述 | 台词；起始秒省略=自动排期"}),
                "auto_start": ("BOOLEAN", {"default": True,
                                           "tooltip": "开=没写起始秒的句子自动往后排；关=必须每句都写起始秒"}),
                "auto_split": ("BOOLEAN", {"default": True,
                                           "tooltip": "开=一句里有多句时按句号/问号/感叹号自动分段生成"}),
                "pause_ms": ("INT", {"default": int(audio_math.PAUSE_MS_DEFAULT), "min": 0, "max": 5000,
                                     "tooltip": "自动排期时两句之间留多少毫秒停顿"}),
                "chars_per_second": ("FLOAT", {"default": audio_math.SPEECH_CPS_DEFAULT,
                                               "min": 1.0, "max": 12.0, "step": 0.1,
                                               "tooltip": "生成前按字数预估语速（仅摘要里参考，实际以音频为准）"}),
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
                                 "tooltip": "基础种子；第 n 句台词用 seed+n，固定即可复现/命中缓存"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        key = {k: kwargs.get(k) for k in (
            "lines", "auto_start", "auto_split", "pause_ms", "chars_per_second",
            "mix_mode", "duck_db", "attack_ms", "release_ms", "cfg_scale",
            "max_new_tokens", "temperature", "top_k", "top_p", "repetition_penalty",
            "depth_temperature", "depth_top_k", "depth_top_p", "seed")}
        key["model_id"] = id(kwargs.get("breeze_model"))
        return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_lines(text: str) -> list[dict]:
        """解析台词表；格式错直接报清楚哪一行。

        行格式：`角色 [@起始秒] | 音色描述 | 台词`；`@auto` 等于不写起始秒。
        """
        entries = []
        for line_no, line in enumerate((text or "").splitlines(), start=1):
            if not line.strip() or line.strip().startswith("#"):
                continue
            parts = line.split("|", 2)  # 台词里允许再出现 |，只切前两刀
            if len(parts) != 3:
                raise ValueError(
                    f"台词表第 {line_no} 行格式不对：{line!r}"
                    "（应形如“女主 @0.0 | 音色描述 | 台词”，起始秒可省略）")
            head = HEAD_RE.match(parts[0].strip())
            if not head:
                raise ValueError(f"台词表第 {line_no} 行的角色/起始秒写法不对：{parts[0]!r}")
            start_raw = head.group("start")
            start = None
            if start_raw and start_raw.lower() != "auto":
                start = max(0.0, float(start_raw))
            entries.append({
                "role": head.group("role").strip(),
                "start": start,
                "instruction": parts[1].strip(),
                "text": parts[2].strip(),
                "line_no": line_no,
            })
        if not entries:
            raise ValueError("台词表是空的：至少写一行“角色 | 音色描述 | 台词”")
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

    def build(self, breeze_model, lines, auto_start=True, auto_split=True,
              pause_ms=int(audio_math.PAUSE_MS_DEFAULT),
              chars_per_second=audio_math.SPEECH_CPS_DEFAULT,
              mix_mode="auto_duck", duck_db=audio_math.DUCK_DB_DEFAULT,
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
        pause = max(0, int(pause_ms)) / 1000.0

        # 1) 展开成“生成单元”：一行可能因为自动分段变成多句。
        units: list[dict] = []
        for entry in entries:
            sentences = (audio_math.split_sentences(entry["text"])
                         if auto_split else [entry["text"]])
            if not sentences:
                sentences = [entry["text"]]
            for index, sentence in enumerate(sentences):
                units.append({
                    "role": entry["role"],
                    "text": sentence,
                    "instruction": entry["instruction"],
                    "explicit_start": entry["start"] if index == 0 else None,
                    "line_no": entry["line_no"],
                })
        if not auto_start:
            missing = [unit["line_no"] for unit in units if unit["explicit_start"] is None]
            if missing:
                raise ValueError(
                    f"auto_start=False 时每句都要写起始秒，但这些行没写：{sorted(set(missing))}"
                    "（或者打开 auto_start 自动排期）")

        # 2) 逐句生成 AUDIO，量出真实时长。
        for index, unit in enumerate(units):
            audio = breeze_tts.voice_design(
                breeze_model,
                text=unit["text"],
                instruction=unit["instruction"] or "自然、清晰、适合剧集对白的说话声音。",
                cfg_scale=cfg_scale, max_new_tokens=max_new_tokens,
                temperature=temperature, top_k=top_k, top_p=top_p,
                repetition_penalty=repetition_penalty,
                depth_temperature=depth_temperature,
                depth_top_k=depth_top_k, depth_top_p=depth_top_p,
                seed=int(seed) + index)
            waveform, rate = self._to_mono(audio)
            unit["waveform"] = waveform
            unit["rate"] = rate
            unit["duration"] = waveform.shape[-1] / float(rate)
            unit["estimate"] = audio_math.estimate_speech_seconds(
                unit["text"], float(chars_per_second))

        # 3) 统一采样率（正常情况下都是 24k；万一不一致就重采样）。
        rate = units[0]["rate"]
        for unit in units[1:]:
            if unit["rate"] == rate:
                continue
            import comfy.audio  # 只在真的不一致时才用 ComfyUI 的重采样
            unit["waveform"] = comfy.audio.resample(
                unit["waveform"], unit["rate"], rate).cpu()
            unit["rate"] = rate
            unit["duration"] = unit["waveform"].shape[-1] / float(rate)

        # 4) 自动排期：显式起始秒优先，其余“上一句结束 + 停顿”。
        starts = audio_math.schedule_starts(
            [unit["duration"] for unit in units],
            [unit["explicit_start"] for unit in units],
            pause_seconds=pause)

        # 5) 同一角色的多句 -> 一条完整音轨（按排好的起始秒摆放）。
        order: list[str] = []
        grouped: dict[str, list[dict]] = {}
        for unit, start in zip(units, starts):
            unit["start"] = start
            if unit["role"] not in grouped:
                grouped[unit["role"]] = []
                order.append(unit["role"])
            grouped[unit["role"]].append(unit)

        tracks: dict[str, torch.Tensor] = {}
        role_units: dict[str, int] = {}
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
            role_units[role] = len(items)

        # 6) 组装 CAST：角色起点都归零（音轨里已经按句子的绝对起点摆好了）。
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

        # 7) 3 路预览音频（超过 3 个角色只给前 3 路；不足补静音）。
        previews = []
        for index in range(3):
            if index < len(order):
                previews.append({"waveform": tracks[order[index]], "sample_rate": rate})
            else:
                previews.append({"waveform": torch.zeros((1, 1, 1)), "sample_rate": rate})

        total_seconds = round(max((unit["start"] + unit["duration"] for unit in units),
                                  default=0.0), 3)
        estimated = round(sum(unit["estimate"] for unit in units)
                          + pause * max(0, len(units) - 1), 3)
        timeline = " / ".join(
            f"{unit['role']}@{unit['start']:.2f}+{unit['duration']:.2f}s"
            for unit in units)
        desc = " / ".join(f"{role}({role_units[role]}句)" for role in order)
        summary = (
            f"台词 {len(units)} 句（原始 {len(entries)} 行），{len(order)} 个角色：{desc}；"
            f"总长 {total_seconds:.2f}s（生成前预估约 {estimated:.2f}s）；"
            f"排期：{timeline}；混音={mix_mode}({duck_db:+.1f}dB, {attack_ms}/{release_ms}ms)")
        print(f"[DirectorDeck] TTS 台词表：{summary}")
        return (cast, previews[0], previews[1], previews[2], summary, float(total_seconds))
