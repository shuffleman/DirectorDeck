"""多角色 ducking/混音的应用层验证（不需要 GPU/模型，只要 ComfyUI venv）。

用两段合成音（A=440Hz、B=880Hz）拼出重叠时间轴，直接调用生成器用的
`av_latent.build_audio_track`，再用 FFT 量一下 B 在重叠区的实际音量：
- sum       ：重叠区 B 应该保持原样（约 0dB 变化）
- priority  ：A 优先级更高，B 在重叠区应被压约 duck_db（默认 -8dB）
- auto_duck ：B 更响的时候换成 A 被压
并检查限幅/峰值不超过 0.99。

用法（ComfyUI venv python）：
    F:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\ComfyUI\\.venv\\Scripts\\python.exe tools/mix_rules_check.py
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import torch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY = r"F:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI"
sys.path.insert(0, COMFY)
sys.path.insert(0, REPO)

from director_deck.adapters import av_latent  # noqa: E402

SR = 32000
DUR = 5.17


def tone(freq: float, amp: float, start: float, end: float,
         duration: float = DUR) -> torch.Tensor:
    n = int(duration * SR)
    t = np.arange(n) / SR
    wave = np.zeros(n, dtype=np.float32)
    mask = (t >= start) & (t < end)
    wave[mask] = amp * np.sin(2 * math.pi * freq * t[mask])
    return torch.from_numpy(wave).view(1, 1, -1).repeat(1, 2, 1)


def role(name: str, wave: torch.Tensor, priority: int, gain_db: float = 0.0) -> dict:
    return {"name": name, "start": 0.0, "gain_db": gain_db, "priority": priority,
            "audio_data": {"waveform": wave, "sample_rate": SR}}


def band_amp(track: torch.Tensor, freq: float, t0: float, t1: float) -> float:
    """在 [t0,t1] 窗口里量目标频率的幅度（正交投影，不受窗口长度/FFT 分辨率影响）。"""
    array = track[0].numpy()[0].astype(np.float64)
    i0, i1 = int(t0 * SR), int(t1 * SR)
    segment = array[i0:i1]
    if len(segment) < 64:
        return 0.0
    t = np.arange(len(segment)) / SR
    window = np.hanning(len(segment))
    gain = window.sum()
    cos_part = 2.0 * (segment * window * np.cos(2 * math.pi * freq * t)).sum() / gain
    sin_part = 2.0 * (segment * window * np.sin(2 * math.pi * freq * t)).sum() / gain
    return float(math.hypot(cos_part, sin_part))


def db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def run_case(label: str, roles: list[dict], mix: dict):
    track = av_latent.build_audio_track(roles, 0.0, DUR, SR, mix=mix)
    b_overlap = band_amp(track, 880, 2.32, 2.50)
    b_solo = band_amp(track, 880, 3.20, 4.50)
    a_overlap = band_amp(track, 440, 2.32, 2.50)
    a_before = band_amp(track, 440, 0.30, 1.50)
    peak = float(track.abs().max())
    print(f"{label:<28} B重叠/独唱={db(b_overlap) - db(b_solo):+6.2f}dB  "
          f"A重叠/之前={db(a_overlap) - db(a_before):+6.2f}dB  peak={peak:.3f}")
    return track


def main() -> int:
    wave_a = tone(440.0, 0.30, 0.0, 2.5)
    wave_b = tone(880.0, 0.30, 2.0, DUR)
    roles = [role("A", wave_a, priority=2), role("B", wave_b, priority=1)]

    print("=== 优先级模式（A 优先，B 在重叠区应被压 -8dB） ===")
    for mode in ("sum", "auto_duck", "priority"):
        run_case(f"mode={mode}", roles, {"mode": mode, "duck_db": -8.0,
                                         "attack_ms": 40, "release_ms": 200})

    print("=== auto_duck：B 更响时应该反过来压 A ===")
    loud_b = [role("A", tone(440.0, 0.10, 0.0, DUR), priority=1),
              role("B", tone(880.0, 0.40, 0.0, 2.5), priority=1)]
    loud_b_mix = av_latent.build_audio_track(loud_b, 0.0, DUR, SR, mix={"mode": "auto_duck", "duck_db": -8.0})
    a_overlap = band_amp(loud_b_mix, 440, 2.3, 2.45)
    a_final = band_amp(loud_b_mix, 440, 4.0, 5.0)
    print(f"auto_duck(B更响)              A 重叠/结尾={db(a_overlap) - db(a_final):+6.2f}dB（A 被压，应明显为负）")

    print("=== 每路增益：B 单独 -6dB（独唱区应降约 6dB） ===")
    roles_gain = [role("A", wave_a, priority=2), role("B", wave_b, priority=1, gain_db=-6.0)]
    base = av_latent.build_audio_track(
        [role("A", wave_a, priority=2), role("B", wave_b, priority=1)],
        0.0, DUR, SR, mix={"mode": "sum"})
    gained = av_latent.build_audio_track(roles_gain, 0.0, DUR, SR, mix={"mode": "sum"})
    diff = db(band_amp(gained, 880, 3.2, 4.5)) - db(band_amp(base, 880, 3.2, 4.5))
    print(f"B 独唱区增益差 = {diff:+.2f}dB（期望 ≈ -6dB）")

    print("=== 跨段 ducking 连续性（第二段是否继承第一段结尾增益） ===")
    # 两段各 5.167s，A/B 全程同时说话（B 应该一直被压）。
    # 波形做成两段总长，第二段窗口在 [DUR, 2*DUR] 才有素材可切。
    long_a = tone(440.0, 0.30, 0.0, 2 * DUR, duration=2 * DUR)
    long_b = tone(880.0, 0.30, 0.0, 2 * DUR, duration=2 * DUR)
    seg_roles = [role("A", long_a, priority=2), role("B", long_b, priority=1)]
    mix_rule = {"mode": "priority", "duck_db": -8.0, "attack_ms": 40, "release_ms": 200}
    _, ctx1 = av_latent.build_audio_track(
        seg_roles, 0.0, DUR, SR, mix=mix_rule, return_context=True)
    print("第一段结尾增益：", {k: round(v, 3) for k, v in ctx1["gain_state"].items()})
    # 第二段时间轴 5.167~10.334：roles 的 start 改成 0 让它们在段内也响。
    seg2_roles = [role("A", long_a, priority=2), role("B", long_b, priority=1)]
    track_cont, ctx2 = av_latent.build_audio_track(
        seg2_roles, DUR, 2 * DUR, SR, mix=mix_rule, previous=ctx1, return_context=True)
    track_fresh, _ = av_latent.build_audio_track(
        seg2_roles, DUR, 2 * DUR, SR, mix=mix_rule, return_context=True)
    # 量第二段开头的 B（880Hz）：续上下文应该已经压着，不续会从 1.0 慢慢压。
    b_cont = band_amp(track_cont, 880, 0.00, 0.03)
    b_fresh = band_amp(track_fresh, 880, 0.00, 0.03)
    print("第二段结尾增益：", {k: round(v, 3) for k, v in ctx2["gain_state"].items()})
    print(f"第二段开头 B 能量：延续上下文={db(b_cont):.2f}dB  "
          f"重置={db(b_fresh):.2f}dB  差={db(b_cont) - db(b_fresh):+.2f}dB")
    print("（差值为负说明第二段一开始就保持上一段的 ducking，没有弹回 1.0）")

    print("=== 结论 ===")
    print("priority 模式下 B 的重叠区相对独唱区应接近 -8dB；sum 应接近 0dB；")
    print("auto_duck 应按响度自动选主说话人；跨段默认继承上一段结尾增益。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
