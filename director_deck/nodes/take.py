"""DirectorDeck · 视频生成器（M1 单段）。

输入：bundle / config / script + 可选的 assets / brief（段级覆盖），以及 6 个必须显式指定的 policy。
输出：DIRECTOR_SEGMENT（含解析后输入快照）+ IMAGE（成片帧）+ AUDIO。

M1 只做单段；M2 起接 previous_segment 实现“上一段尾巴接下一段”的链式续写。
"""

from __future__ import annotations

import hashlib
import json
import os
import time

import numpy as np
from PIL import Image

import folder_paths

from ..adapters import h3
from ..core import assets as assets_lib
from ..core import frames, policy
from ..core.types import (
    ASSETS_POLICIES, BRIEF_POLICIES, BUNDLE_POLICIES, CAST_POLICIES, CATEGORY,
    CONTINUITY_MODES, CONFIG_POLICIES, MAX_SEGMENTS, TYPE_ASSETS, TYPE_BRIEF,
    TYPE_BUNDLE, TYPE_CONFIG, TYPE_SCRIPT, TYPE_SEGMENT, error,
)


def _empty_cast() -> dict:
    """M1 还没有 VoiceLock 节点，先给一个空音色表当默认。"""
    return {"schema": "DIRECTOR_CAST@1", "roles": [], "lock_audio": False}


class DirectorDeckTake:
    """按段生成视频：解析覆盖策略 -> 条件 -> 采样 -> 解码，输出段结果。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "generate"
    RETURN_TYPES = (TYPE_SEGMENT, "IMAGE", "AUDIO")
    RETURN_NAMES = ("segment", "images", "audio")
    OUTPUT_NODE = True
    DESCRIPTION = ("生成一段视频。段级可接自己的资产管理器/剧本片段（覆盖），"
                   "不接则按 policy 沿用；所有 policy 必须显式选择，未指定会报错。")

    @classmethod
    def INPUT_TYPES(cls):
        # 注意：这 6 个 policy 的默认值故意是 unset —— 用户必须自己选，
        # 不选会在 generate 里直接报 DD-E001，绝不静默继承。
        return {
            "required": {
                "bundle": (TYPE_BUNDLE, {"tooltip": "来自模型加载器（只能在链首指定）"}),
                "config": (TYPE_CONFIG, {"tooltip": "来自全局配置"}),
                "script": (TYPE_SCRIPT, {"tooltip": "来自剧本加载器"}),
                "segment_index": ("INT", {"default": 1, "min": 1, "max": MAX_SEGMENTS,
                                          "tooltip": "生成剧本里的第几段（1 起）"}),
                "bundle_policy": (list(BUNDLE_POLICIES), {"default": "unset"}),
                "config_policy": (list(CONFIG_POLICIES), {"default": "unset"}),
                "assets_policy": (list(ASSETS_POLICIES), {"default": "unset"}),
                "brief_policy": (list(BRIEF_POLICIES), {"default": "unset"}),
                "cast_policy": (list(CAST_POLICIES), {"default": "unset"}),
                "continuity": (list(CONTINUITY_MODES), {"default": "unset"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                                 "tooltip": "0=按全局种子策略"}),
            },
            "optional": {
                "assets": (TYPE_ASSETS, {"tooltip": "段级资产管理器（覆盖/合并）"}),
                "brief": (TYPE_BRIEF, {"tooltip": "段级剧本片段（覆盖脚本段落）"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, bundle=None, config=None, script=None, assets=None,
                   brief=None, **kwargs):
        # 缓存键：能序列化的都放进去，模型对象只用 bundle_id；
        # 素材用元数据哈希（图片张量不参与，太不稳定）。
        key = dict(kwargs)
        key["config"] = config
        key["script"] = script
        key["brief"] = brief
        key["asset_hash"] = assets_lib.assets_hash(assets) if assets else None
        key["bundle_id"] = (bundle or {}).get("bundle_id")
        return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False,
                                       default=str).encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_seed(config: dict, node_seed: int, segment_index: int) -> int:
        """按节点 seed / 全局种子策略算本段 seed；返回 0 表示交给采样器随机。"""
        if int(node_seed) > 0:
            return int(node_seed)
        base = int(config.get("seed_base") or 0)
        strategy = config.get("seed_strategy", "per_segment")
        if base <= 0:
            return 0  # 交给采样器随机，并把实际种子写回 segment
        offset = segment_index - 1
        if strategy == "fixed":
            return base
        if strategy == "increment":
            return (base + offset) & 0xFFFFFFFFFFFFFFFF
        # per_segment：用质数错开，避免相邻段撞种子
        return (base + offset * 7919) & 0xFFFFFFFFFFFFFFFF

    @staticmethod
    def _preview_ui(images) -> dict:
        """把首帧存成临时 png，让 ComfyUI 在节点上显示预览（M1 的“预览”实现）。"""
        try:
            temp_dir = folder_paths.get_temp_directory()
            os.makedirs(temp_dir, exist_ok=True)
            frame = images[0].detach().cpu().numpy()
            arr = (np.clip(frame, 0.0, 1.0) * 255.0).astype(np.uint8)
            name = f"directordeck_take_{int(time.time() * 1000)}.png"
            Image.fromarray(arr).save(os.path.join(temp_dir, name))
            return {"images": [{"filename": name, "subfolder": "", "type": "temp"}]}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    def generate(self, bundle, config, script, segment_index, bundle_policy,
                 config_policy, assets_policy, brief_policy, cast_policy,
                 continuity, seed=0, assets=None, brief=None):
        started = time.perf_counter()

        # 1) 把 6 个策略和实际连线交给解析器，得到“这一段到底用什么”。
        policies = {
            "bundle_policy": bundle_policy,
            "config_policy": config_policy,
            "assets_policy": assets_policy,
            "brief_policy": brief_policy,
            "cast_policy": cast_policy,
            "continuity": continuity,
        }
        defaults = {
            "bundle": bundle,
            "config": config,
            "assets": assets_lib.empty_assets(),
            "brief": None,
            "cast": _empty_cast(),
        }
        sockets = {"bundle": bundle}
        if assets is not None:
            sockets["assets"] = assets
        if brief is not None:
            sockets["brief"] = brief
        resolved = policy.resolve_segment(index=0, policies=policies,
                                          sockets=sockets, previous=None,
                                          defaults=defaults)

        # 2) 找到要生成的段落（M1 单段，所以 index 固定 0，但段落号可以选）。
        segments = list((script or {}).get("segments") or [])
        if not 1 <= int(segment_index) <= len(segments):
            raise error("DD-E004",
                        f"segment_index={segment_index} 超出剧本范围（共 {len(segments)} 段）")
        segment = segments[int(segment_index) - 1]
        text = segment.get("text", "")
        seconds = float(segment.get("seconds") or config.get("segment_seconds", 5.0))
        # 段级 brief 优先级最高：接管正文和秒数。
        if resolved.brief:
            text = resolved.brief.get("text", text)
            seconds = float(resolved.brief.get("seconds") or seconds)

        # 3) 绑定素材引用：@图片N -> <Picture N>，并校验空槽/越界。
        prompt = assets_lib.bind_prompt(text, resolved.assets)

        # 4) 帧计划：秒数 -> 17k+5，再反推 H3 的 length。
        plan = frames.segment_plan(0, seconds, config.get("handoff_frames", 22))
        length = frames.validate_length(plan.sample)
        width, height = frames.validate_canvas(config["width"], config["height"])

        # 5) 有条件就参考生视频，没条件就文生视频。
        ref_images = assets_lib.image_tensors(resolved.assets)
        mode = "ref2va" if ref_images else "t2va"
        cond, latent = h3.build_conditioning(
            bundle, mode=mode, prompt=prompt, width=width, height=height,
            length=length, ref_images=ref_images)

        # 6) 采样。
        final_seed = self._resolve_seed(config, seed, int(segment_index))
        sampled = h3.sample(
            bundle, cond, latent, seed=final_seed,
            sampler_name=config.get("sampler_name", "er_sde"),
            scheduler=config.get("scheduler", "beta"),
            steps=int(config.get("steps", 10)),
            denoise=float(config.get("denoise", 1.0)),
            sigmas_string=(config.get("sigmas_string") or None),
            interpolate_to_steps=int(config.get("interpolate_to_steps", 0)),
        )

        # 7) 解码成画面 + 音轨。
        images = h3.decode_video(bundle, sampled)
        audio = h3.decode_audio(bundle, sampled)
        actual_seed = int(sampled.get("_director_seed", final_seed))

        elapsed = time.perf_counter() - started
        # 8) 段元数据：把“用了什么”完整记录下来，后面抽卡/二采/排错全靠它。
        result = {
            "schema": "DIRECTOR_SEGMENT@1",
            "index": int(segment_index),
            "chain_key": resolved.hash,
            "resolved": resolved.to_dict(),
            "mode": mode,
            "prompt": prompt,
            "width": width,
            "height": height,
            "frames": int(images.shape[0]),
            "head": plan.head,
            "delivery": plan.delivery,
            "sample": plan.sample,
            "seed": actual_seed,
            "sigmas": sampled.get("_director_sigmas"),
            "elapsed_s": round(elapsed, 2),
            "preview": bool(config.get("preview", True)),
        }
        ui = self._preview_ui(images) if config.get("preview", True) else {}
        print(f"[DirectorDeck] 第 {segment_index} 段完成：{result['frames']} 帧，"
              f"{elapsed:.1f}s，seed={actual_seed}，mode={mode}")
        return {"ui": ui, "result": (result, images, audio)}
