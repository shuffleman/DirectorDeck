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


def tone(freq: float, amp: float, start: float, end: float) -> torch.Tensor:
    n = int(DUR * SR)
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
    print("=== 结论 ===")
    print("priority 模式下 B 的重叠区相对独唱区应接近 -8dB；sum 应接近 0dB；")
    print("auto_duck 应按响度自动选主说话人。以上由上面的数值直接验证。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
