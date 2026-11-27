"""MiniMax H3 适配层：全库唯一“贴着 ComfyUI 内核”的地方。

为什么要有这一层？
- 内核的加载/采样/解码函数说改就改（我们的工作流就踩过版本升级）；
- 把所有“内核细节”关在这一个文件里，将来升级只改这里，nodes/core 不用动；
- 这里可以 import ComfyUI 的东西，但 core/ 绝不允许。

内核依据（ComfyUI 0.46 实测）：
- 加载：comfy.sd.load_clip(CLIPType.MINIMAX) / comfy.sd.VAE / comfy.sd.load_diffusion_model；
- 条件：comfy_extras.nodes_minimax_h3 的 ImageToVideo / ReferenceToVideo / AddGuide；
- 采样：nodes_custom_sampler.Guider_Basic + comfy.samplers.sampler_object（和
  SamplerCustomAdvanced 等价，只是省掉画布上五个节点）；
- 解码：nodes.VAEDecode（会自动处理打包 AV latent 的视频流）/ nodes_audio.vae_decode_audio。
"""

from __future__ import annotations

import hashlib
import json
import random
import time

import numpy as np
import torch

import comfy.model_management
import comfy.sample
import comfy.samplers
import comfy.sd
import comfy.utils
import folder_paths
import nodes
from comfy_extras import nodes_audio, nodes_custom_sampler
from comfy_extras import nodes_minimax_h3 as h3

from ..core.types import error

# 同一个进程里重复加载同一套模型很亏（42GB 呢），所以按 spec 指纹缓存一份。
BUNDLE_CACHE: dict[str, dict] = {}


# ---------------------------------------------------------------- 加载
def _resolve(kind: str, name: str) -> str:
    """按模型目录类型（diffusion_models/text_encoders/vae/loras）找绝对路径。"""
    return folder_paths.get_full_path_or_raise(kind, name)


def load_clip(name: str):
    """加载 H3 的文本编码器（Qwen3-VL），类型必须选 MINIMAX，否则 tokenizer 不对。"""
    path = _resolve("text_encoders", name)
    return comfy.sd.load_clip(
        ckpt_paths=[path],
        embedding_directory=folder_paths.get_folder_paths("embeddings"),
        clip_type=comfy.sd.CLIPType.MINIMAX,
    )


def load_vae(name: str):
    """加载 VAE（视频/音频都用它，只是文件不同）。"""
    path = _resolve("vae", name)
    sd, metadata = comfy.utils.load_torch_file(path, return_metadata=True)
    vae = comfy.sd.VAE(sd=sd, metadata=metadata)
    vae.throw_exception_if_invalid()
    return vae


def load_unet(name: str, weight_dtype: str = "default"):
    """加载扩散主干。weight_dtype 支持 fp8 量化权重（省显存）。"""
    model_options = {}
    if weight_dtype in ("fp8_e4m3fn", "fp8_e4m3fn_fast"):
        model_options["dtype"] = torch.float8_e4m3fn
        if weight_dtype.endswith("_fast"):
            model_options["fp8_optimizations"] = True
    elif weight_dtype == "fp8_e5m2":
        model_options["dtype"] = torch.float8_e5m2
    return comfy.sd.load_diffusion_model(_resolve("diffusion_models", name),
                                         model_options=model_options)


def apply_lora(model, lora_name: str, strength: float):
    """给主干叠 LoRA（只影响模型，不动 CLIP —— H3 的 LoRA 一般都是模型侧）。"""
    path = _resolve("loras", lora_name)
    lora, metadata = comfy.utils.load_torch_file(path, safe_load=True, return_metadata=True)
    model, _clip = comfy.sd.load_lora_for_models(model, None, lora, float(strength), 0,
                                                 lora_metadata=metadata)
    return model


def apply_sigma_shift(model, shift_video: float = 12.0, shift_audio: float = 3.0):
    """给模型挂 H3 的 flow shift（13 号工作流的 12/3 就是它）。"""
    out = h3.MiniMaxH3SigmaShift.execute(model=model, shift_video=float(shift_video),
                                        shift_audio=float(shift_audio))
    return out.result[0]


def bundle_id(spec: dict) -> str:
    """模型组合指纹：只要路径/权重类型/LoRA/shift 有变化，就会重新加载。"""
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha1:" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def load_bundle(spec: dict) -> dict:
    """按 spec 加载一整套模型，返回 bundle 字典（模型对象直接放里面）。

    注意：这个 bundle 只在“同一进程”里有效，跨节点传的是 Python 对象，
    ComfyUI 允许这么干（模型加载器的输出本来就是对象）。
    """
    key = bundle_id(spec)
    if key in BUNDLE_CACHE:
        return BUNDLE_CACHE[key]

    clip = load_clip(spec["text_encoder"])
    video_vae = load_vae(spec["video_vae"])
    audio_vae = load_vae(spec["audio_vae"])
    # 本机只有一个 fused 主干，fl2va/ref2va 共用；将来有独立 ref2va 模型再分流。
    model_name = spec.get("fl2va_model") or spec.get("ref2va_model") or spec.get("model")
    model = load_unet(model_name, spec.get("weight_dtype", "default"))
    for lora in spec.get("loras") or []:
        model = apply_lora(model, lora["name"], float(lora.get("strength", 1.0)))
    model = apply_sigma_shift(model, spec.get("shift_video", 12.0),
                              spec.get("shift_audio", 3.0))

    bundle = {
        "spec": dict(spec),
        "bundle_id": key,
        "model": model,
        "clip": clip,
        "video_vae": video_vae,
        "audio_vae": audio_vae,
    }
    BUNDLE_CACHE[key] = bundle
    print(f"[DirectorDeck] bundle loaded: {model_name} (id={key[:16]}…)")
    return bundle


# ---------------------------------------------------------------- 条件
def build_conditioning(bundle: dict, *, mode: str, prompt: str, width: int, height: int,
                       length: int, ref_images: list | None = None,
                       first_frame=None, last_frame=None):
    """构造条件 + 空 latent。mode 决定用哪个内核节点。

    - ref2va：参考生视频，喂 1~9 张参考图（带 @图片N 的提示词会变成 <Picture N>）；
    - 其它（t2va/i2va/fl2va）：文生视频/首帧/首尾帧，用的是同一个 ImageToVideo 节点。
    返回值 (conditioning, latent)，latent 是 H3 的“打包音视频”结构。
    """
    if mode == "ref2va":
        refs = {f"ref_image_{i}": image for i, image in enumerate(ref_images or [])}
        if not refs:
            raise error("DD-E011", "参考生视频模式需要至少 1 张参考图")
        out = h3.MiniMaxH3ReferenceToVideo.execute(
            clip=bundle["clip"], prompt=prompt, width=int(width), height=int(height),
            length=int(length), ref_image_size="match",
            vae=bundle["video_vae"], audio_vae=bundle["audio_vae"], ref_images=refs)
    else:
        out = h3.MiniMaxH3ImageToVideo.execute(
            clip=bundle["clip"], vae=bundle["video_vae"], prompt=prompt,
            width=int(width), height=int(height), length=int(length),
            first_frame=first_frame, last_frame=last_frame)
    # V3 节点的 execute 返回 NodeOutput，.result 就是它返回的参数元组。
    cond, latent = out.result[0], out.result[1]
    return cond, latent


def add_guide(bundle: dict, cond, latent, *, image=None, audio=None, frame_idx: int = 0):
    """把图片/音频“钉”到某一帧（M2 的尾帧续写、数字人锁音都靠它）。"""
    out = h3.MiniMaxH3AddGuide.execute(
        positive=cond, latent=latent, frame_idx=int(frame_idx),
        vae=bundle["video_vae"], audio_vae=bundle["audio_vae"],
        image=image, audio=audio)
    return out.result[0]


# ---------------------------------------------------------------- 采样
def sigmas_from_string(sigmas_string: str, interpolate_to_steps: int = 0):
    """把 `1.0, 0.97, 0.92, 0.8, 0.57, 0.33, 0.0` 这种字符串变成 sigma 张量。

    interpolate_to_steps > 0 且数量不匹配时，在 log 空间插值（sigma 是对数尺度的，
    线性插值会把手感带偏）。最后一个点强制 0，保证采样能降到干净。
    """
    values = [float(part) for part in str(sigmas_string).replace(";", ",").split(",")
              if part.strip()]
    if len(values) < 2:
        raise error("DD-E004", "sigmas_string 至少需要 2 个 sigma 值")
    if interpolate_to_steps and interpolate_to_steps > 0 and len(values) != interpolate_to_steps + 1:
        n = int(interpolate_to_steps)
        xs = np.linspace(0.0, 1.0, len(values))
        ys = np.log(np.maximum(np.asarray(values, dtype=np.float64), 1e-6))
        xn = np.linspace(0.0, 1.0, n + 1)
        values = np.exp(np.interp(xn, xs, ys)).tolist()
        values[-1] = 0.0
    return torch.tensor(values, dtype=torch.float32)


def calculate_sigmas(model, scheduler: str, steps: int, denoise: float,
                     sigmas_string: str | None = None,
                     interpolate_to_steps: int = 0):
    """算本次采样的 sigma 表。

    优先用自定义 sigma 字符串（13 号同款）；没给就按 scheduler+steps+denoise 算，
    denoise<1 的处理和官方 BasicScheduler 完全一致（尾部截断）。
    """
    if sigmas_string:
        sigmas = sigmas_from_string(sigmas_string, interpolate_to_steps)
        return sigmas.cpu()
    steps = max(1, int(steps))
    denoise = min(1.0, max(0.0, float(denoise)))
    model_sampling = model.get_model_object("model_sampling")
    if denoise >= 1.0:
        return comfy.samplers.calculate_sigmas(model_sampling, scheduler, steps).cpu()
    if denoise <= 0.0:
        return torch.FloatTensor([])
    total_steps = max(steps, int(steps / denoise))
    sigmas = comfy.samplers.calculate_sigmas(model_sampling, scheduler, total_steps)
    return sigmas[-(steps + 1):].cpu()


def sample(bundle: dict, cond, latent, *, seed: int, sampler_name: str = "er_sde",
           scheduler: str = "beta", steps: int = 10, denoise: float = 1.0,
           sigmas_string: str | None = None, interpolate_to_steps: int = 0,
           on_step=None):
    """跑一次采样。等价于官方那五个采样节点串起来，但只暴露一个函数。

    on_step(已完成步数, 总步数) 给节点层做进度/日志用。
    """
    model = bundle["model"]
    sigmas = calculate_sigmas(model, scheduler, steps, denoise,
                              sigmas_string, interpolate_to_steps)
    total_steps = max(1, len(sigmas) - 1)

    # seed=0 表示“随机”，随机范围对齐官方 RandomNoise（64 位）。
    seed = int(seed) & 0xFFFFFFFFFFFFFFFF
    if seed == 0:
        roll = getattr(comfy.model_management, "roll_inference_rng", None)
        seed = (int(roll()) if callable(roll) else random.randint(0, 0xFFFFFFFFFFFFFFFF))
        seed &= 0xFFFFFFFFFFFFFFFF

    noise = comfy.sample.prepare_noise(latent["samples"], seed)
    sampler = comfy.samplers.sampler_object(sampler_name)
    guider = nodes_custom_sampler.Guider_Basic(model)
    guider.set_conds(cond)

    work = latent.copy()
    pbar = comfy.utils.ProgressBar(total_steps)
    started = time.perf_counter()
    state = {"done": 0}

    def _callback(*args):
        # 官方采样回调会传一堆东西，我们只关心“走到第几步”。
        state["done"] += 1
        if on_step is not None:
            try:
                on_step(state["done"], total_steps)
            except Exception:
                pass
        pbar.update_absolute(state["done"], total_steps, None)
        print(f"[DirectorDeck] 采样 {state['done']}/{total_steps} "
              f"({time.perf_counter() - started:.1f}s)")

    samples = guider.sample(
        noise, work["samples"], sampler, sigmas,
        denoise_mask=work.get("noise_mask"),
        callback=_callback, disable_pbar=False, seed=seed,
    )
    samples = samples.to(comfy.model_management.intermediate_device())

    # 把采样结果放回 latent 结构（保留 mask 等元信息，方便 M2 二采继续用）。
    out = work.copy()
    out.pop("downscale_ratio_spacial", None)
    out.pop("downscale_ratio_temporal", None)
    out["samples"] = samples
    out["_director_seed"] = seed
    out["_director_sigmas"] = sigmas.tolist()
    return out


# ---------------------------------------------------------------- 解码
def decode_video(bundle: dict, latent: dict):
    """解码成 IMAGE 张量 [N,H,W,3]。VAEDecode 会自动取打包 latent 的视频流。"""
    images = nodes.VAEDecode().decode(bundle["video_vae"], latent)[0]
    return images


def decode_audio(bundle: dict, latent: dict):
    """解码成 AUDIO 字典 {"waveform": [B,C,S], "sample_rate": int}。"""
    return nodes_audio.vae_decode_audio(bundle["audio_vae"], latent)


def frame_count(latent: dict) -> int:
    """数一下视频流有多少帧（调试用）。"""
    samples = latent["samples"]
    if hasattr(samples, "is_nested") and samples.is_nested:
        samples = samples.unbind()[0]
    # H3 视频 latent 的时间维在 dim=2
    return int(samples.shape[2])
