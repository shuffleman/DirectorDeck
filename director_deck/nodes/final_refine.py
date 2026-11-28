"""二次处理成片节点（最终精修/超分/封装）。

为什么单独做一个节点，而不是塞进 FinalCut：
- FinalCut 只负责“把段拼起来”，二采/超分往往要反复试参数，单独节点更清晰；
- 二采和 RelayVSR 都很吃显存，先在合并器里手动合并，再在最终节点里“点击生成”，
  中间可以反复预览、换 LoRA、换处理模式，不会每次都重跑上游分段。

手动触发沿用 FinalCut 的 token 门闩：普通排队只跳过本节点，点节点上的
“🎬 生成最终视频”按钮（run_token +1）才真正处理并保存成片。
"""

from __future__ import annotations

import json
import os
import time

import folder_paths
import torch
import torch.nn.functional as torch_functional

try:
    import comfy.model_management
    import comfy.utils
except Exception:  # pragma: no cover
    comfy = None

from ..adapters import av_latent, h3
from ..adapters import preview as preview_lib
from ..adapters import relay_vsr
from ..core import frames
from ..core.types import CATEGORY, FPS, TYPE_BUNDLE, TYPE_CONFIG, TYPE_SEGMENT

try:  # 手动态阻断下游（本节点是输出节点，阻断后静默跳过保存）
    from comfy_execution.graph_utils import ExecutionBlocker
except Exception:  # pragma: no cover
    ExecutionBlocker = None


MODES = [
    "关闭（只重新封装）",
    "潜空间二采",
    "RelayVSR 2x",
    "潜空间二采 + RelayVSR 2x",
    "Lanczos 放大",
]

SAMPLERS = ["er_sde", "euler", "dpmpp_2m", "dpmpp_2m_sde"]
SCHEDULERS = ["beta", "normal", "karras", "simple"]

# 每个最终处理节点的“上次已执行 token”；和 FinalCut 同一套手动门闩。
_RUN_TOKENS: dict[str, int] = {}


def _lora_choices() -> list[str]:
    try:
        names = list(folder_paths.get_filename_list("loras") or [])
    except Exception:
        names = []
    return ["none", *names]


def _pad_frames(images: torch.Tensor, target: int) -> torch.Tensor:
    """二采需要 17k+5 帧；多段合并后的总帧数偶尔不在栅格上，用尾帧补齐。"""
    count = int(images.shape[0])
    if count >= target:
        return images[:target]
    pad = images[-1:].repeat(target - count, 1, 1, 1)
    return torch.cat([images, pad], dim=0)


def _pad_audio(audio: dict, target_samples: int) -> dict:
    waveform = audio["waveform"].detach().float().cpu()
    if waveform.ndim == 2:
        waveform = waveform.unsqueeze(0)
    have = int(waveform.shape[-1])
    if have < target_samples:
        waveform = torch_functional.pad(waveform, (0, target_samples - have))
    elif have > target_samples:
        waveform = waveform[..., :target_samples]
    return {"waveform": waveform,
            "sample_rate": int(audio.get("sample_rate", 48000))}


def _resize(images: torch.Tensor, width: int, height: int) -> torch.Tensor:
    scaled = comfy.utils.common_upscale(
        images.detach().movedim(-1, 1), int(width), int(height), "lanczos", "center")
    return scaled.movedim(1, -1).clamp(0.0, 1.0)


class DirectorDeckFinalRefine:
    """最终成片：手动点击后做二采/RelayVSR/放大，并直接保存最终 mp4。"""

    CATEGORY = f"{CATEGORY}/后期"
    FUNCTION = "finalize"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "AUDIO", "STRING")
    RETURN_NAMES = ("images", "audio", "report")
    DESCRIPTION = ("合并完成后的最终处理：潜空间二采（可叠二采 LoRA）/ RelayVSR 2x / "
                   "Lanczos 放大，保留原音轨并保存最终视频。默认手动，点节点按钮才执行。")

    @classmethod
    def INPUT_TYPES(cls):
        default_model = relay_vsr.default_model()
        return {
            "required": {
                "bundle": (TYPE_BUNDLE, {"tooltip": "和生成时同一套模型（二采用）"}),
                "images": ("IMAGE", {"tooltip": "FinalCut 输出的成片画面"}),
                "audio": ("AUDIO", {"tooltip": "FinalCut 输出的成片音轨（全程保留原音轨）"}),
                "mode": (MODES, {
                    "default": "潜空间二采",
                    "tooltip": "关闭=只重新封装；潜空间二采=低 denoise 再修一遍；RelayVSR=2x 超分"}),
                "prompt": ("STRING", {
                    "default": "电影感，细节清晰，自然皮肤质感，稳定光影，高质量成片",
                    "multiline": True,
                    "tooltip": "二采时的提示词；留空会尝试用连接的 segment 的 prompt"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                                 "tooltip": "二采种子；0=自动用 segment 种子或 12345"}),
                "latent_denoise": ("FLOAT", {
                    "default": 0.2, "min": 0.01, "max": 0.9, "step": 0.01,
                    "tooltip": "二采重绘强度；越低越接近原片"}),
                "latent_steps": ("INT", {"default": 4, "min": 1, "max": 30}),
                "latent_sampler": (SAMPLERS, {"default": "er_sde"}),
                "latent_scheduler": (SCHEDULERS, {"default": "beta"}),
                "refiner_lora": (_lora_choices(), {
                    "default": "none",
                    "tooltip": "只作用于二采的 LoRA（一采模型不受影响）"}),
                "refiner_lora_strength": ("FLOAT", {
                    "default": 1.0, "min": -2.0, "max": 2.0, "step": 0.05,
                    "tooltip": "二采 LoRA 强度"}),
                "relay_model": (relay_vsr.model_choices(), {
                    "default": default_model,
                    "tooltip": "RelayVSR 放大模型（models/diffusion_models/RelayVSR/）"}),
                "relay_vae": (relay_vsr.vae_choices(), {
                    "default": relay_vsr.default_vae(default_model),
                    "tooltip": "RelayVSR Flash VAE（必须与模型同为 x2/x4）"}),
                "relay_detail": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Flash 解码细节强度；0.5 与参考工作流一致"}),
                "relay_lock_exposure": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "把超分后每帧亮度锁回原片，避免整片曝光漂移"}),
                "lanczos_scale": ("FLOAT", {
                    "default": 2.0, "min": 1.0, "max": 4.0, "step": 0.25,
                    "tooltip": "Lanczos 模式的放大倍数"}),
                "target_width": ("INT", {
                    "default": 0, "min": 0, "max": 8192, "step": 32,
                    "tooltip": "最终目标宽度；0=保持当前；非 0 时必须和高度一起填"}),
                "target_height": ("INT", {
                    "default": 0, "min": 0, "max": 8192, "step": 32,
                    "tooltip": "最终目标高度；0=保持当前；非 0 时必须和宽度一起填"}),
                "free_vram": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "RelayVSR 前卸掉 H3 模型，降低显存峰值"}),
                "save_video": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "保存最终 mp4 到 output/<输出目录>/final/"}),
                "output_dir": ("STRING", {"default": "DirectorDeck"}),
                "filename_prefix": ("STRING", {"default": "final"}),
                "run_mode": (["手动", "自动"], {
                    "default": "手动",
                    "tooltip": "手动=点节点上的“🎬 生成最终视频”才执行；自动=每次排队都执行"}),
                "run_token": ("INT", {
                    "default": 0, "min": 0, "max": 0xFFFFFFFFFFFF,
                    "tooltip": "内部用：前端按钮 +1 触发一次"}),
            },
            "optional": {
                "segment": (TYPE_SEGMENT, {
                    "tooltip": "可选：提供二采 prompt/种子的回退来源"}),
                "config": (TYPE_CONFIG, {
                    "tooltip": "可选：沿用全局输出目录（output_dir）"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    @staticmethod
    def _gate(unique_id: str, run_mode: str, run_token: int):
        """手动门闩；返回 blocked 元组或 None。"""
        if str(run_mode or "手动") == "自动":
            return None
        if ExecutionBlocker is None:
            raise RuntimeError("手动执行需要 ComfyUI 的 ExecutionBlocker，请重启 ComfyUI")
        token = int(run_token or 0)
        uid = str(unique_id or "")
        last = _RUN_TOKENS.get(uid)
        if last is None:
            # 第一次见到这个节点：默认 token=0 先记一笔并跳过；
            # 如果 token 已经 >0，说明是按钮刚点过（首次点击也能直接执行）。
            _RUN_TOKENS[uid] = token
            if token <= 0:
                print("[DirectorDeck] 最终处理=手动：等待点击节点上的“生成最终视频”（本次跳过）")
                return (ExecutionBlocker(None), ExecutionBlocker(None), ExecutionBlocker(None))
        elif token <= last:
            print("[DirectorDeck] 最终处理=手动：token 未变化，跳过（点按钮才会执行）")
            return (ExecutionBlocker(None), ExecutionBlocker(None), ExecutionBlocker(None))
        else:
            _RUN_TOKENS[uid] = token
        return None

    def finalize(self, bundle, images, audio, mode, prompt, seed,
                 latent_denoise, latent_steps, latent_sampler, latent_scheduler,
                 refiner_lora, refiner_lora_strength, relay_model, relay_vae,
                 relay_detail, relay_lock_exposure, lanczos_scale,
                 target_width, target_height, free_vram, save_video,
                 output_dir, filename_prefix, run_mode, run_token,
                 segment=None, config=None, **kwargs):
        unique_id = str(kwargs.get("unique_id") or id(self))
        blocked = self._gate(unique_id, run_mode, run_token)
        if blocked is not None:
            return blocked

        # 统一转成 float RGB 张量；后面的处理都按 [N,H,W,3] 走。
        images = images.detach().float().cpu()
        if images.ndim == 3:
            images = images.unsqueeze(0)
        if images.shape[-1] > 3:
            images = images[..., :3]
        original_count = int(images.shape[0])
        original_width, original_height = int(images.shape[2]), int(images.shape[1])
        out_audio = audio
        sample_rate = int(audio.get("sample_rate", 48000))
        seed_value = int(seed) or int((segment or {}).get("seed") or 0) or 12345

        use_latent = "潜空间二采" in str(mode)
        use_relay = "RelayVSR" in str(mode)
        use_lanczos = "Lanczos" in str(mode)

        # 目标尺寸：二采/超分之前先按需要 resize，超分后再回锁到目标尺寸。
        target_w = int(target_width or 0)
        target_h = int(target_height or 0)
        if (target_w > 0) != (target_h > 0):
            raise ValueError("target_width / target_height 要么都填 0，要么都填非 0")
        if target_w > 0:
            frames.validate_canvas(target_w, target_h)
            images = _resize(images, target_w, target_h)

        print(f"[FinalRefine] 输入画面 mean/std={float(images.mean()):.3f}/{float(images.std()):.3f}", flush=True)
        report = {
            "mode": str(mode),
            "in_frames": original_count,
            "in_size": [original_width, original_height],
        }

        # ---- 1) 潜空间二采（H3 AV latent 低 denoise 重采样）----
        if use_latent:
            height, width = int(images.shape[1]), int(images.shape[2])
            valid_count = frames.grid_round_up(original_count)
            staged = _pad_frames(images, valid_count)
            prompt_text = str(prompt or "").strip()
            if not prompt_text:
                prompt_text = str((segment or {}).get("prompt") or "").strip()
            if not prompt_text:
                prompt_text = "电影感，细节清晰，自然皮肤质感，稳定光影，高质量成片"

            use_bundle = bundle
            if str(refiner_lora) not in ("", "none") and abs(float(refiner_lora_strength)) > 1e-6:
                patched = bundle["model"].clone()
                patched = h3.apply_lora(patched, str(refiner_lora),
                                        float(refiner_lora_strength))
                use_bundle = dict(bundle)
                use_bundle["model"] = patched
                report["refiner_lora"] = {"name": str(refiner_lora),
                                          "strength": float(refiner_lora_strength)}

            template = av_latent.template_shapes(width, height, valid_count)
            cond, _latent = h3.build_conditioning(
                use_bundle, mode="t2va", prompt=prompt_text,
                width=width, height=height, length=valid_count)
            video = av_latent.encode_video_latent(use_bundle["video_vae"], staged, template)
            padded_audio = _pad_audio(audio, int(round(valid_count / FPS * sample_rate)))
            audio_latent = av_latent.encode_audio_latent(
                use_bundle["audio_vae"], padded_audio["waveform"], sample_rate,
                template["audio_t"])
            packed = av_latent.pack_av(video, audio_latent,
                                       torch.ones_like(video), torch.zeros_like(audio_latent))
            sampled = h3.sample(
                use_bundle, cond, packed, seed=seed_value,
                sampler_name=str(latent_sampler), scheduler=str(latent_scheduler),
                steps=int(latent_steps), denoise=float(latent_denoise),
                sigmas_string=None, interpolate_to_steps=0)
            sampled = av_latent.restore_audio(sampled, audio_latent)
            refined = h3.decode_video(use_bundle, sampled)[:original_count]
            images = refined.clamp(0.0, 1.0)
            print(f"[FinalRefine] 二采后 mean/std={float(images.mean()):.3f}/{float(images.std()):.3f}", flush=True)
            # 声音全程保留原轨：二采里的 audio latent 只用于锁音，不拿来当输出。
            out_audio = audio
            report.update({
                "second_pass": True,
                "seed": seed_value,
                "denoise": float(latent_denoise),
                "steps": int(latent_steps),
                "sampler": str(latent_sampler),
                "scheduler": str(latent_scheduler),
                "prompt": prompt_text,
            })

        # ---- 2) RelayVSR 2x 超分 ----
        if use_relay:
            if bool(free_vram):
                try:
                    comfy.model_management.unload_all_models()
                    comfy.model_management.soft_empty_cache()
                except Exception:
                    pass
            runner = relay_vsr.get_runner(
                str(relay_model), str(relay_vae),
                detail=float(relay_detail),
                lock_exposure=bool(relay_lock_exposure))
            images = runner.enhance(images).clamp(0.0, 1.0)
            print(f"[FinalRefine] RelayVSR 后 mean/std={float(images.mean()):.3f}/{float(images.std()):.3f}", flush=True)
            report.update({"relay_vsr": {"model": str(relay_model),
                                         "vae": str(relay_vae),
                                         "detail": float(relay_detail),
                                         "lock_exposure": bool(relay_lock_exposure)}})
            if target_w > 0:
                images = _resize(images, target_w, target_h)

        # ---- 3) 纯 Lanczos 快速放大 ----
        if use_lanczos:
            if target_w > 0:
                images = _resize(images, target_w, target_h)
            else:
                height, width = int(images.shape[1]), int(images.shape[2])
                width = max(32, int(round(width * float(lanczos_scale) / 32) * 32))
                height = max(32, int(round(height * float(lanczos_scale) / 32) * 32))
                images = _resize(images, width, height)
            report["lanczos_scale"] = float(lanczos_scale)

        frames.validate_canvas(int(images.shape[2]), int(images.shape[1]))
        report.update({
            "out_frames": int(images.shape[0]),
            "out_size": [int(images.shape[2]), int(images.shape[1])],
            "duration": round(float(images.shape[0]) / FPS, 3),
        })

        # ---- 4) 保存最终视频 + 节点内预览 ----
        output_root = str((config or {}).get("output_dir") or output_dir or "DirectorDeck")
        saved_path = ""
        ui = {}
        try:
            if save_video:
                final_dir = os.path.join(folder_paths.get_output_directory(),
                                         output_root, "final")
                os.makedirs(final_dir, exist_ok=True)
                name = f"{str(filename_prefix or 'final').strip() or 'final'}" \
                       f"_{int(time.time() * 1000)}.mp4"
                saved_path = os.path.join(final_dir, name)
                preview_lib.write_preview_mp4(
                    images, out_audio, saved_path, fps=FPS, crf=18, preset="medium")
                subfolder = f"{output_root.replace(os.sep, '/')}/final"
                ui = {"images": [{"filename": name, "subfolder": subfolder,
                                  "type": "output"}], "animated": [True]}
                report["saved"] = saved_path
                try:
                    with open(os.path.splitext(saved_path)[0] + ".json", "w",
                              encoding="utf-8") as handle:
                        json.dump(report, handle, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            else:
                temp_dir = folder_paths.get_temp_directory()
                os.makedirs(temp_dir, exist_ok=True)
                name = f"directordeck_final_{int(time.time() * 1000)}.mp4"
                saved_path = os.path.join(temp_dir, name)
                preview_lib.write_preview_mp4(
                    images, out_audio, saved_path, fps=FPS, crf=20, preset="veryfast")
                ui = {"images": [{"filename": name, "subfolder": "", "type": "temp"}],
                      "animated": [True]}
                report["saved"] = saved_path
        except Exception as exc:
            print(f"[DirectorDeck] 最终视频保存/预览失败：{exc}")

        report_text = (
            f"模式：{report['mode']}\n"
            f"帧数：{report['in_frames']} -> {report.get('out_frames', '?')}"
            f"（{report.get('duration', 0)}s @ {FPS}fps）\n"
            f"尺寸：{report['in_size'][0]}x{report['in_size'][1]}"
            f" -> {report.get('out_size', ['?', '?'])[0]}x{report.get('out_size', ['?', '?'])[1]}\n"
            f"二采 LoRA：{report.get('refiner_lora', {}).get('name', 'none')}\n"
            f"RelayVSR：{'开' if use_relay else '关'}\n"
            f"输出：{saved_path or '（未保存）'}")
        print(f"[DirectorDeck] 最终处理完成：{report['mode']}，{report_text}")
        return {"ui": ui, "result": (images, out_audio, report_text)}
