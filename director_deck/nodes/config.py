"""DirectorDeck · 全局配置（M1）。

整条链只有一个配置真相源：分辨率、段时长、衔接帧、采样参数、种子策略、预览开关……
每段都可以用 config_policy=overrides 覆盖“安全子集”，但画布/fps/模型改不了。
"""

from __future__ import annotations

import hashlib
import json

from ..core import frames
from ..core import seam
from ..core.types import CATEGORY, FPS, TYPE_CONFIG

# 种子策略：
# - per_segment：每段错开（默认，方便多段不撞脸）；
# - fixed：全片同一个种子；
# - increment：每段 +1。
SEED_STRATEGIES = ["per_segment", "fixed", "increment"]

# 显存策略（M2 起真正生效）：release=每段后释放；unload=卸载模型；none=不管。
VRAM_POLICIES = ["release", "unload", "none"]

# 段文件清理策略：ask=问用户；auto=自动清中间文件；keep=全留。
CLEANUP_MODES = ["ask", "auto", "keep"]

# 13 号工作流同款 sigma 表（7 个点，插值到 10 步）。
DEFAULT_SIGMAS = "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"


class DirectorDeckConfig:
    """全局配置节点：输出 DIRECTOR_CONFIG。"""

    CATEGORY = f"{CATEGORY}/加载"
    FUNCTION = "build"
    RETURN_TYPES = (TYPE_CONFIG,)
    RETURN_NAMES = ("config",)
    DESCRIPTION = ("整条链唯一的配置来源。宽高须 32 倍数（或直接选 480p/720p/768p/1080p 预设）；"
                   "fps 固定 24；handoff_frames 只允许 5/22/39/56（17n+5 衔接栅格）。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {"default": 640, "min": 32, "max": 16384, "step": 32}),
                "height": ("INT", {"default": 352, "min": 32, "max": 16384, "step": 32}),
                "segment_seconds": ("FLOAT", {"default": 5.0, "min": 0.5, "max": 60.0, "step": 0.1}),
                "handoff_frames": ("INT", {"default": 22, "min": 5, "max": 56, "step": 1,
                                           "tooltip": "衔接帧数，吸附到 5/22/39/56"}),
                "sampler_name": (["er_sde", "euler", "dpmpp_2m", "dpmpp_2m_sde"], {"default": "er_sde"}),
                "scheduler": (["beta", "normal", "karras", "simple"], {"default": "beta"}),
                "steps": ("INT", {"default": 10, "min": 1, "max": 100}),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "sigmas_string": ("STRING", {"default": DEFAULT_SIGMAS, "multiline": False,
                                             "tooltip": "自定义 sigma 表（13 号同款）；空=用 scheduler+steps 计算"}),
                "interpolate_to_steps": ("INT", {"default": 10, "min": 0, "max": 255}),
                "seed_strategy": (SEED_STRATEGIES, {"default": "per_segment"}),
                "seed_base": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "preview": ("BOOLEAN", {"default": True}),
                "vram_policy": (VRAM_POLICIES, {"default": "release"}),
                "cleanup_segments": (CLEANUP_MODES, {"default": "ask"}),
                # ---- 接缝修正（M2）----
                # 只修“交付帧”，不碰衔接头；窗口/上下限都能调，方便不同题材微调。
                "seam_enabled": ("BOOLEAN", {"default": True,
                                             "tooltip": "是否自动修正段间曝光/亮度跳变"}),
                "seam_window": ("INT", {"default": seam.WINDOW_DEFAULT, "min": 2, "max": 48,
                                        "tooltip": "参与比较的帧数"}),
                "seam_max_add": ("FLOAT", {"default": seam.MAX_ADD_DEFAULT, "min": 0.0,
                                           "max": 0.5, "step": 0.01,
                                           "tooltip": "允许的亮度偏移上限"}),
                "seam_gain_limit": ("FLOAT", {"default": seam.GAIN_LIMIT_DEFAULT, "min": 0.0,
                                              "max": 0.2, "step": 0.005,
                                              "tooltip": "允许的增益偏差上限"}),
                # ---- 分辨率预设（追加在最后，保持旧控件顺序不变）----
                # 选 480p/720p/768p/1080p 时用预设尺寸，宽高控件会被忽略；
                # 选“自定义”时才用上面的 width/height。
                "resolution": (list(frames.RESOLUTION_OPTIONS), {
                    "default": frames.RESOLUTION_CUSTOM,
                    "tooltip": "分辨率预设：480p/720p/768p/1080p（已对齐 32 倍数）；自定义=用宽高"}),
                "aspect_ratio": (list(frames.ASPECT_RATIOS), {
                    "default": frames.ASPECT_RATIOS[0],
                    "tooltip": "画面比例：16:9 横屏 / 9:16 竖屏 / 1:1 方形"}),
            },
            "optional": {
                "output_dir": ("STRING", {"default": "DirectorDeck"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 配置一变，下游所有节点都应该重算；配置没变则复用。
        return hashlib.sha1(json.dumps(kwargs, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    def build(self, width, height, segment_seconds, handoff_frames, sampler_name,
              scheduler, steps, denoise, sigmas_string, interpolate_to_steps,
              seed_strategy, seed_base, preview, vram_policy, cleanup_segments,
              output_dir="DirectorDeck", seam_enabled=True,
              seam_window=seam.WINDOW_DEFAULT, seam_max_add=seam.MAX_ADD_DEFAULT,
              seam_gain_limit=seam.GAIN_LIMIT_DEFAULT,
              resolution=frames.RESOLUTION_CUSTOM,
              aspect_ratio=frames.ASPECT_RATIOS[0]):
        # 画布硬约束先拦住：预设已经对齐 32；自定义宽高不是 32 倍数直接报错。
        canvas_w, canvas_h = frames.resolve_canvas(
            width, height, resolution, aspect_ratio)
        config = {
            "schema": "DIRECTOR_CONFIG@1",
            "width": int(canvas_w),
            "height": int(canvas_h),
            "resolution": str(resolution),
            "aspect_ratio": str(aspect_ratio),
            "fps": FPS,  # 锁死 24，不允许用户改
            "segment_seconds": float(segment_seconds),
            # 衔接帧吸附到 5/22/39/56，用户填 1~56 都能接受。
            "handoff_frames": frames.context_frames_for(handoff_frames),
            "sampler_name": str(sampler_name),
            "scheduler": str(scheduler),
            "steps": int(steps),
            "denoise": float(denoise),
            "sigmas_string": str(sigmas_string or "").strip(),
            "interpolate_to_steps": int(interpolate_to_steps),
            "seed_strategy": str(seed_strategy),
            "seed_base": int(seed_base),
            "preview": bool(preview),
            "vram_policy": str(vram_policy),
            "cleanup_segments": str(cleanup_segments),
            "output_dir": str(output_dir or "DirectorDeck"),
            "seam_enabled": bool(seam_enabled),
            "seam_window": int(seam_window),
            "seam_max_add": float(seam_max_add),
            "seam_gain_limit": float(seam_gain_limit),
        }
        return (config,)
