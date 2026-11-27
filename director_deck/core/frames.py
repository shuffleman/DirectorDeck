"""17k+5 帧数学（与 H3 原生时间栅格一致）。

契约见 docs/CONTRACTS.md §5：
    grid_length(seconds) = round((max(5, 秒*24) - 5) / 17) * 17 + 5
    第 1 段: head=0, delivery=sample=grid_length
    后续段  : head=context_frames(handoff)（5/22/39/56）
              sample = grid_round_up(delivery_requested + head)
              delivery = sample - head（keep_full=True，默认）
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import FPS, FRAME_OFFSET, FRAME_STEP, HANDOFF_GRID, error


def grid_length(seconds: float, fps: int = FPS) -> int:
    """秒数吸附到 H3 的 17k+5 栅格（5s@24fps -> 124）。"""
    target = max(5.0, float(seconds) * float(fps))
    blocks = max(0, round((target - FRAME_OFFSET) / FRAME_STEP))
    return blocks * FRAME_STEP + FRAME_OFFSET


def is_valid_length(value: int) -> bool:
    return int(value) >= FRAME_OFFSET and int(value) % FRAME_STEP == FRAME_OFFSET


def grid_round_up(value: int) -> int:
    """向上补到最近的 17k+5。"""
    v = max(FRAME_OFFSET, int(value))
    while v % FRAME_STEP != FRAME_OFFSET:
        v += 1
    v += 0
    return v


def context_frames_for(handoff: int) -> int:
    """衔接帧吸附到 5/22/39/56。"""
    value = max(1, min(HANDOFF_GRID[-1], int(handoff)))
    for candidate in HANDOFF_GRID:
        if value <= candidate:
            return candidate
    return HANDOFF_GRID[-1]


def validate_canvas(width: int, height: int) -> tuple[int, int]:
    """宽高必须是 32 的倍数（H3 画布约束）。"""
    w, h = int(width), int(height)
    if w <= 0 or h <= 0 or w % 32 or h % 32:
        raise error("DD-E021", f"宽高必须为 32 的倍数，当前 {w}x{h}")
    return w, h


@dataclass(frozen=True)
class SegmentPlan:
    """单段的帧计划。"""

    index: int
    seconds: float
    head: int
    delivery: int
    sample: int
    timeline_start: float

    @property
    def length(self) -> int:
        """交给 H3 的 length（= sample，等于 17k+5 网格长度）。"""
        return self.sample

    @property
    def duration(self) -> float:
        return self.delivery / FPS

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "seconds": self.seconds,
            "head": self.head,
            "delivery": self.delivery,
            "sample": self.sample,
            "timeline_start": round(self.timeline_start, 6),
            "length": self.length,
        }


def segment_plan(index: int, seconds: float, handoff_frames: int = 22, *,
                 previous_timeline: float = 0.0, keep_full: bool = True) -> SegmentPlan:
    """计算单段帧计划。index 从 0 开始。"""
    if index < 0:
        raise error("DD-E004", f"index 不能为负：{index}")
    requested = grid_length(seconds)
    if index == 0:
        return SegmentPlan(index=0, seconds=float(seconds), head=0,
                           delivery=requested, sample=requested,
                           timeline_start=float(previous_timeline or 0.0))
    head = context_frames_for(handoff_frames)
    sample = grid_round_up(requested + head)
    delivery = sample - head if keep_full else requested
    return SegmentPlan(index=index, seconds=float(seconds), head=head,
                       delivery=delivery, sample=sample,
                       timeline_start=float(previous_timeline or 0.0))


def plan_chain(segments: list[dict], handoff_frames: int = 22, *,
               keep_full: bool = True) -> list[SegmentPlan]:
    """给一组 {seconds?} 段生成完整计划；缺秒数用 5.0。"""
    plans: list[SegmentPlan] = []
    for index, segment in enumerate(segments):
        seconds = float(segment.get("seconds") or 5.0)
        previous_timeline = 0.0 if not plans else (plans[-1].timeline_start + plans[-1].duration)
        plan = segment_plan(index, seconds, handoff_frames,
                            previous_timeline=previous_timeline, keep_full=keep_full)
        plans.append(plan)
    return plans


def total_frames(plans: list[SegmentPlan]) -> int:
    return sum(p.delivery for p in plans)


def total_duration(plans: list[SegmentPlan]) -> float:
    return total_frames(plans) / FPS


def validate_length(value: int, *, what: str = "length") -> int:
    if not is_valid_length(value):
        raise error("DD-E020", f"{what}={value} 不是 17k+5（如 124、158、175、243、362）")
    return int(value)
