"""DirectorDeck · 多段合并器（M2）：把各段交付帧拼成一条成片。

合并规则（和 H3 的续写逻辑配套）：
- 第 1 段：原样保留（head=0）；
- 之后每段：丢掉开头的 head 帧（那是上一段的重复尾巴，只用来给模型做引导），
  只留 delivery 部分；
- 音轨同理：按 head/24 秒裁掉开头，再首尾相接。

输出：IMAGE（整片帧）、AUDIO（整片音轨）、DIRECTOR_MANIFEST（清单，M2 先给结构，M5 落盘）。
"""

from __future__ import annotations

import json
import os
import time

import folder_paths
import torch

from ..adapters import segment_store
from ..core.types import CATEGORY, FPS, TYPE_MANIFEST, TYPE_SEGMENT

MAX_SEGMENTS = 4  # M2 先支持 4 段（15~20 秒），M4 再扩到任意段


class DirectorDeckFinalCut:
    """多段合并：裁衔接头 -> 拼画面 -> 拼音轨 -> 出清单。"""

    CATEGORY = f"{CATEGORY}/输出"
    FUNCTION = "merge"
    RETURN_TYPES = ("IMAGE", "AUDIO", TYPE_MANIFEST)
    RETURN_NAMES = ("images", "audio", "manifest")
    DESCRIPTION = ("把最多 4 段按顺序合并：自动裁掉衔接头，音轨按同样规则裁剪后拼接。")

    @classmethod
    def INPUT_TYPES(cls):
        required = {
            "segment_1": (TYPE_SEGMENT, {"tooltip": "第 1 段元数据"}),
            "images_1": ("IMAGE", {"tooltip": "第 1 段画面"}),
            "audio_1": ("AUDIO", {"tooltip": "第 1 段音轨"}),
        }
        optional = {}
        for index in range(2, MAX_SEGMENTS + 1):
            optional[f"segment_{index}"] = (TYPE_SEGMENT, {"tooltip": f"第 {index} 段元数据"})
            optional[f"images_{index}"] = ("IMAGE", {"tooltip": f"第 {index} 段画面"})
            optional[f"audio_{index}"] = ("AUDIO", {"tooltip": f"第 {index} 段音轨"})
        # 清单落盘开关：想留档就开，只想快速看片就关。
        optional["save_manifest"] = ("BOOLEAN", {"default": True,
                                                 "tooltip": "把合并清单写到 output/DirectorDeck/manifests/"})
        # 源音频混流：数字人锁音段可以直接用“当初锁进去的源音轨”，
        # 做到逐样点无损；不开则用段解码出来的音轨（会经过神经音频 VAE）。
        optional["audio_from_source"] = ("BOOLEAN", {"default": False,
                                                     "tooltip": "锁音段优先使用源音轨（无损），M4 新增"})
        # 段边界音频交叉淡化（跨段 ducking/生成音频的衔接更自然）。
        optional["audio_crossfade_ms"] = ("INT", {"default": 0, "min": 0, "max": 500,
                                                 "tooltip": "段边界等功率交叉淡化时长（毫秒），0=硬接"})
        return {"required": required, "optional": optional}

    @staticmethod
    def _source_audio_full(segment: dict) -> dict | None:
        """从运行期仓库拿“锁音源轨”（整段采样长度，含衔接头），供 FinalCut 裁剪/交叉淡化。

        为什么存整段而不是只存交付部分：交叉淡化需要段开头的重叠区（head 帧），
        只留交付部分就没法在边界上做等功率淡化了。
        """
        store_key = segment.get("store_key")
        if not store_key:
            return None
        snapshot = segment_store.get(store_key)
        if not snapshot:
            return None
        source = snapshot.get("lock_source_audio")
        if not source:
            return None
        return {"waveform": source["waveform"], "sample_rate": int(source["sample_rate"])}

    @staticmethod
    def _equal_power(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        """两段等长音频的等功率交叉淡化（a→b），返回同长度张量。"""
        import math
        n = min(int(a.shape[-1]), int(b.shape[-1]))
        if n <= 0:
            return a[..., :0]
        phase = torch.linspace(0.0, math.pi / 2.0, n + 2)[1:-1].view(1, 1, n)
        return a[..., -n:] * torch.cos(phase) + b[..., :n] * torch.sin(phase)

    @staticmethod
    def _trim_audio(audio: dict, head_frames: int) -> dict:
        """按衔接头帧数裁掉音轨开头；裁完再返回同结构的 AUDIO。"""
        waveform = audio["waveform"]
        sample_rate = int(audio.get("sample_rate", 48000))
        start = int(round(head_frames / FPS * sample_rate))
        if start > 0:
            waveform = waveform[..., start:]
        return {"waveform": waveform, "sample_rate": sample_rate}

    def merge(self, segment_1, images_1, audio_1, save_manifest=True,
              audio_from_source=False, audio_crossfade_ms=0, **kwargs):
        pieces_images = []
        pieces_audio = []
        metas = []
        first = True
        # 按 1..4 顺序收集，没接的段直接跳过（允许只合 1~3 段）。
        for index in range(1, MAX_SEGMENTS + 1):
            segment = segment_1 if index == 1 else kwargs.get(f"segment_{index}")
            images = images_1 if index == 1 else kwargs.get(f"images_{index}")
            audio = audio_1 if index == 1 else kwargs.get(f"audio_{index}")
            if segment is None or images is None or audio is None:
                continue
            head = 0 if first else int(segment.get("head") or 0)
            delivery = int(images.shape[0]) - head
            # 画面：丢头帧，留 delivery（最后一帧就是段尾，不用再裁尾巴）。
            pieces_images.append(images[head:])
            # 音轨：优先用“锁音源轨”（无损，整段采样长度），否则用解码音轨。
            source_audio = self._source_audio_full(segment) if audio_from_source else None
            audio_piece = source_audio if source_audio is not None else audio
            pieces_audio.append({
                "waveform": audio_piece["waveform"].detach().float().cpu(),
                "sample_rate": int(audio_piece.get("sample_rate", 48000)),
                "head": head,
                "delivery": delivery,
                "source": source_audio is not None,
            })
            metas.append({
                "index": segment.get("index", index),
                "head": head,
                "delivery": delivery,
                "sample": int(images.shape[0]),
                "seed": segment.get("seed"),
                "prompt": segment.get("prompt"),
                "store_key": segment.get("store_key"),
                "audio_source": "source" if source_audio is not None else "decoded",
                "seam": segment.get("seam"),
            })
            first = False

        if not pieces_images:
            raise ValueError("FinalCut 至少需要连接一段（segment_1/images_1/audio_1）")

        images = torch.cat(pieces_images, dim=0)
        sample_rate = int(pieces_audio[0]["sample_rate"])
        for piece in pieces_audio[1:]:
            if int(piece["sample_rate"]) != sample_rate:
                raise ValueError("各段音轨采样率不一致，无法合并")

        # 边界等功率交叉淡化：用“本段衔接头最后 xfade 个采样点”和“上一段尾部 xfade 个采样点”混合，
        # 总时长不变（上一段去掉尾部 xfade、本段补回混合块 + 交付部分）。
        # 注意：segment 里的 head 是**帧数**，这里要换算成采样点。
        xfade = max(0, int(round(float(audio_crossfade_ms or 0) / 1000.0 * sample_rate)))
        audio_out = None
        for piece in pieces_audio:
            waveform = piece["waveform"]
            head_samples = int(round(int(piece["head"]) / FPS * sample_rate))
            if audio_out is None:
                audio_out = waveform
                continue
            usable = min(xfade, head_samples, int(waveform.shape[-1]) - head_samples)
            if usable > 0 and audio_out.shape[-1] >= usable:
                cross = self._equal_power(audio_out[..., -usable:],
                                          waveform[..., head_samples - usable:head_samples])
                audio_out = torch.cat([audio_out[..., :-usable], cross,
                                       waveform[..., head_samples:]], dim=-1)
            else:
                audio_out = torch.cat([audio_out, waveform[..., head_samples:]], dim=-1)
        audio = {"waveform": audio_out, "sample_rate": sample_rate}

        manifest = {
            "schema": "DIRECTOR_MANIFEST@1",
            "segments": metas,
            "total_frames": int(images.shape[0]),
            "duration": round(float(images.shape[0]) / FPS, 3),
            "fps": FPS,
            "audio_crossfade_ms": int(audio_crossfade_ms or 0),
        }
        # 清单落盘：这是“可复现/可追溯”的关键，二采和发布都要用。
        if save_manifest:
            try:
                out_root = os.path.join(folder_paths.get_output_directory(),
                                        "DirectorDeck", "manifests")
                os.makedirs(out_root, exist_ok=True)
                path = os.path.join(out_root, f"manifest_{time.strftime('%Y%m%d_%H%M%S')}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(manifest, fh, ensure_ascii=False, indent=2)
                manifest["path"] = path
            except Exception as exc:  # 落盘失败不影响成片
                print(f"[DirectorDeck] 清单落盘失败：{exc}")
        return (images, audio, manifest)
