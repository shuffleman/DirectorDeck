"""接缝/曝光匹配（纯数学，不碰 torch/ComfyUI，方便单测）。

要解决什么问题？
两段视频拼在一起时，段边界常常“亮一截/暗一截/偏色”——因为每段是独立采样的，
曝光和色温会有微小漂移。如果不修，观众一眼就能看出“这是两段拼的”。

做法（和之前 H3 Lite 验证过的一致）：
1. 取上一段最后 window 帧、下一段最前 window 帧，算每帧平均亮度；
2. 用线性回归求出“下一段要乘多少 gain、加多少 offset”才能贴近上一段；
3. gain/offset 都夹紧（默认 ±4% / ±10%），避免修过头把画面拉灰；
4. 如果两段亮度差太大（比如故意硬切/换场景），就别硬修，直接判定 hard_cut 跳过调整。

注意：这里只算参数、不碰画面；真正乘到帧上由节点层（torch）来做。
"""

from __future__ import annotations

WINDOW_DEFAULT = 12
MAX_ADD_DEFAULT = 0.10
GAIN_LIMIT_DEFAULT = 0.04
# 亮度差超过 low 阈值就开始警惕，超过 high 阈值直接当硬切（不修）。
HARD_CUT_LOW = 0.012
HARD_CUT_HIGH = 0.022


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def exposure_plan(prev_means: list[float], cur_means: list[float], *,
                  window: int = WINDOW_DEFAULT,
                  max_add: float = MAX_ADD_DEFAULT,
                  gain_limit: float = GAIN_LIMIT_DEFAULT,
                  hardcut_low: float = HARD_CUT_LOW,
                  hardcut_high: float = HARD_CUT_HIGH) -> dict:
    """根据两段的逐帧平均亮度，算出接缝修正参数。

    返回字典（都能直接 JSON 序列化，方便写进 segment 元数据）：
    - apply：是否要改画面；
    - gain/offset：下一段交付帧的修正系数（new = gain * old + offset）；
    - lowfreq：两段整体亮度差（正=上一段更亮，需要提亮下一段）；
    - hard_cut：是否判定为硬切（真换场景，不修）；
    - window：实际参与计算的帧数。
    """
    window = max(1, int(window))
    n = min(len(prev_means or []), len(cur_means or []), window)
    if n < 2:
        return {"apply": False, "reason": "窗口帧数不足", "gain": 1.0, "offset": 0.0,
                "lowfreq": 0.0, "hard_cut": False, "window": n}

    prev = [float(v) for v in prev_means[-n:]]
    cur = [float(v) for v in cur_means[:n]]

    # 整体亮度差：上一段尾部均值 - 下一段头部均值。
    lowfreq = sum(prev) / n - sum(cur) / n

    # 线性回归 prev ≈ gain * cur + offset（最小二乘）。
    mean_p = sum(prev) / n
    mean_c = sum(cur) / n
    cov = sum((cur[i] - mean_c) * (prev[i] - mean_p) for i in range(n))
    var = sum((cur[i] - mean_c) ** 2 for i in range(n))
    gain = (cov / var) if var > 1e-9 else 1.0
    gain = _clamp(gain, 1.0 - gain_limit, 1.0 + gain_limit)
    offset = _clamp(mean_p - gain * mean_c, -max_add, max_add)

    # 修完以后的残余误差，用来给用户一个“接缝质量”指标。
    adjusted = [gain * cur[i] + offset for i in range(n)]
    residual = sum(abs(adjusted[i] - prev[i]) for i in range(n)) / n

    # 硬切判定：整体差太大就不是“漂移”，而是故意换场景，强行匹配会拉灰。
    hard_cut = abs(lowfreq) > hardcut_high
    # 小抖动但方向明确（超过 low 阈值）时也保守：只调 offset 不动 gain。
    small_shift = abs(lowfreq) > hardcut_low and not hard_cut

    apply = (not hard_cut) and (abs(offset) > 0.0005 or abs(gain - 1.0) > 0.0005)
    return {
        "apply": bool(apply),
        "gain": round(float(gain), 6),
        "offset": round(float(offset), 6),
        "lowfreq": round(float(lowfreq), 6),
        "residual": round(float(residual), 6),
        "hard_cut": bool(hard_cut),
        "small_shift": bool(small_shift),
        "window": n,
    }
