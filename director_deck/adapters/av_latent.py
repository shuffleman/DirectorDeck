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


def _frame_energies(track: torch.Tensor, frame_size: int) -> list[float]:
    """逐帧 RMS（给混音规则判断“谁在说话”）。"""
    mono = track.mean(dim=1).reshape(-1)
    energies = []
    for start in range(0, mono.shape[0], max(1, frame_size)):
        chunk = mono[start:start + frame_size]
        if chunk.numel() == 0:
            break
        energies.append(float(torch.sqrt((chunk * chunk).mean()).item()))
    return energies


def _apply_gain_envelope(track: torch.Tensor, gains: list[float], frame_size: int) -> torch.Tensor:
    """把“逐帧增益”线性插值到采样点再乘上去（避免台阶式爆音）。"""
    if not gains:
        return track
    length = int(track.shape[-1])
    envelope = torch.tensor(gains, dtype=track.dtype).view(1, 1, -1)
    upsampled = torch.nn.functional.interpolate(
        envelope, size=length, mode="linear", align_corners=False).reshape(length)
    return track * upsampled


def build_audio_track(roles: list[dict], seg_start: float, seg_end: float,
                      sample_rate: int = 32000, mix: dict | None = None,
                      previous: dict | None = None,
                      return_context: bool = False):
    """把多个角色的配音按时间轴铺成“本段一条音轨”，并按混音规则处理。

    混音规则（`mix`，来自 VoiceLock 节点）：
    - `mode`：`auto_duck` / `priority` / `sum`；
    - `duck_db`：被压多少分贝（默认 -8dB ≈ 0.398 倍）；
    - `attack_ms` / `release_ms`：压下去/恢复的速度，避免爆音；
    - 每路还可单独设 `gain_db` 和 `priority`。

    **跨段一致性**（`previous`）：上一段传下来的混音上下文
    `{"gain_state": {角色: 结尾增益}, "tail": 尾音, "sample_rate": ...}`。
    - 包络从上一段结尾的增益接着算（段边界不会突然“弹回 1.0”）；
    - 返回的 context 里带着本段尾音和结尾增益，供下一段使用。

    `return_context=True` 时返回 (track, context)，否则只返回 track。
    """
    mix = dict(mix or {})
    previous = dict(previous or {})
    mode = str(mix.get("mode") or "auto_duck")
    duck_db = float(mix.get("duck_db", audio_math.DUCK_DB_DEFAULT))
    attack_ms = float(mix.get("attack_ms", audio_math.ATTACK_MS_DEFAULT))
    release_ms = float(mix.get("release_ms", audio_math.RELEASE_MS_DEFAULT))
    frame_ms = float(mix.get("frame_ms", audio_math.MIX_FRAME_MS))
    length = max(1, audio_math.samples_for(seg_end - seg_start, sample_rate))

    tracks: list[torch.Tensor] = []
    used_roles: list[dict] = []
    role_keys: list[str] = []
    for index, role in enumerate(roles or []):
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
        track = torch.zeros((1, 2, length), dtype=torch.float32)
        track[..., dst_i0:dst_i0 + count] += waveform[..., src_i0:src_i0 + count][..., :count]
        # 每路增益（dB）。
        gain_db = float(role.get("gain_db") or 0.0)
        if abs(gain_db) > 1e-6:
            track = track * audio_math.db_to_linear(gain_db)
        # 素材切入/切出做个 8ms 淡入淡出，避免“咔哒”。
        fade = min(int(sample_rate * 0.008), max(1, count // 4))
        if count > 2 * fade:
            ramp = torch.linspace(0.0, 1.0, fade, dtype=torch.float32)
            track[..., dst_i0:dst_i0 + fade] *= ramp
            track[..., dst_i0 + count - fade:dst_i0 + count] *= ramp.flip(0)
        tracks.append(track)
        used_roles.append(role)
        role_keys.append(str(role.get("id") or role.get("name") or f"role{index}"))

    context = {
        "gain_state": {},
        "tail": None,
        "sample_rate": int(sample_rate),
        "limiter": 1.0,
    }
    if not tracks:
        empty = torch.zeros((1, 2, length), dtype=torch.float32)
        return (empty, context) if return_context else empty

    # 逐帧能量 -> 混音规则 -> 逐路增益包络（起始增益接上一段结尾）。
    gain_state = dict(previous.get("gain_state") or {})
    initial = [float(gain_state.get(key, 1.0)) for key in role_keys]
    frame_size = max(1, int(round(sample_rate * frame_ms / 1000.0)))
    energies = [_frame_energies(track, frame_size) for track in tracks]
    priorities = [int(role.get("priority") or 0) for role in used_roles]
    gains = audio_math.mix_gains(
        energies, priorities, mode=mode, duck_db=duck_db,
        attack_ms=attack_ms, release_ms=release_ms, frame_ms=frame_ms,
        initial_gains=initial)

    mixed = torch.zeros((1, 2, length), dtype=torch.float32)
    for track, envelope in zip(tracks, gains):
        mixed = mixed + _apply_gain_envelope(track, envelope, frame_size)

    peak = float(mixed.abs().max()) if mixed.numel() else 0.0
    limit = audio_math.apply_limiter(peak)
    if limit < 1.0:
        mixed = mixed * limit

    context = {
        "gain_state": {key: float(envelope[-1]) if envelope else 1.0
                       for key, envelope in zip(role_keys, gains)},
        # 尾部留 1 秒：下一段的混音上下文 / 段边界淡入淡出都能用。
        "tail": mixed[..., -min(length, int(sample_rate)):].clone(),
        "sample_rate": int(sample_rate),
        "limiter": float(limit),
    }
    return (mixed, context) if return_context else mixed


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


# ---------------------------------------------------------------- latent 尾帧续写
def _existing_masks(latent: dict, video_t: int, audio_t: int,
                    video: torch.Tensor, audio: torch.Tensor
                    ) -> tuple[torch.Tensor, torch.Tensor]:
    """取出 latent 里已有的逐流 mask；没有就新建全 1（表示全部要去噪）。

    锁音之后的 mask 是“视频 1 / 音频 0”，latent 续写要在它基础上把开头几帧也钉住，
    所以不能简单重建 mask，必须沿用已有的。
    """
    mask = latent.get("noise_mask") if isinstance(latent, dict) else None
    if mask is not None and getattr(mask, "is_nested", False):
        parts = mask.unbind()
        if len(parts) == 2:
            video_mask = parts[0].to(device=video.device, dtype=video.dtype)
            audio_mask = parts[1].to(device=audio.device, dtype=audio.dtype)
            return video_mask, audio_mask
    video_mask = torch.ones((video.shape[0], 1, video_t, video.shape[3], video.shape[4]),
                            device=video.device, dtype=video.dtype)
    audio_mask = torch.ones((audio.shape[0], 1, audio.shape[2], audio_t),
                            device=audio.device, dtype=audio.dtype)
    return video_mask, audio_mask


def latent_handoff(latent: dict, previous: dict, requested_head: int,
                   lock_audio_only: bool = False) -> tuple[dict, dict]:
    """latent 尾帧续写：把上一段 latent 的尾部 token 搬进新 latent 开头并钉住（mask=0）。

    previous 里应有：
      - video：上一段的视频 latent（[1,24,T,H,W]）
      - audio：上一段的音频 latent（[1,32,2,Ta]）
      - sample：上一段的像素帧数

    为什么这么干：RGB 尾帧引导要把画面解码成图片再编码成条件，比较绕；
    直接把上一段 latent 的尾部 token 放过来并设 noise_mask=0，
    采样器就会原样保留它们，同时模型能基于这些 token 继续生成——更快、更贴近原生续写。
    """
    new_video, new_audio = split_av(latent)
    prev_video = previous["video"].to(device=new_video.device, dtype=new_video.dtype)
    prev_audio = previous["audio"].to(device=new_audio.device, dtype=new_audio.dtype)
    sample_frames = int(previous.get("sample") or 0)
    prev_tokens = int(prev_video.shape[2])
    if sample_frames <= 0:
        sample_frames = sum(_frame_spans(prev_tokens))

    # 按 token 边界算“搬多少 token / 实际遮多少帧”（可能比 head 多 0~3 帧）。
    k0, masked_frames = _tail_boundary(sample_frames, int(requested_head), prev_tokens)
    count = min(prev_tokens - k0, int(new_video.shape[2]))
    if count <= 0:
        raise error("DD-E008", "上一段 latent 太短，无法做 latent 尾帧续写")

    video_mask, audio_mask = _existing_masks(
        latent, int(new_video.shape[2]), int(new_audio.shape[-1]), new_video, new_audio)
    video = new_video.clone()
    video[:, :, :count] = prev_video[:, :, k0:k0 + count]
    video_mask = video_mask.clone()
    video_mask[:, :, :count] = 0

    audio = new_audio.clone()
    if not lock_audio_only:
        audio_count = int(round(masked_frames / 24.0 * AUDIO_LATENT_FPS))
        audio_count = min(audio_count, int(new_audio.shape[-1]), int(prev_audio.shape[-1]))
        if audio_count > 0:
            audio[..., :audio_count] = prev_audio[..., -audio_count:]
            audio_mask = audio_mask.clone()
            audio_mask[..., :audio_count] = 0

    packed = pack_av(video, audio, video_mask, audio_mask)
    info = {
        "mode": "latent_tail",
        "tokens_copied": int(count),
        "token_start": int(k0),
        "masked_frames": int(masked_frames),
        "audio_tokens": 0 if lock_audio_only else int(audio_count),
    }
    return packed, info


def _frame_spans(token_count: int) -> list[int]:
    from ..core.frames import token_frame_spans
    return token_frame_spans(int(token_count))


def _tail_boundary(sample_frames: int, head_frames: int, token_count: int) -> tuple[int, int]:
    """按“实际 token 数”算边界（比 core 的公式更稳：直接用上一段 latent 的 T）。"""
    from ..core.frames import token_frame_boundaries
    boundaries = token_frame_boundaries(int(token_count))
    target = int(sample_frames) - max(1, int(head_frames))
    k0 = 0
    for index, boundary in enumerate(boundaries):
        if boundary <= target:
            k0 = index
        else:
            break
    k0 = max(0, min(k0, int(token_count)))
    masked_frames = int(sample_frames) - boundaries[k0]
    return k0, masked_frames
