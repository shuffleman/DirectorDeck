"""帧数学：把“我要几秒”换算成 H3 真正接受的帧数。

为什么单独放一个文件？
- H3 的帧数必须落在 17k+5 栅格上，算错一个数，采样直接报错；
- 多段链的“衔接头 / 正片 / 采样总长 / 时间轴起点”全是这一套公式推出来的；
- 这些公式是纯数学，不碰模型、不碰 ComfyUI，所以能写单测锁死（我们已经有 13 个用例）。

口语化概念：
- head（衔接头）：这一段开头有多少帧是“上一段的尾巴”，要被钉住不生成；
- delivery（交付帧）：真正属于这一段的画面，剪进成片的就是它；
- sample（采样长度）：交给 H3 的总帧数 = 衔接头 + 正片，而且必须满足 17k+5；
- timeline_start：这一段在整条时间轴上的起点（秒），数字人锁音切音频时要用。
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import FPS, FRAME_OFFSET, FRAME_STEP, HANDOFF_GRID, error


def grid_length(seconds: float, fps: int = FPS) -> int:
    """把秒数吸附到最近的 17k+5 栅格（四舍五入，不是向上取整）。

    举例：5 秒 @24fps = 120 帧，120 变成 17k+5 就是 124（k=7）。
    这也是为什么 H3 里“5 秒”实际是 124 帧，而不是 120 帧。
    """
    target = max(5.0, float(seconds) * float(fps))
    blocks = max(0, round((target - FRAME_OFFSET) / FRAME_STEP))
    return blocks * FRAME_STEP + FRAME_OFFSET


def is_valid_length(value: int) -> bool:
    """判断一个帧数是不是合法的 17k+5。"""
    return int(value) >= FRAME_OFFSET and int(value) % FRAME_STEP == FRAME_OFFSET


def grid_round_up(value: int) -> int:
    """向上补到最近的 17k+5。

    什么时候用？多段链里 sample = 衔接头 + 正片，这个和通常不是栅格，
    必须往上补几个帧，让 H3 能接受。多出来的尾巴正好给“保完整”用。
    """
    v = max(FRAME_OFFSET, int(value))
    while v % FRAME_STEP != FRAME_OFFSET:
        v += 1
    return v


def context_frames_for(handoff: int) -> int:
    """把用户填的衔接帧数吸附到 5/22/39/56。

    面板上允许填 1~56，但 H3 只认这四个值，所以“填 1~5 用 5、6~22 用 22……”
    这样不管用户怎么填，最后都能跑。
    """
    value = max(1, min(HANDOFF_GRID[-1], int(handoff)))
    for candidate in HANDOFF_GRID:
        if value <= candidate:
            return candidate
    return HANDOFF_GRID[-1]


def validate_canvas(width: int, height: int) -> tuple[int, int]:
    """宽高必须是 32 的倍数（H3 画布的硬性要求）。

    顺手返回元组，方便调用方写 w, h = validate_canvas(...)。
    """
    w, h = int(width), int(height)
    if w <= 0 or h <= 0 or w % 32 or h % 32:
        raise error("DD-E021", f"宽高必须为 32 的倍数，当前 {w}x{h}")
    return w, h


@dataclass(frozen=True)
class SegmentPlan:
    """一段的帧计划。frozen=True 是为了防止算完又被别处顺手改掉。"""

    index: int
    seconds: float
    head: int
    delivery: int
    sample: int
    timeline_start: float

    @property
    def length(self) -> int:
        """交给 H3 的 length 参数（= sample，一定是 17k+5）。"""
        return self.sample

    @property
    def duration(self) -> float:
        """这一段在成片里占多少秒（注意是交付帧，不含衔接头）。"""
        return self.delivery / FPS

    def to_dict(self) -> dict:
        """给 manifest / 调试面板用的可序列化形式。"""
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
    """算某一段的帧计划。index 从 0 开始（0 = 第一段）。

    规则：
    - 第 1 段：没有衔接头，head=0，delivery=sample=grid_length(秒数)；
    - 之后的段：head 吸附到 5/22/39/56；sample = 向上补到栅格的 (width + head)；
    - keep_full=True 时，sample 比“正片+头”多出来的那几帧也算进交付，
      避免下一段接不上（实际效果是每段固定多 12 帧，我们是按这个调过的）。
    """
    if index < 0:
        raise error("DD-E004", f"index 不能为负：{index}")
    requested = grid_length(seconds)

    # 第一段最省事：没头没脑，直接按秒数吸栅格。
    if index == 0:
        return SegmentPlan(index=0, seconds=float(seconds), head=0,
                           delivery=requested, sample=requested,
                           timeline_start=float(previous_timeline or 0.0))

    # 后面的段：先按栅格算正片，再加上衔接头，最后补到合法长度。
    head = context_frames_for(handoff_frames)
    sample = grid_round_up(requested + head)
    # keep_full 的意思是“多出来的尾巴别扔，也当成本段画面”，这样下一段钉尾帧时
    # 不会因为差几帧接不上。不保完整就只交 requested 帧。
    delivery = sample - head if keep_full else requested
    return SegmentPlan(index=index, seconds=float(seconds), head=head,
                       delivery=delivery, sample=sample,
                       timeline_start=float(previous_timeline or 0.0))


def plan_chain(segments: list[dict], handoff_frames: int = 22, *,
               keep_full: bool = True) -> list[SegmentPlan]:
    """给整条链（每段至少给个 seconds）批量算计划。

    时间轴起点是上一段起点 + 上一段时长，所以必须顺序算，不能并行。
    """
    plans: list[SegmentPlan] = []
    for index, segment in enumerate(segments):
        seconds = float(segment.get("seconds") or 5.0)
        previous_timeline = 0.0 if not plans else (
            plans[-1].timeline_start + plans[-1].duration)
        plan = segment_plan(index, seconds, handoff_frames,
                            previous_timeline=previous_timeline, keep_full=keep_full)
        plans.append(plan)
    return plans


def total_frames(plans: list[SegmentPlan]) -> int:
    """整条链一共交付多少帧（不含段间被裁掉的衔接头）。"""
    return sum(p.delivery for p in plans)


def total_duration(plans: list[SegmentPlan]) -> float:
    """成片时长（秒）。"""
    return total_frames(plans) / FPS


def validate_length(value: int, *, what: str = "length") -> int:
    """统一入口：校验并返回 17k+5 的帧数，不合规直接报 DD-E020。"""
    if not is_valid_length(value):
        raise error("DD-E020", f"{what}={value} 不是 17k+5（如 124、158、175、243、362）")
    return int(value)


# ---------------------------------------------------------------- latent 尾帧续写用
# H3 的视频 latent 里，一个“时间 token”覆盖的像素帧数不是固定的：
# 每 5 个 token 一个循环，覆盖 (1,4,4,4,4) 帧。latent 尾帧续写要把上一段
# 最后 head 帧对应的一整串 token 搬进新 latent，所以必须按这个表算边界。
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)


def video_latent_tokens(frame_count: int) -> int:
    """像素帧数 -> 视频 latent 的时间 token 数（H3 的公式）。"""
    frame_count = int(frame_count)
    return 2 if frame_count <= 5 else ((frame_count - 5) // 17) * 5 + 2


def token_frame_spans(token_count: int) -> list[int]:
    """每个时间 token 覆盖多少像素帧。"""
    return [FRAME_PER_TOKEN[i % 5] for i in range(max(0, int(token_count)))]


def token_frame_boundaries(token_count: int) -> list[int]:
    """累积边界：boundaries[k] = 前 k 个 token 覆盖的总帧数（长度 token_count+1）。

    例如 47 个 token 的最后一项是 158，代表 158 帧。
    """
    boundaries = [0]
    for span in token_frame_spans(token_count):
        boundaries.append(boundaries[-1] + span)
    return boundaries


def tail_token_boundary(sample_frames: int, head_frames: int) -> tuple[int, int]:
    """算“尾帧续写”要搬多少个 token、实际遮住多少帧。

    为什么不能正好等于 head_frames：token 边界不一定落在任意帧上，
    只能取“最接近且不超过目标”的 token 边界；实际遮住的帧数会 ≥ head（最多多 3 帧）。
    返回 (k0, masked_frames)：搬 token[k0:]，新视频前 masked_frames 帧来自上一段。

    举例（5 秒段、head=22）：sample=158、token 47 个，边界里正好有 136，
    于是 k0=40、masked=22，和请求一致。
    """
    sample_frames = int(sample_frames)
    head_frames = max(1, int(head_frames))
    token_count = video_latent_tokens(sample_frames)
    boundaries = token_frame_boundaries(token_count)
    target = sample_frames - head_frames
    # 找最后一个 <= target 的边界（下标 k 就代表搬 token[k:]）。
    k0 = 0
    for index, boundary in enumerate(boundaries):
        if boundary <= target:
            k0 = index
        else:
            break
    k0 = max(0, min(k0, token_count))
    masked_frames = sample_frames - boundaries[k0]
    return k0, masked_frames

# ---------------------------------------------------------------- 分辨率预设
# 用户嘴里说的“480p / 768p / 1080p”要落到 H3 能用的 32 倍数画布。
# 因为 16:9 的常见尺寸（854x480、1280x720、1920x1080）不一定两边都是 32 的倍数，
# 这里直接给一组“已经对齐 32”的预设，避免用户自己算。
RESOLUTION_CUSTOM = "自定义（用宽高）"
RESOLUTION_OPTIONS = (RESOLUTION_CUSTOM, "480p", "720p", "768p", "1080p")
ASPECT_RATIOS = ("16:9 横屏", "9:16 竖屏", "1:1 方形")

RESOLUTION_PRESETS: dict[str, dict[str, tuple[int, int]]] = {
    "480p": {
        "16:9 横屏": (864, 480),
        "9:16 竖屏": (480, 864),
        "1:1 方形": (480, 480),
    },
    "720p": {
        "16:9 横屏": (1280, 704),
        "9:16 竖屏": (704, 1280),
        "1:1 方形": (704, 704),
    },
    "768p": {
        "16:9 横屏": (1376, 768),
        "9:16 竖屏": (768, 1376),
        "1:1 方形": (768, 768),
    },
    "1080p": {
        "16:9 横屏": (1920, 1088),
        "9:16 竖屏": (1088, 1920),
        "1:1 方形": (1088, 1088),
    },
}


def resolve_canvas(width: int, height: int, resolution: str = RESOLUTION_CUSTOM,
                   aspect_ratio: str = ASPECT_RATIOS[0]) -> tuple[int, int]:
    """全局画布尺寸解析：选了分辨率预设就用预设，选“自定义”就用宽高。

    返回 (width, height)，保证两边都是 32 的倍数；预设表本身就是对齐好的。
    """
    if resolution in RESOLUTION_PRESETS:
        table = RESOLUTION_PRESETS[resolution]
        if aspect_ratio not in table:
            raise error("DD-E004", f"未知画面比例 {aspect_ratio!r}（可选 {ASPECT_RATIOS}）")
        return validate_canvas(*table[aspect_ratio])
    if resolution != RESOLUTION_CUSTOM:
        raise error("DD-E004", f"未知分辨率 {resolution!r}（可选 {RESOLUTION_OPTIONS}）")
    return validate_canvas(width, height)
