"""DirectorDeck · 视频生成器（M2）。

M2 在 M1 单段基础上加了“链式续写”：
- 输入里多了 previous_segment（上一段的输出）；
- 当 continuity=guide_tail 时，把上一段尾巴的画面/音轨用 AddGuide 钉在本段开头；
- 生成完自动做接缝曝光修正（只修交付帧，不动衔接头）；
- 把尾帧/尾音/素材快照放进进程内仓库，供下一段取用（segment 里只带 store_key）。

M1 的规矩不变：6 个 policy 必须显式指定，没选就报错；模型只允许链首指定。
"""

from __future__ import annotations

import hashlib
import json
import os
import time

import numpy as np
from PIL import Image

import folder_paths

from ..adapters import av_latent, h3
from ..adapters import segment_store
from ..core import assets as assets_lib
from ..core import audio as audio_math
from ..core import frames, policy, seam
from ..core.types import (
    ASSETS_POLICIES, BRIEF_POLICIES, BUNDLE_POLICIES, CAST_POLICIES, CATEGORY,
    CONTINUITY_MODES, CONFIG_POLICIES, FPS, MAX_SEGMENTS, TYPE_ASSETS, TYPE_BRIEF,
    TYPE_BUNDLE, TYPE_CAST, TYPE_CONFIG, TYPE_SCRIPT, TYPE_SEGMENT, error,
)


def _empty_cast() -> dict:
    """M2 还没有 VoiceLock 节点，先给一个空音色表当默认。"""
    return {"schema": "DIRECTOR_CAST@1", "roles": [], "lock_audio": False}


def _frame_means(images) -> list[float]:
    """逐帧平均亮度（RGB 全通道均值）；接缝匹配只需要这个级别。"""
    return [float(v) for v in images.detach().float().mean(dim=(1, 2, 3)).cpu().tolist()]


def _slice_audio_tail(audio: dict, tail_frames: int) -> dict:
    """从音轨末尾切出“衔接头时长”那一段，用于给下一段做音频引导。"""
    sample_rate = int(audio.get("sample_rate", 48000))
    samples = int(round(tail_frames / FPS * sample_rate))
    waveform = audio["waveform"]
    start = max(0, waveform.shape[-1] - samples)
    return {"waveform": waveform[..., start:], "sample_rate": sample_rate}


def _timeline_start(script: dict, index: int, handoff_frames: int, config: dict) -> float:
    """算第 index 段（0 起）在整条时间轴上的起点（秒）。

    为什么要算它：锁音是按“整条时间轴”对齐音频的，
    不知道这一段从第几秒开始，就没法从台词音频里切对那一截。
    """
    total = 0.0
    segments = list((script or {}).get("segments") or [])
    default_seconds = float(config.get("segment_seconds", 5.0))
    for i in range(max(0, index)):
        seconds = (float(segments[i].get("seconds") or default_seconds)
                   if i < len(segments) else default_seconds)
        total += frames.segment_plan(i, seconds, handoff_frames).duration
    return total


class DirectorDeckTake:
    """按段生成视频（支持接上一段做续写）。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "generate"
    RETURN_TYPES = (TYPE_SEGMENT, "IMAGE", "AUDIO")
    RETURN_NAMES = ("segment", "images", "audio")
    OUTPUT_NODE = True
    DESCRIPTION = ("生成一段视频。第 2 段起请连接 previous_segment；"
                   "continuity=guide_tail 会把上一段尾巴钉到本段开头，实现无缝续写。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "bundle": (TYPE_BUNDLE, {"tooltip": "来自模型加载器（只能在链首指定）"}),
                "config": (TYPE_CONFIG, {"tooltip": "来自全局配置"}),
                "script": (TYPE_SCRIPT, {"tooltip": "来自剧本加载器"}),
                "segment_index": ("INT", {"default": 1, "min": 1, "max": MAX_SEGMENTS,
                                          "tooltip": "生成剧本里的第几段（1 起）"}),
                # 这 6 个 policy 故意默认 unset：必须用户自己选，不选直接报错。
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
                "cast": (TYPE_CAST, {"tooltip": "段级音色/锁音表（锁音生成时接 VoiceLock）"}),
                "previous_segment": (TYPE_SEGMENT, {"tooltip": "上一段的 segment 输出（第 2 段起必接）"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, bundle=None, config=None, script=None, assets=None,
                   brief=None, cast=None, previous_segment=None, **kwargs):
        key = dict(kwargs)
        key["config"] = config
        key["script"] = script
        key["brief"] = brief
        key["asset_hash"] = assets_lib.assets_hash(assets) if assets else None
        key["bundle_id"] = (bundle or {}).get("bundle_id")
        # cast 里有音频张量，不能直接序列化；用角色/起点/槽位做指纹即可。
        key["cast_roles"] = [
            (r.get("id"), r.get("start"), (r.get("voice") or {}).get("slot"))
            for r in (cast or {}).get("roles") or []
        ]
        key["cast_lock"] = bool((cast or {}).get("lock_audio"))
        # 上一段的运行期 store_key 含种子信息，变了说明必须重跑。
        key["prev_store_key"] = (previous_segment or {}).get("store_key")
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
            return 0
        offset = segment_index - 1
        if strategy == "fixed":
            return base
        if strategy == "increment":
            return (base + offset) & 0xFFFFFFFFFFFFFFFF
        return (base + offset * 7919) & 0xFFFFFFFFFFFFFFFF

    @staticmethod
    def _preview_ui(images) -> dict:
        """把首帧存成临时 png，让 ComfyUI 在节点上显示预览。"""
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

    @staticmethod
    def _restore_previous(previous_segment: dict | None, bundle: dict):
        """从内存仓库还原上一段的解析快照。

        为什么不在 segment 里直接存张量？因为 segment 要进 JSON（history/缓存），
        存张量会序列化失败。所以只存 store_key，真正的数据在 segment_store 里。
        """
        if previous_segment is None:
            return None
        store_key = previous_segment.get("store_key")
        snapshot = segment_store.get(store_key)
        if snapshot is None:
            raise error("DD-E008",
                        "找不到上一段的运行期画面数据（可能 ComfyUI 重启过或换了进程），"
                        "请重新运行上一段")
        resolved_meta = previous_segment.get("resolved") or {}
        return policy.Resolution(
            index=int(previous_segment.get("index", 1)) - 1,
            bundle=bundle,
            config=snapshot["config"],
            assets=snapshot["assets"],
            brief=snapshot.get("brief"),
            cast=snapshot["cast"],
            continuity=resolved_meta.get("continuity", "start"),
        ), snapshot

    # ------------------------------------------------------------------
    def generate(self, bundle, config, script, segment_index, bundle_policy,
                 config_policy, assets_policy, brief_policy, cast_policy,
                 continuity, seed=0, assets=None, brief=None, cast=None,
                 previous_segment=None):
        started = time.perf_counter()
        index = int(segment_index) - 1  # 内部用 0 起，方便帧数学

        # 1) 第 2 段起必须接上一段；否则“续写”就是假的。
        if index > 0 and previous_segment is None:
            raise error("DD-E008", f"第 {segment_index} 段必须连接上一段的 segment 输出（previous_segment）")

        previous_res = None
        prev_snapshot = None
        if index > 0:
            previous_res, prev_snapshot = self._restore_previous(previous_segment, bundle)

        # 2) 解析覆盖策略：index>0 时 bundle 只能继承，continuity 只能是 guide_tail/none。
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
        if cast is not None:
            sockets["cast"] = cast
        resolved = policy.resolve_segment(index=index, policies=policies,
                                          sockets=sockets, previous=previous_res,
                                          defaults=defaults)

        # 3) 找出本段剧本（brief 覆盖优先级最高）。
        segments = list((script or {}).get("segments") or [])
        if not 1 <= int(segment_index) <= len(segments):
            raise error("DD-E004",
                        f"segment_index={segment_index} 超出剧本范围（共 {len(segments)} 段）")
        segment = segments[int(segment_index) - 1]
        text = segment.get("text", "")
        seconds = float(segment.get("seconds") or config.get("segment_seconds", 5.0))
        if resolved.brief:
            text = resolved.brief.get("text", text)
            seconds = float(resolved.brief.get("seconds") or seconds)
        prompt = assets_lib.bind_prompt(text, resolved.assets)

        # 4) 帧计划：注意这里是“第 index 段”，不是永远第 1 段。
        timeline_start = _timeline_start(script, index,
                                         config.get("handoff_frames", 22), config)
        plan = frames.segment_plan(index, seconds, config.get("handoff_frames", 22),
                                   previous_timeline=timeline_start)
        length = frames.validate_length(plan.sample)
        width, height = frames.validate_canvas(config["width"], config["height"])

        # 5) 条件 + 空 latent。
        ref_images = assets_lib.image_tensors(resolved.assets)
        mode = "ref2va" if ref_images else "t2va"
        cond, latent = h3.build_conditioning(
            bundle, mode=mode, prompt=prompt, width=width, height=height,
            length=length, ref_images=ref_images)

        # 5.5) 数字人锁音：把 cast 里的音轨按时间轴铺好，锁进音频流。
        #      这是“真锁音”——不是 AddGuide 的条件锚定，而是 noise_mask=0。
        lock_info = {"applied": False}
        locked_audio_latent = None
        lock_source_audio = None
        if resolved.cast.get("lock_audio"):
            roles_with_audio = [r for r in resolved.cast.get("roles") or []
                                if r.get("audio_data")]
            if roles_with_audio:
                # 本段的“真实时间区间”：采样头是上一段尾巴，所以起点要往前挪。
                seg_start, seg_end = audio_math.segment_span(
                    plan.timeline_start, plan.head, plan.sample)
                vae_rate = int(getattr(bundle["audio_vae"], "audio_sample_rate", 32000))
                track = av_latent.build_audio_track(
                    roles_with_audio, seg_start, seg_end, vae_rate)
                if float(track.abs().max()) > 0:
                    latent, locked_audio_latent = av_latent.lock_audio(
                        latent, bundle["audio_vae"], track, vae_rate)
                    # 源音轨留在运行期仓库里：成片合并时可以选“直接用源音频”，
                    # 做到逐样点无损（绕过神经音频编解码器的相位重建）。
                    lock_source_audio = {"waveform": track, "sample_rate": vae_rate}
                    lock_info = {
                        "applied": True,
                        "roles": [r.get("name") for r in roles_with_audio],
                        "window": [round(seg_start, 3), round(seg_end, 3)],
                        "samples": int(track.shape[-1]),
                    }

        # 6) 续写引导：把上一段 delivery 的尾巴（head 帧）钉到本段第 0 帧，
        #    音轨也钉一段，这样画面和声音都能接上。
        guide_info = {"used": False, "head": plan.head, "audio": False}
        if plan.head > 0 and resolved.continuity == "guide_tail":
            tail_images = prev_snapshot["images_tail"]
            if tail_images.shape[0] < plan.head:
                raise error("DD-E008",
                            f"上一段可用的尾帧只有 {tail_images.shape[0]} 帧，"
                            f"不够衔接头 {plan.head} 帧")
            tail_images = tail_images[-plan.head:]
            if lock_info.get("applied"):
                # 音频已经被锁死了，就别再拿上一段音频去引导，否则两套声音打架。
                cond = h3.add_guide(bundle, cond, latent,
                                    image=tail_images, frame_idx=0)
                guide_info.update(used=True, audio=False)
            else:
                tail_audio = _slice_audio_tail(prev_snapshot["audio_full"], plan.head)
                cond = h3.add_guide(bundle, cond, latent, image=tail_images,
                                    audio=tail_audio, frame_idx=0)
                guide_info.update(used=True, audio=True)

        # 7) 采样 + 解码。
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
        # 7.5) 锁音兜底恢复：确保采样后的音频流还是我们锁进去的那一版。
        if locked_audio_latent is not None:
            sampled = av_latent.restore_audio(sampled, locked_audio_latent)

        images = h3.decode_video(bundle, sampled)
        audio = h3.decode_audio(bundle, sampled)
        actual_seed = int(sampled.get("_director_seed", final_seed))

        # 8) 接缝曝光修正：拿上一段尾巴和本段交付帧开头比，修本段交付部分。
        seam_info = None
        if plan.head > 0 and prev_snapshot is not None and config.get("seam_enabled", True):
            window = int(config.get("seam_window", seam.WINDOW_DEFAULT))
            prev_tail = prev_snapshot.get("seam_tail")
            if prev_tail is not None and prev_tail.shape[0] >= 2:
                cur_head_means = _frame_means(images[plan.head:plan.head + window])
                seam_info = seam.exposure_plan(
                    _frame_means(prev_tail), cur_head_means, window=window,
                    max_add=float(config.get("seam_max_add", seam.MAX_ADD_DEFAULT)),
                    gain_limit=float(config.get("seam_gain_limit", seam.GAIN_LIMIT_DEFAULT)))
                if seam_info.get("apply"):
                    fixed = images.clone()
                    adjusted = (fixed[plan.head:] * float(seam_info["gain"])
                                + float(seam_info["offset"])).clamp(0.0, 1.0)
                    fixed[plan.head:] = adjusted
                    images = fixed

        # 9) 把本段的运行期数据放进仓库：下一段靠它拿尾帧/尾音。
        store_key = hashlib.sha1(
            f"{resolved.hash}|{prompt}|{actual_seed}|{tuple(images.shape)}"
            .encode("utf-8")).hexdigest()[:24]
        segment_store.put(store_key, {
            # 尾帧最多留 56 帧（衔接头上限），下一段按自己的 head 取用。
            "images_tail": images[-min(56, images.shape[0]):].clone(),
            # 接缝匹配只看最后 24 帧。
            "seam_tail": images[-min(24, images.shape[0]):].clone(),
            "audio_full": audio,
            # 锁音时的源音轨（成片可直接混流，做到逐样点无损）。
            "lock_source_audio": lock_source_audio,
            "config": resolved.config,
            "assets": resolved.assets,
            "cast": resolved.cast,
            "brief": resolved.brief,
        })

        elapsed = time.perf_counter() - started
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
            "store_key": store_key,
            "guide": guide_info,
            "lock": lock_info,
            "seam": seam_info,
        }
        ui = self._preview_ui(images) if config.get("preview", True) else {}
        # 把段元数据落盘一份（不含张量），方便抽卡/排错/回放；写失败不影响出图。
        try:
            output_root = os.path.join(folder_paths.get_output_directory(),
                                       config.get("output_dir", "DirectorDeck"),
                                       "segments")
            os.makedirs(output_root, exist_ok=True)
            meta_path = os.path.join(output_root, f"seg_{int(segment_index):02d}_{store_key}.json")
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            result["meta_path"] = meta_path
        except Exception as exc:  # 元数据写不进去不影响出片
            print(f"[DirectorDeck] 段元数据落盘失败：{exc}")

        print(f"[DirectorDeck] 第 {segment_index} 段完成：{result['frames']} 帧，"
              f"{elapsed:.1f}s，seed={actual_seed}，guide={guide_info['used']}，"
              f"lock={lock_info.get('applied')}，seam={seam_info and seam_info.get('apply')}")
        return {"ui": ui, "result": (result, images, audio)}
