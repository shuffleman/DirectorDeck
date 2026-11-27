"""M1 集成冒烟测试（在 ComfyUI 的 venv 里直接调用节点，不依赖重启 ComfyUI）。

为什么要这么测：我们的节点库还没被 ComfyUI 加载（要重启服务才会加载新 custom_nodes），
但节点内部逻辑（加载/条件/采样/解码）可以在这个脚本里直接调用，等于提前把 M1 跑通一次。

用法（必须用 ComfyUI venv 的 python）：
    F:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\ComfyUI\\.venv\\Scripts\\python.exe tools\\smoke_m1.py

流程：释放服务器显存 -> ModelLoader -> DirectorConfig -> ScriptDesk -> DirectorTake(单段)
      -> 校验帧数/音轨 -> 编码 mp4 到 runs/m1_smoke/ -> 打印摘要。

排错提示：每一步都会写日志到 runs/m1_smoke/smoke.log，
就算 CUDA 直接崩掉（Python 来不及打 traceback），也能看出最后走到哪一步。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY = r"F:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI"
EXTRA_CONFIG = r"C:\Users\shuff\AppData\Roaming\Comfy Desktop\instance-model-paths\inst-1795042329472.yaml"
OUT_DIR = os.path.join(REPO, "runs", "m1_smoke")
LOG_PATH = os.path.join(OUT_DIR, "smoke.log")

sys.path.insert(0, COMFY)
sys.path.insert(0, REPO)

UNET = "MiniMax\\fastvideo_fasth3_8step_v2_pruned_bf16.safetensors"
CLIP = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
LORA_1 = "minimax\\pika_h3_flex_ref2va_v1_bf16.safetensors"
LORA_2 = "minimax\\dmad_minimax_h3_8step_full_critic_comfyui.safetensors"
LORA_3 = "minimax\\Motion_Repair运动连续性.safetensors"
SIGMAS = "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"


def log(message: str) -> None:
    """所有阶段都往日志文件里补一行，方便 native crash 后定位。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def free_server() -> None:
    """先让正在运行的 ComfyUI 释放显存，避免我们和它抢 12G 显存。"""
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:8188/free",
        data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            log(f"/free -> {resp.status}")
    except Exception as exc:
        log(f"/free 失败（继续）：{exc}")
    time.sleep(3)


def encode_mp4(frames, audio, path: str) -> str:
    """把 IMAGE 张量 + AUDIO 字典编码成 mp4。

    这里故意不依赖 ComfyUI 的 SaveVideo：冒烟脚本要能独立出片做证据。
    frames: torch [N,H,W,3] float(0..1)；audio: {"waveform":[B,C,S], "sample_rate":int}
    """
    import numpy as np
    import imageio_ffmpeg

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    arr = frames.detach().cpu().float().numpy()
    arr = (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
    n, h, w, _ = arr.shape
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmd = [ff, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", "24", "-i", "-"]
    tmp_audio = None
    if audio:
        wf = audio["waveform"]
        samples = wf.detach().cpu().float().numpy()
        if samples.ndim == 3:
            samples = samples[0]
        if samples.shape[0] == 1:
            samples = np.repeat(samples, 2, axis=0)
        interleaved = samples.T.reshape(-1).astype(np.float32)
        tmp_audio = path + ".audio.f32"
        interleaved.tofile(tmp_audio)
        cmd += ["-f", "f32le", "-ar", str(int(audio.get("sample_rate", 48000))),
                "-ac", "2", "-i", tmp_audio]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if tmp_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        proc.stdin.write(arr.tobytes())
        proc.stdin.close()
        err = proc.stderr.read()
        code = proc.wait()
    finally:
        if tmp_audio and os.path.exists(tmp_audio):
            os.remove(tmp_audio)
    if code != 0:
        raise RuntimeError("ffmpeg failed: " + err.decode("utf-8", "replace")[-2000:])
    return path


def run() -> dict:
    """真正跑一遍 M1。返回摘要字典，异常由 main 统一接住。"""
    started = time.time()
    free_server()

    log("import folder_paths / extra_config")
    import folder_paths
    import utils.extra_config
    if os.path.isfile(EXTRA_CONFIG):
        utils.extra_config.load_extra_path_config(EXTRA_CONFIG)
        log("extra model paths loaded")
    log(f"diffusion_models: {folder_paths.get_filename_list('diffusion_models')[:3]}")

    from director_deck.nodes.loader import DirectorDeckModelLoader
    from director_deck.nodes.config import DirectorDeckConfig
    from director_deck.nodes.script_node import DirectorDeckScriptDesk, EXAMPLE_SCRIPT
    from director_deck.nodes.take import DirectorDeckTake

    log("加载模型（42GB 主干 + 15GB TE + 双 VAE，可能要 1~2 分钟）…")
    bundle, = DirectorDeckModelLoader().load(
        fl2va_model=UNET, text_encoder=CLIP, video_vae=VIDEO_VAE,
        audio_vae=AUDIO_VAE, weight_dtype="default", vram_tier="auto",
        ref2va_model="none", lora_1=LORA_1, strength_1=1.0,
        lora_2=LORA_2, strength_2=0.5, lora_3=LORA_3, strength_3=0.3,
        lora_4="none", strength_4=1.0, shift_video=12.0, shift_audio=3.0)
    log(f"bundle loaded: {bundle['bundle_id'][:20]}…")

    log("构建 config")
    config, = DirectorDeckConfig().build(
        width=640, height=352, segment_seconds=5.0, handoff_frames=22,
        sampler_name="er_sde", scheduler="beta", steps=10, denoise=1.0,
        sigmas_string=SIGMAS, interpolate_to_steps=10,
        seed_strategy="per_segment", seed_base=12345, preview=False,
        vram_policy="release", cleanup_segments="ask", output_dir="DirectorDeck")

    log("解析剧本")
    script, summary = DirectorDeckScriptDesk().parse_text(
        EXAMPLE_SCRIPT, mode="auto", default_seconds=5.0, max_segments=64,
        keep_header=False, regex_pattern="")
    log("script: " + summary.replace("\n", " | "))

    log("生成第 1 段（条件 -> 采样 -> 解码）…")
    out = DirectorDeckTake().generate(
        bundle=bundle, config=config, script=script, segment_index=1,
        bundle_policy="provided", config_policy="inherit", assets_policy="clear",
        brief_policy="inherit", cast_policy="inherit", continuity="start", seed=0)
    segment, images, audio = out["result"]
    log(f"生成完成：frames={tuple(images.shape)} seed={segment['seed']} "
        f"elapsed={segment['elapsed_s']}s")

    os.makedirs(OUT_DIR, exist_ok=True)
    log("编码 mp4 …")
    mp4 = encode_mp4(images, audio, os.path.join(OUT_DIR, "m1_single_segment.mp4"))
    with open(os.path.join(OUT_DIR, "segment.json"), "w", encoding="utf-8") as fh:
        json.dump(segment, fh, ensure_ascii=False, indent=2)

    log("保存首帧 png")
    from PIL import Image
    import numpy as np
    arr = (np.clip(images[0].detach().cpu().numpy(), 0.0, 1.0) * 255).astype("uint8")
    Image.fromarray(arr).save(os.path.join(OUT_DIR, "first_frame.png"))

    total = time.time() - started
    return {
        "ok": True,
        "frames": int(images.shape[0]),
        "size": [int(images.shape[2]), int(images.shape[1])],
        "audio_rate": audio.get("sample_rate"),
        "seed": segment["seed"],
        "sigmas": segment.get("sigmas"),
        "elapsed_s": segment["elapsed_s"],
        "total_s": round(total, 1),
        "mp4": mp4,
        "segment_json": os.path.join(OUT_DIR, "segment.json"),
    }


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    # 清掉旧日志，别把上一次的残留混进来。
    open(LOG_PATH, "w", encoding="utf-8").close()
    try:
        summary = run()
    except Exception:
        detail = traceback.format_exc()
        log("FAILED:\n" + detail)
        with open(os.path.join(OUT_DIR, "smoke_error.txt"), "w", encoding="utf-8") as fh:
            fh.write(detail)
        return 1
    with open(os.path.join(OUT_DIR, "smoke_result.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    log("DONE: " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
