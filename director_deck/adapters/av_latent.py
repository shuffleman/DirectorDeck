"""打包 AV latent 的“手术层”（M3 锁音/二采的关键）。

H3 的 latent 不是普通 latent：它是一个 NestedTensor 对——
- 视频流：[B, 24, T_lat, H/16, W/16]
- 音频流：[B, 32, 2, T_audio]
两者共用一个时间轴，采样器把它们当一条数据去噪。

所以“数字人锁音”的本质是：
1. 把外部音轨编码成音频 latent，替换掉 latent 里的音频流；
2. 给 noise_mask 设置成“视频全 1、音频全 0”——
   这样采样器只在视频流上去噪，音频流原样保留（这就是“锁”）。
3. 采样完再兜底把音频流恢复一遍，防止某些采样器顺手改了它。

这些操作内核节点做不到（SetLatentNoiseMask 只支持单流 mask），
只能在 Python 里拆/合，这也是 M3 必须自己写节点的原因。
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

import comfy.audio
import comfy.model_management
import comfy.nested_tensor
from comfy_extras.nodes_minimax_h3 import AUDIO_LATENT_FPS, temporal_shape

from ..core import audio as audio_math
from ..core.types import error


def template_shapes(width: int, height: int, length: int) -> dict:
    """给定像素尺寸和帧数，算出 H3 期望的 latent 形状。

    video_latent_t / audio_t 是内核的时间压缩关系（17k+5 与 40fps 音频栅格），
    这里直接问内核要，别自己猜。
    """
    frame_count, video_t, audio_t = temporal_shape(int(length))
    return {
        "frame_count": int(frame_count),
        "video": (24, int(video_t), int(height) // 16, int(width) // 16),
        "audio": (32, 2, int(audio_t)),
        "audio_t": int(audio_t),
    }


def _as_latent(samples) -> dict:
    """把裸张量/字典统一成 latent 字典。"""
    if isinstance(samples, dict):
        return samples
    return {"samples": samples}


def split_av(latent) -> tuple[torch.Tensor, torch.Tensor]:
    """把打包 AV latent 拆成 (视频流, 音频流)。"""
    samples = _as_latent(latent)["samples"]
    if not getattr(samples, "is_nested", False):
        raise error("DD-E030", "这不是 H3 的打包 AV latent（samples 不是 NestedTensor）")
    tensors = samples.unbind()
    if len(tensors) != 2:
        raise error("DD-E030", f"打包 AV latent 应该有 2 条流，实际 {len(tensors)} 条")
    return tensors[0], tensors[1]


def pack_av(video: torch.Tensor, audio: torch.Tensor,
            video_mask: torch.Tensor | None = None,
            audio_mask: torch.Tensor | None = None) -> dict:
    """把两条流重新打包成 latent；给了 mask 就一起打包（采样器认这个）。"""
    latent = {"samples": comfy.nested_tensor.NestedTensor((video, audio))}
    if video_mask is not None and audio_mask is not None:
        latent["noise_mask"] = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
    return latent


def _fit_time(tensor: torch.Tensor, target_t: int) -> torch.Tensor:
    """把时间轴（最后一维或倒数第三维）裁/补到目标长度。

    VAE 编码出来的长度可能和空 latent 差一两个 token（浮点舍入），
    这里统一裁掉多余、补零不足，避免 shape 不匹配直接报错。
    """
    current = tensor.shape[-1]
    if current == target_t:
        return tensor
    if current > target_t:
        return tensor[..., :target_t].contiguous()
    pad = target_t - current
    return F.pad(tensor, (0, pad)).contiguous()


def encode_video_latent(vae, images: torch.Tensor, template: dict) -> torch.Tensor:
    """把成片帧编码成视频 latent，并校验/对齐到模板形状。"""
    try:
        latent = vae.encode(images)
    except Exception as exc:
        raise error("DD-E030", f"视频 VAE 编码失败：{exc}")
    if latent.shape[1] != template["video"][0]:
        raise error("DD-E030",
                    f"视频 latent 通道数不符：{latent.shape[1]} != {template['video'][0]}")
    if latent.shape[2] != template["video"][1]:
        raise error("DD-E030",
                    f"视频 latent 时间长度不符：{latent.shape[2]} != {template['video'][1]}"
                    "（帧数没吸附到 17k+5？）")
    if latent.shape[3] != template["video"][2] or latent.shape[4] != template["video"][3]:
        raise error("DD-E030",
                    f"视频 latent 空间尺寸不符：{tuple(latent.shape[3:])} != "
                    f"{template['video'][2:]}")
    return latent


def encode_audio_latent(audio_vae, waveform: torch.Tensor, sample_rate: int,
                        target_t: int) -> torch.Tensor:
    """把波形编码成音频 latent，并把时间长度对齐到目标。

    waveform: [B, C, S]（和 ComfyUI AUDIO 一致）；vae.encode 要 [B, S, C]。
    """
    vae_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
    if int(sample_rate) != vae_rate:
        waveform = comfy.audio.resample(waveform, int(sample_rate), vae_rate)
    latent = audio_vae.encode(waveform[:1].movedim(1, -1))  # [1, 32, 2, T]
    if latent.shape[1] != 32 or latent.shape[2] != 2:
        raise error("DD-E030", f"音频 latent 形状异常：{tuple(latent.shape)}（期望 [1,32,2,T]）")
    return _fit_time(latent, int(target_t))


def build_audio_track(roles: list[dict], seg_start: float, seg_end: float,
                      sample_rate: int = 32000) -> torch.Tensor:
    """把多个角色的配音按时间轴铺成“本段一条音轨”。

    规则：
    - 每个角色有 audio_data（波形）+ start（在整条时间轴上的起点，秒）；
    - 用 core.audio.clip_window 算它在段内的偏移和长度；
    - 多角色重叠就相加（先不做智能 ducking，M4 再做）；
    - 最后削一下峰值，避免叠加后爆音。
    """
    length = max(1, audio_math.samples_for(seg_end - seg_start, sample_rate))
    track = torch.zeros((1, 2, length), dtype=torch.float32)
    for role in roles or []:
        data = role.get("audio_data")
        if not data:
            continue
        waveform = data["waveform"].detach().float().cpu()
        rate = int(data.get("sample_rate", sample_rate))
        if rate != sample_rate:
            waveform = comfy.audio.resample(waveform, rate, sample_rate)
        if waveform.shape[1] == 1:  # 单声道复制成双声道，保持形状统一
            waveform = waveform.repeat(1, 2, 1)
        clip_start = float(role.get("start") or 0.0)
        clip_end = clip_start + waveform.shape[-1] / float(sample_rate)
        window = audio_math.clip_window(clip_start, clip_end, seg_start, seg_end)
        if window is None:
            continue
        src_offset, dst_offset, length_s = window
        src_i0 = audio_math.samples_for(src_offset, sample_rate)
        dst_i0 = audio_math.samples_for(dst_offset, sample_rate)
        count = min(audio_math.samples_for(length_s, sample_rate),
                    waveform.shape[-1] - src_i0,
                    length - dst_i0)
        if count <= 0:
            continue
        track[..., dst_i0:dst_i0 + count] += waveform[..., src_i0:src_i0 + count][..., :count]
    peak = float(track.abs().max()) if track.numel() else 0.0
    if peak > 1.0:
        track = track / peak
    return track


def lock_audio(latent, audio_vae, waveform: torch.Tensor, sample_rate: int) -> tuple[dict, torch.Tensor]:
    """把音轨锁进 AV latent：替换音频流 + 视频 mask=1 / 音频 mask=0。

    返回 (新的 latent, 锁进去的音频 latent)，后者用于采样后兜底恢复。
    """
    video, _audio = split_av(latent)
    # 音频目标长度由像素帧数决定：duration * AUDIO_LATENT_FPS。
    frames = _frames_from_video_latent(video)
    target_t = int(round(frames / 24.0 * AUDIO_LATENT_FPS))
    locked_audio = encode_audio_latent(audio_vae, waveform, sample_rate, target_t)
    video_mask = torch.ones_like(video)
    audio_mask = torch.zeros_like(locked_audio)
    return pack_av(video, locked_audio, video_mask, audio_mask), locked_audio


def _frames_from_video_latent(video: torch.Tensor) -> int:
    """从视频 latent 的 T 反推像素帧数（用于算音频目标长度）。"""
    # FRAME_PER_TOKEN=(1,4,4,4,4)，第 i 个 token 覆盖 1/4/4/4/4 帧，循环。
    from comfy.ldm.minimax.model import FRAME_PER_TOKEN
    return sum(FRAME_PER_TOKEN[k % 5] for k in range(int(video.shape[2])))


def restore_audio(sampled: dict, locked_audio: torch.Tensor) -> dict:
    """采样后把音频流恢复成“锁进去的那一版”，视频流保持采样结果。

    为什么还要做这一步？noise_mask=0 理论上已经保护了音频流，
    但不同采样器/未来内核可能在最后一步把整包数据都过一遍；这里再兜一层底，
    保证“数字人锁音”不会因为内核升级而悄悄漂掉。
    """
    video, sampled_audio = split_av(sampled)
    audio = _fit_time(locked_audio.to(sampled_audio.device, sampled_audio.dtype),
                      int(sampled_audio.shape[-1]))
    out = dict(sampled)
    out["samples"] = comfy.nested_tensor.NestedTensor((video, audio))
    out.pop("noise_mask", None)
    return out
