"""DirectorDeck · 模型加载器（M1）。

这是整条链的“片场电源”：主干、文本编码器、视频/音频 VAE、LoRA、flow shift 全在这里配。
规矩只有一条：**模型只能在链首指定**，后面段落不许换模型（换模型 = 换一条链）。
"""

from __future__ import annotations

import hashlib
import json

import folder_paths

from ..adapters import h3
from ..core.types import CATEGORY, TYPE_BUNDLE

# 权重精度选项。fp8 能省显存，但画质/稳定性略降，默认交给用户自己掂量。
WEIGHT_DTYPES = ["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"]

# 显存档位：目前只是记录在 bundle 里（M2 会按档位调整卸载策略），不影响加载。
VRAM_TIERS = ["auto", "16G", "12G", "8G"]


def _list(kind: str, with_none: bool = False) -> list[str]:
    """列出某类模型文件；ComfyUI 没扫到文件时返回空列表（面板会显示为空，不崩）。"""
    names = list(folder_paths.get_filename_list(kind))
    names.sort()
    return (["none"] + names) if with_none else names


class DirectorDeckModelLoader:
    """加载 H3 模型组合，输出 DIRECTOR_BUNDLE。"""

    CATEGORY = f"{CATEGORY}/加载"
    FUNCTION = "load"
    RETURN_TYPES = (TYPE_BUNDLE,)
    RETURN_NAMES = ("bundle",)
    DESCRIPTION = ("加载 MiniMax H3 模型组合：fl2va/ref2va 主干、文本编码器、视频/音频 VAE、"
                   "最多 4 个 LoRA、SigmaShift。模型只应在本节点（链首）指定。")

    @classmethod
    def INPUT_TYPES(cls):
        diffusion_models = _list("diffusion_models")
        text_encoders = _list("text_encoders")
        vaes = _list("vae")
        loras = _list("loras", with_none=True)
        return {
            "required": {
                "fl2va_model": (diffusion_models, {"tooltip": "H3 主干（T2VA/I2VA/FL2VA/Ref2VA 共用；本机为 fused 模型）"}),
                "text_encoder": (text_encoders, {"tooltip": "H3 文本编码器（Qwen3-VL）"}),
                "video_vae": (vaes, {"tooltip": "视频 VAE"}),
                "audio_vae": (vaes, {"tooltip": "音频 VAE"}),
                "weight_dtype": (WEIGHT_DTYPES, {"default": "default"}),
                "vram_tier": (VRAM_TIERS, {"default": "auto"}),
            },
            "optional": {
                # 本机只有一个 fused 主干，所以 ref2va 默认可不填（与 fl2va 共用）。
                "ref2va_model": (["none"] + diffusion_models,
                                 {"tooltip": "可选：Ref2VA 专用主干；none=与 fl2va 共用"}),
                # 4 组 LoRA 是“追加式”参数：以后想加更多，只能往后追加，不能改已有顺序。
                "lora_1": (loras, {"default": "none"}),
                "strength_1": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                "lora_2": (loras, {"default": "none"}),
                "strength_2": ("FLOAT", {"default": 0.5, "min": -100.0, "max": 100.0, "step": 0.01}),
                "lora_3": (loras, {"default": "none"}),
                "strength_3": ("FLOAT", {"default": 0.3, "min": -100.0, "max": 100.0, "step": 0.01}),
                "lora_4": (loras, {"default": "none"}),
                "strength_4": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                "shift_video": ("FLOAT", {"default": 12.0, "min": 0.01, "max": 100.0, "step": 0.01,
                                          "tooltip": "H3 视频 flow shift（13 号默认 12）"}),
                "shift_audio": ("FLOAT", {"default": 3.0, "min": 0.01, "max": 100.0, "step": 0.01,
                                          "tooltip": "H3 音频 flow shift（13 号默认 3）"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        """参数一变就重新加载；参数没变时 ComfyUI 会复用缓存结果，不会重复吃 42GB。"""
        return hashlib.sha1(json.dumps(kwargs, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    def load(self, fl2va_model, text_encoder, video_vae, audio_vae,
             weight_dtype="default", vram_tier="auto", ref2va_model="none",
             lora_1="none", strength_1=1.0, lora_2="none", strength_2=0.5,
             lora_3="none", strength_3=0.3, lora_4="none", strength_4=1.0,
             shift_video=12.0, shift_audio=3.0):
        # 四个槽里填了非 none 的才进 LoRA 列表，顺序保持用户接线顺序。
        loras = []
        for name, strength in ((lora_1, strength_1), (lora_2, strength_2),
                               (lora_3, strength_3), (lora_4, strength_4)):
            if name and name != "none":
                loras.append({"name": name, "strength": float(strength)})
        spec = {
            "fl2va_model": fl2va_model,
            "ref2va_model": None if ref2va_model in ("none", "", None) else ref2va_model,
            "text_encoder": text_encoder,
            "video_vae": video_vae,
            "audio_vae": audio_vae,
            "weight_dtype": weight_dtype,
            "vram_tier": vram_tier,
            "loras": loras,
            "shift_video": float(shift_video),
            "shift_audio": float(shift_audio),
        }
        return (h3.load_bundle(spec),)
