"""把一段画面 + 音轨压成一个可预览的小 mp4（给节点预览用）。

为什么单独写：ComfyUI 节点的视频预览走 `ui={"images":[{filename...}], "animated":[True]}`
这套数据；前端会把 .mp4 直接渲染成可播放的视频。这里负责用 ffmpeg 把
[帧张量] + [AUDIO 字典] 编码成 H.264 + AAC 的临时 mp4。

预览只是“看效果”，所以用 veryfast + CRF 23；正式成片仍由 SaveVideo/FinalCut 输出。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import wave

import numpy as np


def _write_wav(path: str, waveform, sample_rate: int) -> None:
    """AUDIO 波形（torch 张量）写成 16bit PCM wav，给 ffmpeg 当第二路输入。"""
    array = waveform.detach().float().cpu().numpy()
    while array.ndim > 2:
        array = array[0]
    if array.ndim == 1:
        array = np.stack([array, array], axis=0)
    elif array.shape[0] == 1:
        array = np.repeat(array, 2, axis=0)
    array = np.clip(array, -1.0, 1.0).T  # [N, C]
    pcm = (array * 32767.0).astype("<i2")
    with wave.open(path, "wb") as handle:
        handle.setnchannels(int(pcm.shape[1]))
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())


def write_preview_mp4(images, audio: dict | None, out_path: str, *,
                      fps: int = 24, crf: int = 23, preset: str = "veryfast") -> str:
    """把帧张量 + 音轨写成 mp4；返回 out_path。失败抛异常由调用方兜底。"""
    import imageio_ffmpeg

    import torch  # noqa: F401  # 确认是 torch 张量（预览在 ComfyUI 里跑）

    frames = images.detach().float().cpu().numpy()
    if frames.ndim == 4 and frames.shape[-1] > 3:
        frames = frames[..., :3]
    count, height, width = frames.shape[0], frames.shape[1], frames.shape[2]
    if count <= 0:
        raise ValueError("没有可预览的帧")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    wav_path = None
    cmd = [ffmpeg, "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{width}x{height}", "-r", str(int(fps)), "-i", "-"]
    waveform = (audio or {}).get("waveform")
    if waveform is not None and getattr(waveform, "numel", lambda: 0)() > 0:
        handle, wav_path = tempfile.mkstemp(suffix=".wav", prefix="dd_prev_")
        os.close(handle)
        _write_wav(wav_path, waveform, int((audio or {}).get("sample_rate", 48000)))
        cmd += ["-i", wav_path, "-c:a", "aac", "-b:a", "128k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", str(preset), "-crf", str(int(crf)),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]

    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for frame in frames:
            # 注意：浮点 0~1 必须乘 255 再转 uint8，否则会变成 0/1 的“黑片”。
            process.stdin.write(
                (np.clip(frame, 0.0, 1.0) * 255.0).astype(np.uint8).tobytes())
        process.stdin.close()
        stderr = process.stderr.read()
        code = process.wait()
    finally:
        if process.stderr:
            process.stderr.close()
        if wav_path and os.path.isfile(wav_path):
            os.remove(wav_path)
    if code != 0:
        raise RuntimeError("预览 mp4 编码失败：" + stderr.decode("utf-8", "replace")[-300:])
    return out_path
