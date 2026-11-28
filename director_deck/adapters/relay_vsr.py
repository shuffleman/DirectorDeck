"""RelayVSR 2x 视频超分适配。

RelayVSR 是 ComfyUI 核心能力：用扩散模型每 15 帧抽一次关键帧、Flash VAE 重建全部帧，
输出 2x 分辨率（也有 x4 变体）。它只处理画面，音频始终由调用方保留原轨。

这里不依赖第三方节点包，直接用 ComfyUI 自带的 UNETLoader / VAELoader /
RelayVSRConditioning / KSampler / VSRDecode，方便在 DirectorDeck 里复用。
"""

from __future__ import annotations

import importlib
import os
import re

import folder_paths
import torch

try:  # 运行期在 ComfyUI 里一定有；单测环境允许缺
    import comfy.model_management
except Exception:  # pragma: no cover
    comfy = None

_CACHE: dict[tuple[str, str], "RelayVSRRunner"] = {}


def _relay_names(category: str) -> list[str]:
    try:
        names = list(folder_paths.get_filename_list(category) or [])
    except Exception:
        return []
    result = []
    for name in names:
        compact = str(name or "").replace("\\", "/").lower()
        if "relayvsr" in compact or "relay_vsr" in compact:
            result.append(str(name))
    return sorted(dict.fromkeys(result), key=lambda value: value.lower())


def model_choices() -> list[str]:
    choices = _relay_names("diffusion_models")
    return choices or ["(没有找到 RelayVSR 放大模型)"]


def vae_choices() -> list[str]:
    choices = _relay_names("vae")
    return choices or ["(没有找到 RelayVSR Flash VAE)"]


def scale_of(name: str) -> int | None:
    """从文件名里读 x2/x4；读不到返回 None。"""
    base = os.path.basename(str(name or "").replace("\\", "/")).lower()
    matches = re.findall(r"(?:^|[_-])x([24])(?=[._-]|$)", base)
    if not matches:
        matches = re.findall(r"x([24])", base)
    return int(matches[-1]) if matches else None


def default_model() -> str:
    choices = model_choices()
    for name in choices:
        if scale_of(name) == 2 and "lightx2v" in name.lower():
            return name
    for name in choices:
        if scale_of(name) == 2:
            return name
    return choices[0]


def default_vae(model_name: str) -> str:
    choices = vae_choices()
    wanted = scale_of(model_name)
    if wanted is not None:
        for name in choices:
            if scale_of(name) == wanted:
                return name
    for name in choices:
        if scale_of(name) == 2:
            return name
    return choices[0]


def _require(name: str, choices: list[str], label: str) -> str:
    value = str(name or "").strip()
    if not value or value.startswith("(") or value not in choices:
        raise ValueError(f"{label}无效：{value!r}；当前可选：{', '.join(choices)}")
    return value


def _fit_count(frames: torch.Tensor, count: int) -> torch.Tensor:
    if frames.shape[0] > count:
        return frames[:count]
    if frames.shape[0] < count:
        pad = frames[-1:].repeat(count - frames.shape[0], 1, 1, 1)
        return torch.cat([frames, pad], dim=0)
    return frames


def _lock_exposure(output: torch.Tensor, source: torch.Tensor) -> torch.Tensor:
    """把超分后的每帧亮度按低清原片锁回去，避免整片曝光漂移。"""
    result = output.clone()
    for index in range(result.shape[0]):
        ref = source[index]
        ref_luma = (ref[..., 0] * 0.2126 + ref[..., 1] * 0.7152
                    + ref[..., 2] * 0.0722).mean().clamp_min(1e-4)
        out = result[index]
        out_luma = (out[..., 0] * 0.2126 + out[..., 1] * 0.7152
                    + out[..., 2] * 0.0722).mean().clamp_min(1e-4)
        gain = (ref_luma / out_luma).clamp(0.85, 1.18)
        result[index] = (out * gain).clamp(0.0, 1.0)
    return result


class RelayVSRRunner:
    """加载一套 RelayVSR 模型/Flash VAE，并复用到多帧。"""

    def __init__(self, model_name: str, vae_name: str, *, detail: float = 0.5,
                 lock_exposure: bool = True):
        self.model_name = _require(model_name, model_choices(), "RelayVSR 模型")
        self.vae_name = _require(vae_name, vae_choices(), "RelayVSR Flash VAE")
        model_scale = scale_of(self.model_name)
        vae_scale = scale_of(self.vae_name)
        if model_scale is not None and vae_scale is not None and model_scale != vae_scale:
            raise ValueError(f"RelayVSR 模型是 x{model_scale}，VAE 是 x{vae_scale}；两者倍数必须一致")
        self.detail = max(0.0, min(1.0, float(detail)))
        self.lock_exposure = bool(lock_exposure)

        core_nodes = importlib.import_module("nodes")
        loaded_model = core_nodes.UNETLoader().load_unet(self.model_name, "default")
        self.model = loaded_model[0] if isinstance(loaded_model, (tuple, list)) else loaded_model
        loaded_vae = core_nodes.VAELoader().load_vae(self.vae_name)
        self.vae = loaded_vae[0] if isinstance(loaded_vae, (tuple, list)) else loaded_vae
        print(f"[DirectorDeck RelayVSR] 已加载 {self.model_name} + {self.vae_name}"
              f"（细节 {self.detail:.2f}，锁曝光 {'开' if self.lock_exposure else '关'}）")

    def enhance(self, frames: torch.Tensor) -> torch.Tensor:
        source = frames.detach().float().cpu()
        if source.ndim == 3:
            source = source.unsqueeze(0)
        if source.shape[-1] > 3:
            source = source[..., :3]
        original_count = int(source.shape[0])

        with torch.inference_mode():
            from comfy_extras.nodes_wan import RelayVSRConditioning, VSRDecode
            core_nodes = importlib.import_module("nodes")
            conditioning = RelayVSRConditioning.execute(self.model, source)
            values = getattr(conditioning, "result", conditioning)
            if not isinstance(values, (tuple, list)) or len(values) < 2:
                raise RuntimeError("RelayVSR 条件节点没有返回 positive / latent")
            positive, latent = values[0], values[1]
            sampled = core_nodes.KSampler().sample(
                self.model, 0, 1, 1.0, "euler", "simple",
                positive, positive, latent, 1.0)
            sampled = sampled[0] if isinstance(sampled, (tuple, list)) else sampled
            decoded_out = VSRDecode.execute(self.vae, sampled, source, detail=self.detail)
            decoded = getattr(decoded_out, "result", decoded_out)
            if isinstance(decoded, (tuple, list)):
                decoded = decoded[0]
            if isinstance(decoded, torch.Tensor):
                decoded = decoded.detach().float().cpu()
        decoded = _fit_count(decoded, original_count)
        if self.lock_exposure:
            with torch.inference_mode():
                decoded = _lock_exposure(decoded, source)
        return decoded


def get_runner(model_name: str, vae_name: str, *, detail: float = 0.5,
               lock_exposure: bool = True) -> RelayVSRRunner:
    key = (str(model_name), str(vae_name))
    runner = _CACHE.get(key)
    if runner is None:
        runner = RelayVSRRunner(model_name, vae_name, detail=detail,
                                lock_exposure=lock_exposure)
        _CACHE[key] = runner
    else:
        runner.detail = max(0.0, min(1.0, float(detail)))
        runner.lock_exposure = bool(lock_exposure)
    return runner
