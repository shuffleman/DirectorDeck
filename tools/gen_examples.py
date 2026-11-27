"""生成 M1 示例工作流（ComfyUI API 格式，可 POST /prompt 或导入面板）。

为什么要脚本生成而不是手写 JSON？
因为模型文件路径、sigma 表、示例剧本这些常量只该维护一份；
生成出来的 JSON 还能直接当“可运行文档”给用户抄。

用法：python tools/gen_examples.py
产物：examples/m1_single_segment_api.json、examples/m1_ref2va_api.json
"""

from __future__ import annotations

import copy
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
EXAMPLE_DIR = os.path.join(REPO, "examples")

# 本机（ComfyUI-Shared）实际在用的模型组合；换机器时改这里。
UNET = "MiniMax\\fastvideo_fasth3_8step_v2_pruned_bf16.safetensors"
CLIP = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
LORA_1 = "minimax\\pika_h3_flex_ref2va_v1_bf16.safetensors"
LORA_2 = "minimax\\dmad_minimax_h3_8step_full_critic_comfyui.safetensors"
LORA_3 = "minimax\\Motion_Repair运动连续性.safetensors"
SIGMAS = "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"
SCRIPT = """第1段（5秒）
清晨的湖面，薄雾浮动，一叶小舟缓缓划过，镜头从远处缓慢推进，暖金色晨光。

第2段（5秒）
特写：船夫粗糙的手握住船桨，水珠从桨叶落下，逆光里的水雾，镜头极慢推近。

第3段（5秒）
镜头升到高处俯瞰：小舟驶向湖心，晨雾散开，远山轮廓浮现，画面安静收尾。
"""


def loader_node() -> dict:
    """模型加载器节点：主模型 + 三件套 TE/VAE + 三个 LoRA + flow shift。"""
    return {
        "class_type": "DirectorDeck_ModelLoader",
        "inputs": {
            "fl2va_model": UNET,
            "text_encoder": CLIP,
            "video_vae": VIDEO_VAE,
            "audio_vae": AUDIO_VAE,
            "weight_dtype": "default",
            "vram_tier": "auto",
            "ref2va_model": "none",
            "lora_1": LORA_1, "strength_1": 1.0,
            "lora_2": LORA_2, "strength_2": 0.5,
            "lora_3": LORA_3, "strength_3": 0.3,
            "lora_4": "none", "strength_4": 1.0,
            "shift_video": 12.0, "shift_audio": 3.0,
        },
    }


def config_node() -> dict:
    """全局配置节点：640x352、5 秒、10 步、13 号同款 sigma 表。"""
    return {
        "class_type": "DirectorDeck_DirectorConfig",
        "inputs": {
            "width": 640, "height": 352, "segment_seconds": 5.0,
            "handoff_frames": 22, "sampler_name": "er_sde", "scheduler": "beta",
            "steps": 10, "denoise": 1.0, "sigmas_string": SIGMAS,
            "interpolate_to_steps": 10, "seed_strategy": "per_segment",
            "seed_base": 12345, "preview": True, "vram_policy": "release",
            "cleanup_segments": "ask", "output_dir": "DirectorDeck",
            # M2 接缝参数（不填会用默认值，但 API 格式要求显式给）
            "seam_enabled": True, "seam_window": 12,
            "seam_max_add": 0.10, "seam_gain_limit": 0.04,
        },
    }


def script_node() -> dict:
    """剧本加载器节点：两段湖面/船夫示例。"""
    return {
        "class_type": "DirectorDeck_ScriptDesk",
        "inputs": {"text": SCRIPT, "mode": "auto", "default_seconds": 5.0,
                   "max_segments": 64, "keep_header": False, "regex_pattern": ""},
    }


def take_node(node_id: str, bundle: str, config: str, script: str,
              assets: str | None = None, extra: dict | None = None) -> dict:
    """生成器节点：6 个 policy 全部显式给值（这就是我们强制显式指定的效果）。"""
    inputs = {
        "bundle": [bundle, 0],
        "config": [config, 0],
        "script": [script, 0],
        "segment_index": 1,
        "bundle_policy": "provided",
        "config_policy": "inherit",
        "assets_policy": "replace" if assets else "clear",
        "brief_policy": "inherit",
        "cast_policy": "inherit",
        "continuity": "start", "seed": 0, "cache_mode": "auto",
    }
    if assets:
        inputs["assets"] = [assets, 0]
    if extra:
        inputs.update(extra)
    return {"class_type": "DirectorDeck_DirectorTake", "inputs": inputs}


def output_nodes(take_id: str, prefix: str) -> dict:
    """尾巴两个节点：CreateVideo（组帧+音轨）-> SaveVideo（落盘）。"""
    create = {
        "class_type": "CreateVideo",
        "inputs": {"images": [take_id, 1], "fps": 24.0, "audio": [take_id, 2],
                   "bit_depth": 8, "color_space": "sRGB",
                   "chroma_subsampling": "auto", "codec": "h264"},
    }
    save = {
        "class_type": "SaveVideo",
        "inputs": {"video": ["5", 0], "filename_prefix": prefix,
                   "format": "auto", "codec": "auto"},
    }
    return {"5": create, "6": save}


def single() -> dict:
    """文生视频示例：最单纯的一条链，用来验收 M1。"""
    return {
        "1": loader_node(),
        "2": config_node(),
        "3": script_node(),
        "4": take_node("4", "1", "2", "3"),
        **output_nodes("4", "DirectorDeck/M1_single"),
    }


def ref2va() -> dict:
    """参考生视频示例：两张参考图进槽 1/2，再用 SegmentBrief 覆盖第一段文案。"""
    graph = {
        "1": loader_node(),
        "2": config_node(),
        "3": script_node(),
        # 两张参考图 -> AssetShelf 槽 1/2（LoadImage 从 input 目录读）
        "7": {"class_type": "LoadImage", "inputs": {"image": "11.png"}},
        "8": {"class_type": "LoadImage", "inputs": {"image": "睡衣.png"}},
        "9": {"class_type": "DirectorDeck_AssetShelf",
              "inputs": {"image_1": ["7", 0], "image_2": ["8", 0]}},
        "4": take_node("4", "1", "2", "3", assets="9"),
        **output_nodes("4", "DirectorDeck/M1_ref2va"),
    }
    # 用 SegmentBrief 覆盖第一段正文：明确演示 @图片1/@图片2 怎么绑素材。
    graph["4"]["inputs"]["brief_policy"] = "replace"
    graph["10"] = {"class_type": "DirectorDeck_SegmentBrief",
                   "inputs": {"text": "@图片1 的女孩穿着 @图片2 的衣服在海边散步，电影感缓慢推镜。",
                              "seconds": 5.0, "dialogue": "", "refs": "1,2"}}
    graph["4"]["inputs"]["brief"] = ["10", 0]
    return graph


def m2_chain() -> dict:
    """M2 三链示例：3 段 × 5s 续写 -> 合并 -> 出片。

    三段共用同一份模型/配置/剧本；第 2、3 段通过 previous_segment 接上一段，
    continuity=guide_tail 让生成器自动取上一段尾巴做画面+音轨引导。
    """
    graph = {
        "1": loader_node(),
        "2": config_node(),
        "3": script_node(),
        "4": {"class_type": "DirectorDeck_FramePlanner",
              "inputs": {"script": ["3", 0], "config": ["2", 0], "keep_full": True}},
    }
    # 三次生成：注意 bundle_policy 第一段 provided、后面 inherit；continuity 首段 start、后面 guide_tail。
    gen = [
        {"id": "10", "index": 1, "bundle_policy": "provided",
         "continuity": "start", "assets_policy": "clear"},
        {"id": "11", "index": 2, "bundle_policy": "inherit",
         "continuity": "guide_tail", "assets_policy": "inherit"},
        {"id": "12", "index": 3, "bundle_policy": "inherit",
         "continuity": "guide_tail", "assets_policy": "inherit"},
    ]
    for item in gen:
        inputs = {
            "bundle": ["1", 0],
            "config": ["2", 0],
            "script": ["3", 0],
            "segment_index": item["index"],
            "bundle_policy": item["bundle_policy"],
            "config_policy": "inherit",
            "assets_policy": item["assets_policy"],
            "brief_policy": "inherit",
            "cast_policy": "inherit",
            "continuity": item["continuity"],
            "seed": 0,
            "cache_mode": "auto",
        }
        if item["index"] > 1:
            # 第 2 段接第 1 段（节点 10），第 3 段接第 2 段（节点 11）。
            inputs["previous_segment"] = [{"2": "10", "3": "11"}[str(item["index"])], 0]
        graph[item["id"]] = {"class_type": "DirectorDeck_DirectorTake", "inputs": inputs}

    # 合并三段：调 FinalCut 的 segment/images/audio 三组输入。
    cut_inputs = {
        "segment_1": ["10", 0], "images_1": ["10", 1], "audio_1": ["10", 2],
        "segment_2": ["11", 0], "images_2": ["11", 1], "audio_2": ["11", 2],
        "segment_3": ["12", 0], "images_3": ["12", 1], "audio_3": ["12", 2],
    }
    graph["20"] = {"class_type": "DirectorDeck_FinalCut", "inputs": cut_inputs}
    graph["21"] = {"class_type": "CreateVideo",
                   "inputs": {"images": ["20", 0], "fps": 24.0, "audio": ["20", 1],
                              "bit_depth": 8, "color_space": "sRGB",
                              "chroma_subsampling": "auto", "codec": "h264"}}
    graph["22"] = {"class_type": "SaveVideo",
                   "inputs": {"video": ["21", 0], "filename_prefix": "DirectorDeck/M2_chain",
                              "format": "auto", "codec": "auto"}}
    return graph


def m2_reroll() -> dict:
    """M2 抽卡示例：只换第 2 段的 seed（其余不动），验证“前段复用、只重抽一段”。

    ComfyUI 会按 IS_CHANGED 缓存上游：第 1 段节点没变 -> 直接复用；
    第 2 段种子变了 -> 重跑；第 3 段依赖第 2 段的尾帧 -> 跟着重跑。
    """
    graph = copy.deepcopy(m2_chain())
    graph["11"]["inputs"]["seed"] = 88888
    graph["22"]["inputs"]["filename_prefix"] = "DirectorDeck/M2_reroll_seg2"
    return graph


def m3_digital_human() -> dict:
    """M3 数字人锁音 + 二采示例。

    链路：LoadAudio（一段 16.5s 音频）-> VoiceLock（女主: 槽1, 0.0s）
          -> Take（真锁音生成 5s 段）-> 存一版 raw
          -> Refiner（latent 二采 denoise=0.2 steps=4）-> 存一版 refined
    """
    graph = {
        "1": loader_node(),
        "2": config_node(),
        "3": script_node(),
        "5": {"class_type": "LoadAudio", "inputs": {"audio": "directordeck_voice.wav"}},
        "6": {"class_type": "DirectorDeck_VoiceLock",
              "inputs": {"roles": "女主: 1, 0.0", "lock_audio": True,
                         "audio_1": ["5", 0]}},
        "10": {"class_type": "DirectorDeck_DirectorTake",
               "inputs": {
                   "bundle": ["1", 0], "config": ["2", 0], "script": ["3", 0],
                   "segment_index": 1, "bundle_policy": "provided",
                   "config_policy": "inherit", "assets_policy": "clear",
                   "brief_policy": "inherit", "cast_policy": "replace",
                   "continuity": "start", "seed": 0, "cache_mode": "auto", "cast": ["6", 0]}},
        # 一采原片
        "21": {"class_type": "CreateVideo",
               "inputs": {"images": ["10", 1], "fps": 24.0, "audio": ["10", 2],
                          "codec": "h264"}},
        "22": {"class_type": "SaveVideo",
               "inputs": {"video": ["21", 0], "filename_prefix": "DirectorDeck/M3_lock_raw",
                          "format": "auto", "codec": "auto"}},
        # 二采（低 denoise 再采样，音频锁定）
        "20": {"class_type": "DirectorDeck_Refiner",
               "inputs": {"bundle": ["1", 0], "segment": ["10", 0],
                          "images": ["10", 1], "audio": ["10", 2],
                          "mode": "latent_2nd", "denoise": 0.2, "steps": 4,
                          "sampler_name": "er_sde", "scheduler": "beta",
                          "upscale": 2.0}},
        "31": {"class_type": "CreateVideo",
               "inputs": {"images": ["20", 1], "fps": 24.0, "audio": ["20", 2],
                          "codec": "h264"}},
        "32": {"class_type": "SaveVideo",
               "inputs": {"video": ["31", 0],
                          "filename_prefix": "DirectorDeck/M3_lock_refined",
                          "format": "auto", "codec": "auto"}},
    }
    return graph


def m4_lock_finalcut() -> dict:
    """M4 示例：锁音段 -> FinalCut（直接混源音频）-> mp4 + wav。

    验证点：成片音轨与源 wav 逐样点一致（不再经过音频 VAE 的相位重建）。
    """
    graph = {
        "1": loader_node(),
        "2": config_node(),
        "3": script_node(),
        "5": {"class_type": "LoadAudio", "inputs": {"audio": "directordeck_voice.wav"}},
        "6": {"class_type": "DirectorDeck_VoiceLock",
              "inputs": {"roles": "女主: 1, 0.0", "lock_audio": True,
                         "audio_1": ["5", 0]}},
        "10": {"class_type": "DirectorDeck_DirectorTake",
               "inputs": {
                   "bundle": ["1", 0], "config": ["2", 0], "script": ["3", 0],
                   "segment_index": 1, "bundle_policy": "provided",
                   "config_policy": "inherit", "assets_policy": "clear",
                   "brief_policy": "inherit", "cast_policy": "replace",
                   "continuity": "start", "seed": 0, "cache_mode": "auto", "cast": ["6", 0]}},
        "40": {"class_type": "DirectorDeck_FinalCut",
               "inputs": {"segment_1": ["10", 0], "images_1": ["10", 1],
                          "audio_1": ["10", 2], "save_manifest": True,
                          "audio_from_source": True}},
        "41": {"class_type": "CreateVideo",
               "inputs": {"images": ["40", 0], "fps": 24.0, "audio": ["40", 1],
                          "codec": "h264"}},
        "42": {"class_type": "SaveVideo",
               "inputs": {"video": ["41", 0],
                          "filename_prefix": "DirectorDeck/M4_lock_source_audio",
                          "format": "auto", "codec": "auto"}},
        "43": {"class_type": "SaveAudio",
               "inputs": {"audio": ["40", 1],
                          "filename_prefix": "DirectorDeck/M4_lock_source"}},
    }
    return graph


def m5_latent_chain() -> dict:
    """M5.5 示例：latent 尾帧续写（两段）。

    第 2 段 continuity=latent_tail：生成器直接把上一段 latent 的尾部 token
    搬进新 latent 开头并设 noise_mask=0，省掉 RGB 解码/编码的绕路。
    """
    graph = {
        "1": loader_node(),
        "2": config_node(),
        "3": script_node(),
        "10": take_node("10", "1", "2", "3"),
        "11": {
            "class_type": "DirectorDeck_DirectorTake",
            "inputs": {
                "bundle": ["1", 0], "config": ["2", 0], "script": ["3", 0],
                "segment_index": 2, "bundle_policy": "inherit",
                "config_policy": "inherit", "assets_policy": "inherit",
                "brief_policy": "inherit", "cast_policy": "inherit",
                "continuity": "latent_tail", "seed": 0, "cache_mode": "auto",
                "previous_segment": ["10", 0],
            },
        },
        "20": {"class_type": "DirectorDeck_FinalCut",
               "inputs": {"segment_1": ["10", 0], "images_1": ["10", 1],
                          "audio_1": ["10", 2],
                          "segment_2": ["11", 0], "images_2": ["11", 1],
                          "audio_2": ["11", 2],
                          "save_manifest": True, "audio_from_source": False}},
        "21": {"class_type": "CreateVideo",
               "inputs": {"images": ["20", 0], "fps": 24.0, "audio": ["20", 1],
                          "codec": "h264"}},
        "22": {"class_type": "SaveVideo",
               "inputs": {"video": ["21", 0],
                          "filename_prefix": "DirectorDeck/M5_latent_chain",
                          "format": "auto", "codec": "auto"}},
    }
    return graph


def main() -> int:
    os.makedirs(EXAMPLE_DIR, exist_ok=True)
    for name, graph in (("m1_single_segment_api", single()),
                        ("m1_ref2va_api", ref2va()),
                        ("m2_chain_api", m2_chain()),
                        ("m2_reroll_seg2_api", m2_reroll()),
                        ("m3_digital_human_api", m3_digital_human()),
                        ("m4_lock_finalcut_api", m4_lock_finalcut()),
                        ("m5_latent_chain_api", m5_latent_chain())):
        path = os.path.join(EXAMPLE_DIR, name + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(graph, fh, ensure_ascii=False, indent=2)
        print("written:", path, "| nodes:", len(graph))
    return 0


if __name__ == "__main__":
    sys.exit(main())
