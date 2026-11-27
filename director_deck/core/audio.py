"""音频时间窗口数学（纯 Python，方便单测）。

锁音要解决的第一个问题不是模型，而是“这段音频到底该切哪一截”：
- 一条 16 秒的台词音频，第 2 段（时间轴 5.17s~10.33s）该取哪一段？
- 角色 A 的音频从第 3 秒开始，角色 B 从第 7 秒开始，重叠部分怎么混？
- 段开头有衔接头（head 帧），音频要不要一起往前挪？

这些换算都是“秒 <-> 采样点”的数学，放这里就能不装 torch 也测。
真正把 float 波形切出来、相加，是节点层用 torch 干的。
"""

from __future__ import annotations


def samples_for(seconds: float, sample_rate: int) -> int:
    """秒 -> 采样点数（四舍五入到最近的整数点）。"""
    return int(round(float(seconds) * int(sample_rate)))


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """两个时间区间的重叠长度（秒）；不重叠返回 0。"""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def clip_window(clip_start: float, clip_end: float,
                seg_start: float, seg_end: float) -> tuple[float, float, float] | None:
    """算出“一条素材”在“某一段”里应该取哪一截。

    参数：
    - clip_start/clip_end：素材在整条时间轴上的起点/终点（秒）；
    - seg_start/seg_end：这一段在时间轴上的起点/终点（秒）。

    返回 (src_offset, dst_offset, length)：
    - src_offset：从素材的第几秒开始取；
    - dst_offset：放到这一段的第几秒（段内相对时间）；
    - length：取多长。
    完全不重叠就返回 None（这段不用这条素材）。
    """
    start = max(clip_start, seg_start)
    end = min(clip_end, seg_end)
    if end <= start:
        return None
    return (start - clip_start, start - seg_start, end - start)


def segment_span(timeline_start: float, head_frames: int, sample_frames: int, fps: int = 24
                 ) -> tuple[float, float]:
    """一段在时间轴上的真实区间（秒）。

    注意：采样长度的开头有 head 帧是上一段的重复尾巴，所以这一段的“素材起点”
    要往前挪 head 帧。锁定音频是按整段采样窗口铺的，不是只铺交付部分。
    """
    start = float(timeline_start) - float(head_frames) / float(fps)
    start = max(0.0, start)
    duration = float(sample_frames) / float(fps)
    return start, start + duration


# ---------------------------------------------------------------- 多角色混音规则
# 多角色锁音不是“把所有音轨加起来”就完了：
# - 两个人同时说话时，一个声音会盖住另一个（观众听不清），需要自动 ducking；
# - 每路的音量/优先级要能单独调；
# - 切换要平滑（attack/release），否则会“咔哒”爆音；
# - 最后要限幅（limiter），避免叠加后削波。
#
# 这一节是纯 Python 的“增益包络”数学：输入每个角色逐帧的能量/优先级，
# 输出每个角色逐帧的增益系数（0~1）。真正的采样点相乘在 torch 层做。

MIX_MODES = ("auto_duck", "priority", "sum")
MIX_FRAME_MS = 10.0
DUCK_DB_DEFAULT = -8.0
ATTACK_MS_DEFAULT = 60.0
RELEASE_MS_DEFAULT = 200.0
SILENCE_RATIO = 0.02  # 能量低于全局峰值的 2% 当“没说话”


def db_to_linear(db: float) -> float:
    """分贝 -> 线性增益（-8dB ≈ 0.398）。"""
    return float(10.0 ** (float(db) / 20.0))


def linear_to_db(gain: float) -> float:
    """线性增益 -> 分贝（0 会给 -inf，调用方注意）。"""
    gain = float(gain)
    if gain <= 0:
        return float("-inf")
    import math
    return 20.0 * math.log10(gain)


def frame_rms(samples: list[float], frame_size: int) -> list[float]:
    """把一维采样点切成帧，算每帧 RMS（纯 Python，测试/离线分析用）。"""
    frame_size = max(1, int(frame_size))
    out = []
    for start in range(0, len(samples), frame_size):
        chunk = samples[start:start + frame_size]
        if not chunk:
            break
        total = sum(float(x) * float(x) for x in chunk)
        out.append((total / len(chunk)) ** 0.5)
    return out


def mix_gains(role_energies: list[list[float]], priorities: list[int] | None = None,
              *, mode: str = "auto_duck", duck_db: float = DUCK_DB_DEFAULT,
              attack_ms: float = ATTACK_MS_DEFAULT,
              release_ms: float = RELEASE_MS_DEFAULT,
              frame_ms: float = MIX_FRAME_MS,
              silence_ratio: float = SILENCE_RATIO) -> list[list[float]]:
    """按帧算每个角色的增益包络。

    参数：
    - role_energies：[[role0 每帧能量...], [role1 每帧能量...], ...]
    - priorities：每个角色的优先级（越大越不容易被压），mode=priority 时使用
    - mode：
        auto_duck —— 每帧音量最大的角色保持原样，其他同时发声的角色压 duck_db；
        priority  —— 每帧优先级最高的角色保持原样，其他角色压 duck_db；
        sum       —— 不做 ducking（只做每路基础增益）。
    - duck_db / attack_ms / release_ms：压多少、压下去多快、恢复多快。

    返回与 role_energies 同形状的增益列表（1.0=不压）。
    """
    if mode not in MIX_MODES:
        raise ValueError(f"未知混音模式 {mode!r}（可选 {MIX_MODES}）")
    roles = len(role_energies)
    if roles == 0:
        return []
    frames = max((len(row) for row in role_energies), default=0)
    if frames == 0:
        return [[1.0] for _ in range(roles)]
    priorities = list(priorities or [0] * roles)
    while len(priorities) < roles:
        priorities.append(0)

    # 1) 归一化能量：用全局峰值判断“说话/没说话”。
    all_max = max((max(row) if row else 0.0) for row in role_energies) or 1e-9
    threshold = all_max * max(0.0, float(silence_ratio))
    duck_gain = max(0.0, min(1.0, db_to_linear(duck_db)))

    # 2) 逐帧决定“谁是主说话人”。
    targets = [[1.0] * frames for _ in range(roles)]
    if mode != "sum":
        for frame in range(frames):
            energies = [row[frame] if frame < len(row) else 0.0 for row in role_energies]
            active = [i for i, energy in enumerate(energies) if energy > threshold]
            if len(active) < 2:
                continue
            if mode == "auto_duck":
                keeper = max(active, key=lambda i: (energies[i], priorities[i], -i))
            else:  # priority
                keeper = max(active, key=lambda i: (priorities[i], energies[i], -i))
            for role in active:
                if role != keeper:
                    targets[role][frame] = duck_gain

    # 3) 平滑：目标变小走 attack，变大走 release，避免爆音。
    import math
    frame_ms = max(1e-3, float(frame_ms))
    attack_coeff = math.exp(-frame_ms / max(1.0, float(attack_ms)))
    release_coeff = math.exp(-frame_ms / max(1.0, float(release_ms)))
    envelopes = []
    for role in range(roles):
        gain = 1.0
        row = []
        for frame in range(frames):
            target = targets[role][frame]
            coeff = attack_coeff if target < gain else release_coeff
            gain = coeff * gain + (1.0 - coeff) * target
            row.append(round(gain, 6))
        envelopes.append(row)
    return envelopes


def apply_limiter(peak: float, *, ceiling: float = 0.99) -> float:
    """全局限幅：峰值超过 ceiling 就整体缩下来（返回要乘的系数）。

    为什么不用 tanh 软削波？锁音是“台词”，要求可懂度；硬限幅只降整体电平，
    不会把波形形状改坏（真爆音的场景 M4 还可以用源音频混流绕过）。
    """
    peak = float(peak)
    if peak <= float(ceiling) or peak <= 0:
        return 1.0
    return float(ceiling) / peak
