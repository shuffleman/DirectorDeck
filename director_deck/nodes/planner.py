"""DirectorDeck · 帧计划器（M2）：把剧本 + 配置算成每段怎么切帧。

为什么单独一个节点？
生成器只负责“第 N 段怎么生成”，但整条链的帧数/衔接/时间轴必须先算清楚，
不然每段各算各的很容易对不上（下一段的 head 需要上一段的 delivery 信息）。
这个节点输出一张“施工蓝图”，人可以看，机器也能用。
"""

from __future__ import annotations

import hashlib
import json

from ..core import frames
from ..core.types import CATEGORY, FPS, TYPE_CONFIG, TYPE_PLAN, TYPE_SCRIPT


class DirectorDeckFramePlanner:
    """按剧本+配置生成整条链的帧计划（DIRECTOR_PLAN）。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "plan"
    RETURN_TYPES = (TYPE_PLAN, "STRING")
    RETURN_NAMES = ("plan", "summary")
    DESCRIPTION = ("把剧本的每段秒数换算成 H3 的 17k+5 帧计划："
                   "head（衔接头）/delivery（交付帧）/sample（采样长度）/timeline_start。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "script": (TYPE_SCRIPT, {"tooltip": "剧本加载器的输出"}),
                "config": (TYPE_CONFIG, {"tooltip": "全局配置（提供 handoff_frames 等）"}),
            },
            "optional": {
                "keep_full": ("BOOLEAN", {"default": True,
                                          "tooltip": "是否把补栅格多出来的尾巴也算进交付帧（默认开）"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return hashlib.sha1(json.dumps(kwargs, sort_keys=True, ensure_ascii=False,
                                       default=str).encode("utf-8")).hexdigest()

    def plan(self, script, config, keep_full=True):
        segments = list((script or {}).get("segments") or [])
        if not segments:
            # 没有段落也要能过图，给个空计划而不是直接崩。
            return ({"schema": "DIRECTOR_PLAN@1", "segments": [], "total_frames": 0,
                     "total_duration": 0.0, "fps": FPS}, "剧本为空，没有可计划的段落")
        plans = frames.plan_chain(segments, int(config.get("handoff_frames", 22)),
                                  keep_full=bool(keep_full))
        data = {
            "schema": "DIRECTOR_PLAN@1",
            "segments": [p.to_dict() for p in plans],
            "total_frames": frames.total_frames(plans),
            "total_duration": round(frames.total_duration(plans), 3),
            "fps": FPS,
        }
        lines = [f"{p.index + 1}. head={p.head} delivery={p.delivery} "
                 f"sample={p.sample} @ {p.timeline_start:.2f}s" for p in plans]
        summary = (f"{len(plans)} 段 / {data['total_frames']} 帧 / "
                   f"{data['total_duration']}s\n" + "\n".join(lines))
        return (data, summary)
