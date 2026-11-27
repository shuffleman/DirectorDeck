"""DirectorDeck · 二采工具（M3）。

两种模式：
1. `latent_2nd`（真正的二采）：把成片帧重新编码回 H3 的 AV latent，
   用低 denoise（默认 0.2）+ 少量步数再采一次，画面细节会被模型“再修一遍”；
   音频流会被锁住（mask=0），保证音轨不变。
2. `lanczos2x`：纯图像放大（快、稳，适合先要个大图）。

为什么二采要重新编码？
因为 H3 的 latent 里带了音视频两条流和确定的时序栅格，拿像素帧重新编码
是唯一能“回到模型空间再修”的正路；直接放大图片并不经过模型。
"""

from __future__ import annotations

import hashlib
import json

import comfy.utils
import torch

from ..adapters import av_latent, h3
from ..core import frames
from ..core.types import CATEGORY, TYPE_BUNDLE, TYPE_SEGMENT, error

MODES = ["latent_2nd", "lanczos2x"]


class DirectorDeckRefiner:
    """二次优化：低 denoise 再采样（或快速放大）。"""

    CATEGORY = f"{CATEGORY}/后处理"
    FUNCTION = "refine"
    RETURN_TYPES = (TYPE_SEGMENT, "IMAGE", "AUDIO")
    RETURN_NAMES = ("segment", "images", "audio")
    DESCRIPTION = ("二采：把成片编码回 AV latent，低 denoise 再采样一遍修细节，"
                   "音频流锁定不变；也可以只做 lanczos 放大。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "bundle": (TYPE_BUNDLE, {"tooltip": "模型组合（和生成时同一套）"}),
                "segment": (TYPE_SEGMENT, {"tooltip": "要二采的段（来自视频生成器）"}),
                "images": ("IMAGE", {"tooltip": "该段画面"}),
                "audio": ("AUDIO", {"tooltip": "该段音轨（二采后保持不变）"}),
            },
            "optional": {
                "mode": (MODES, {"default": "latent_2nd"}),
                "denoise": ("FLOAT", {"default": 0.2, "min": 0.01, "max": 0.9, "step": 0.01,
                                      "tooltip": "二采去噪强度；越低越接近原片"}),
                "steps": ("INT", {"default": 4, "min": 1, "max": 30}),
                "sampler_name": (["er_sde", "euler", "dpmpp_2m"], {"default": "er_sde"}),
                "scheduler": (["beta", "normal", "karras"], {"default": "beta"}),
                "upscale": ("FLOAT", {"default": 2.0, "min": 1.0, "max": 4.0, "step": 0.25,
                                      "tooltip": "lanczos2x 模式的放大倍数"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, segment=None, **kwargs):
        key = dict(kwargs)
        key["segment_seed"] = (segment or {}).get("seed")
        key["segment_store_key"] = (segment or {}).get("store_key")
        return hashlib.sha1(json.dumps(key, sort_keys=True, default=str)
                            .encode("utf-8")).hexdigest()

    @staticmethod
    def _upscale_images(images, scale: float):
        """用 comfy 的通用放大做 lanczos（不做模型推理，快）。"""
        height, width = int(images.shape[1]), int(images.shape[2])
        target_w = max(32, int(round(width * scale / 32) * 32))
        target_h = max(32, int(round(height * scale / 32) * 32))
        scaled = comfy.utils.common_upscale(images.detach().movedim(-1, 1),
                                            target_w, target_h, "lanczos", "center")
        return scaled.movedim(1, -1)

    def refine(self, bundle, segment, images, audio, mode="latent_2nd",
               denoise=0.2, steps=4, sampler_name="er_sde", scheduler="beta",
               upscale=2.0):
        frame_count = int(images.shape[0])
        frames.validate_length(frame_count)

        # ---- 快速路径：只放大，不经过模型 ----
        if mode == "lanczos2x":
            out_images = self._upscale_images(images, float(upscale))
            out = dict(segment or {})
            out.update({"refined": True,
                        "refine": {"mode": mode, "scale": float(upscale)}})
            return (out, out_images, audio)

        # ---- 真二采：编码 -> 低 denoise 再采样 -> 解码 ----
        height, width = int(images.shape[1]), int(images.shape[2])
        template = av_latent.template_shapes(width, height, frame_count)
        cond, _latent = h3.build_conditioning(
            bundle, mode="t2va", prompt=str((segment or {}).get("prompt") or ""),
            width=width, height=height, length=frame_count)
        video = av_latent.encode_video_latent(bundle["video_vae"], images, template)
        audio_latent = av_latent.encode_audio_latent(
            bundle["audio_vae"], audio["waveform"], audio["sample_rate"],
            template["audio_t"])
        # 视频 mask=1（允许采样器修）、音频 mask=0（锁死不修）。
        packed = av_latent.pack_av(video, audio_latent,
                                   torch.ones_like(video), torch.zeros_like(audio_latent))
        sampled = h3.sample(
            bundle, cond, packed,
            seed=int((segment or {}).get("seed") or 0),
            sampler_name=sampler_name, scheduler=scheduler,
            steps=int(steps), denoise=float(denoise),
            sigmas_string=None, interpolate_to_steps=0)
        sampled = av_latent.restore_audio(sampled, audio_latent)
        out_images = h3.decode_video(bundle, sampled)
        out_audio = h3.decode_audio(bundle, sampled)
        out = dict(segment or {})
        out.update({
            "refined": True,
            "refine": {"mode": mode, "denoise": float(denoise),
                       "steps": int(steps), "sampler": sampler_name,
                       "scheduler": scheduler},
        })
        return (out, out_images, out_audio)
