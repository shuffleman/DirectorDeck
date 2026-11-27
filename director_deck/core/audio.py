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
