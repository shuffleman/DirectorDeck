"""段的磁盘缓存（画面 mp4 + 音轨/ latent / 源音轨 npz + 元数据 json）。

为什么画面用 mp4 而不是 npy？
- 一段 124 帧 640x352 的 float32 原始数据约 335MB，npy 存不下几段；
- h264 CRF 12 的 mp4 只有 ~1–3MB，解码回来画质几乎无损（CRF 12 视觉上已经很接近），
  抽卡复用完全够用；音轨和 latent 很小，用 npz 存原始 float，保证精确。

缓存目录：output/DirectorDeck/cache/segments/seg_<指纹>.{mp4,npz,json}
"""

from __future__ import annotations

import json
import os
import subprocess

import numpy as np
import torch

from ..core import cache as cache_lib
from ..core.types import error

try:  # imageio_ffmpeg 在 ComfyUI 环境里有；没有就退化成“不缓存”
    import imageio_ffmpeg
except Exception:  # pragma: no cover
    imageio_ffmpeg = None


def cache_paths(cache_root: str, fingerprint: str) -> dict:
    stem = cache_lib.cache_stem(fingerprint)
    base = os.path.join(cache_root, "segments")
    return {
        "dir": base,
        "mp4": os.path.join(base, f"seg_{stem}.mp4"),
        "npz": os.path.join(base, f"seg_{stem}.npz"),
        "json": os.path.join(base, f"seg_{stem}.json"),
    }


def available() -> bool:
    """当前环境能不能写缓存（没有 ffmpeg 就不缓存，别影响正常出片）。"""
    return imageio_ffmpeg is not None


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def save(cache_root: str, fingerprint: str, *, images: torch.Tensor,
         audio: dict, latent_handoff: dict | None, lock_source_audio: dict | None,
         meta: dict) -> dict:
    """把一段的产物写进磁盘缓存，返回路径字典。"""
    if not available():
        return {}
    paths = cache_paths(cache_root, fingerprint)
    os.makedirs(paths["dir"], exist_ok=True)

    # 1) 画面：h264 mp4（CRF 12）。
    frames = images.detach().float().cpu()
    array = (frames.clamp(0.0, 1.0) * 255.0).to(torch.uint8).numpy()
    height, width = int(array.shape[1]), int(array.shape[2])
    cmd = [_ffmpeg(), "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
           "-r", "24", "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "12",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", paths["mp4"]]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        proc.stdin.write(array.tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read()
        code = proc.wait()
    finally:
        pass
    if code != 0:
        raise error("DD-E040", "缓存 mp4 写入失败：" + stderr.decode("utf-8", "replace")[-400:])

    # 2) 音轨 + latent + 锁音源轨：npz 原始 float。
    payload = {
        "waveform": audio["waveform"].detach().float().cpu().numpy(),
        "sample_rate": np.array(int(audio.get("sample_rate", 48000)), dtype=np.int64),
    }
    if latent_handoff:
        payload["lat_video"] = latent_handoff["video"].detach().float().cpu().numpy()
        payload["lat_audio"] = latent_handoff["audio"].detach().float().cpu().numpy()
        payload["lat_sample"] = np.array(int(latent_handoff.get("sample") or 0), dtype=np.int64)
    if lock_source_audio:
        payload["lock_waveform"] = lock_source_audio["waveform"].detach().float().cpu().numpy()
        payload["lock_sample_rate"] = np.array(int(lock_source_audio["sample_rate"]), dtype=np.int64)
    np.savez(paths["npz"], **payload)

    # 3) 元数据：段结果 + 画面尺寸（读回解码要用）。
    meta = dict(meta or {})
    meta["_cache"] = {"frames": int(array.shape[0]), "height": height, "width": width,
                      "fingerprint": fingerprint, "schema": cache_lib.CACHE_SCHEMA}
    with open(paths["json"], "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return paths


def _decode_mp4(path: str, frames: int, height: int, width: int) -> torch.Tensor:
    """把缓存 mp4 解码回 [N,H,W,3] float 张量。"""
    expected = int(frames) * int(height) * int(width) * 3
    result = subprocess.run(
        [_ffmpeg(), "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True)
    buffer = result.stdout
    if len(buffer) < expected:
        raise error("DD-E040",
                    f"缓存 mp4 解码失败：期望 {expected} 字节，实际 {len(buffer)}")
    array = np.frombuffer(buffer[:expected], dtype=np.uint8)
    array = array.reshape(int(frames), int(height), int(width), 3).astype(np.float32) / 255.0
    return torch.from_numpy(array)


def load(cache_root: str, fingerprint: str) -> dict | None:
    """读缓存；没有/损坏/版本不符就返回 None（按未命中处理，绝不阻断生成）。"""
    if not available():
        return None
    paths = cache_paths(cache_root, fingerprint)
    if not (os.path.isfile(paths["mp4"]) and os.path.isfile(paths["npz"])
            and os.path.isfile(paths["json"])):
        return None
    try:
        with open(paths["json"], "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        info = meta.get("_cache") or {}
        if int(info.get("schema", 0)) != int(cache_lib.CACHE_SCHEMA):
            return None
        images = _decode_mp4(paths["mp4"], int(info["frames"]),
                             int(info["height"]), int(info["width"]))
        with np.load(paths["npz"], allow_pickle=False) as data:
            audio = {"waveform": torch.from_numpy(np.array(data["waveform"])),
                     "sample_rate": int(np.array(data["sample_rate"]))}
            latent_handoff = None
            if "lat_video" in data:
                latent_handoff = {
                    "video": torch.from_numpy(np.array(data["lat_video"])),
                    "audio": torch.from_numpy(np.array(data["lat_audio"])),
                    "sample": int(np.array(data["lat_sample"])),
                }
            lock_source_audio = None
            if "lock_waveform" in data:
                lock_source_audio = {
                    "waveform": torch.from_numpy(np.array(data["lock_waveform"])),
                    "sample_rate": int(np.array(data["lock_sample_rate"])),
                }
        return {"images": images, "audio": audio, "latent_handoff": latent_handoff,
                "lock_source_audio": lock_source_audio, "meta": meta, "paths": paths}
    except Exception as exc:  # 缓存坏了就当没命中，不要影响出片
        print(f"[DirectorDeck] 缓存读取失败（按未命中处理）：{exc}")
        return None
