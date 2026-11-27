"""生成 ComfyUI 画布可直接打开的工作流（UI 格式 version 0.4）。

为什么需要它：API 格式的 JSON 只能 POST /prompt，用户想在画布上改参数、拖线、看预览，
必须有 UI 格式。这个脚本从运行中的 ComfyUI（默认 8189）拉 object_info，
按每个节点的真实控件顺序拼 widgets_values，再用 ui_to_api() 反向还原成 API，
和 examples/ 里的 API 工作流逐输入对比，保证“画布能打开、参数没写错位置”。

产物：examples/ui/*.json（M1 单段 / M1 参考 / M2 三段链 / M3 数字人 / M4 锁音成片）
"""

from __future__ import annotations

import collections
import json
import os
import sys
import urllib.request
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_DIR = os.path.join(REPO, "examples")
UI_DIR = os.path.join(REPO, "examples", "ui")

# 哪些类型是“插头”（连线的），其余是控件（widgets_values）。
LINK_TYPES = {
    "MODEL", "CLIP", "VAE", "CONDITIONING", "LATENT", "IMAGE", "AUDIO", "VIDEO",
    "NOISE", "GUIDER", "SAMPLER", "SIGMAS", "MASK",
    # DirectorDeck 自定义类型
    "DIRECTOR_BUNDLE", "DIRECTOR_CONFIG", "DIRECTOR_CONFIG_OVERRIDE",
    "DIRECTOR_ASSETS", "DIRECTOR_SCRIPT", "DIRECTOR_BRIEF", "DIRECTOR_CAST",
    "DIRECTOR_PLAN", "DIRECTOR_SEGMENT", "DIRECTOR_MANIFEST",
    # 第三方（Breeze-TTS-2）：装了才有，没装时当普通插头类型处理
    "BREEZE_TTS2_MODEL", "BREEZE_SPEAKER",
}
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COMFY_DYNAMICCOMBO_V3"}
NO_SCHEMA_NODES = {"Note", "MarkdownNote"}

# 特殊情况手工补：SaveVideo 的 format 是动态组合，后面跟一个 format.codec 子控件。
MANUAL_SLOTS = {
    "SaveVideo": [("filename_prefix", "widget"), ("format", "widget"),
                  ("format.codec", "widget"), ("codec", "widget")],
}


def fetch_object_info(server: str) -> dict:
    with urllib.request.urlopen(server.rstrip("/") + "/object_info", timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def combo_options(spec) -> list:
    if not isinstance(spec, list) or not spec:
        return []
    first = spec[0]
    if isinstance(first, list):
        return list(first)
    if len(spec) >= 2 and isinstance(spec[1], dict) and isinstance(spec[1].get("options"), list):
        return list(spec[1]["options"])
    return []


def slot_default(spec):
    if isinstance(spec, list) and len(spec) >= 2 and isinstance(spec[1], dict):
        if "default" in spec[1]:
            return spec[1]["default"]
    options = combo_options(spec)
    return options[0] if options else 0


def widget_slots(oi: dict, cls: str) -> list[tuple[str, str, object]]:
    """返回 [(槽名, 类型, 默认值)]；顺序必须和 ComfyUI 前端建控件顺序一致。"""
    if cls in MANUAL_SLOTS:
        return [(name, kind, None) for name, kind in MANUAL_SLOTS[cls]]
    schema = oi[cls]
    spec_io = schema.get("input") or {}
    order = schema.get("input_order") or {}
    slots = []
    for group in ("required", "optional"):
        specs = spec_io.get(group) or {}
        for name in order.get(group) or []:
            spec = specs.get(name)
            if spec is None:
                continue
            typ = spec[0] if isinstance(spec, list) and spec else spec
            typ = typ if isinstance(typ, str) else "COMBO"
            if typ in LINK_TYPES or typ not in WIDGET_TYPES:
                continue
            slots.append((name, "widget", slot_default(spec)))
            if typ == "INT" and isinstance(spec, list) and len(spec) >= 2 \
                    and isinstance(spec[1], dict) and spec[1].get("control_after_generate"):
                slots.append((name + ".control", "control", "fixed"))
            if typ == "COMFY_DYNAMICCOMBO_V3":
                slots.append((name + ".codec", "widget", "auto"))
    return slots


MANUAL_SLOT_TYPES = {
    "filename_prefix": "STRING",
    "format": "COMFY_DYNAMICCOMBO_V3",
    "format.codec": "COMBO",
    "codec": "COMFY_DYNAMICCOMBO_V3",
}


def schema_entries(oi: dict, cls: str) -> list[dict]:
    """按 ComfyUI 顺序列出节点输入：插头 + 控件（含动态子控件）。"""
    schema = oi[cls]
    spec_io = schema.get("input") or {}
    order = schema.get("input_order") or {}

    # 手工覆盖的节点（SaveVideo）：插头从 schema 拿，控件按 MANUAL_SLOTS 顺序。
    if cls in MANUAL_SLOTS:
        entries = []
        for group in ("required", "optional"):
            specs = spec_io.get(group) or {}
            for name in order.get(group) or []:
                spec = specs.get(name)
                if spec is None:
                    continue
                typ = spec[0] if isinstance(spec, list) and spec else spec
                typ = typ if isinstance(typ, str) else "COMBO"
                if typ in LINK_TYPES:
                    entries.append({"name": name, "type": typ, "kind": "link"})
        for name, _kind in MANUAL_SLOTS[cls]:
            entries.append({"name": name,
                            "type": MANUAL_SLOT_TYPES.get(name, "COMBO"),
                            "kind": "widget"})
        return entries

    entries = []
    for group in ("required", "optional"):
        specs = spec_io.get(group) or {}
        for name in order.get(group) or []:
            spec = specs.get(name)
            if spec is None:
                continue
            typ = spec[0] if isinstance(spec, list) and spec else spec
            typ = typ if isinstance(typ, str) else "COMBO"
            if typ in LINK_TYPES:
                entries.append({"name": name, "type": typ, "kind": "link"})
            elif typ in WIDGET_TYPES:
                entries.append({"name": name, "type": typ, "kind": "widget"})
                if typ == "COMFY_DYNAMICCOMBO_V3":
                    entries.append({"name": name + ".codec", "type": "COMBO",
                                    "kind": "widget"})
    return entries


def build_ui(oi: dict, spec_nodes: list[dict], groups: list[dict], name: str) -> tuple[str, dict]:
    nodes = []
    links = []
    link_id = 0
    id2node = {}
    for spec in spec_nodes:
        cls = spec["type"]
        node_id = int(spec["id"])
        node = {
            "id": node_id,
            "type": cls,
            "pos": list(spec["pos"]),
            "size": list(spec.get("size", [320, 200])),
            "flags": {},
            "order": 0,
            "mode": int(spec.get("mode", 0)),
        }
        if spec.get("title"):
            node["title"] = spec["title"]
        if cls in NO_SCHEMA_NODES:
            node["inputs"] = []
            node["outputs"] = []
            node["properties"] = {}
            node["widgets_values"] = [spec.get("text", "")]
            nodes.append(node)
            id2node[node_id] = node
            continue

        # 控件值：spec 里给了就用，否则用 schema 默认值。
        values = dict(spec.get("values") or {})
        widgets_values = []
        for slot_name, kind, default in widget_slots(oi, cls):
            if slot_name in values:
                widgets_values.append(values[slot_name])
            elif default is not None:
                widgets_values.append(default)
            else:
                widgets_values.append("auto")

        # UI 的 inputs 列表：插头 + 控件（控件也占一个 input 条目，link=null）。
        entries = []
        for entry in schema_entries(oi, cls):
            if entry["kind"] == "link":
                entries.append({"localized_name": entry["name"], "name": entry["name"],
                                "type": entry["type"], "link": None})
            else:
                entries.append({"localized_name": entry["name"], "name": entry["name"],
                                "type": entry["type"],
                                "widget": {"name": entry["name"]}, "link": None})
        node["inputs"] = entries
        node["outputs"] = [
            {"localized_name": out_name, "name": out_name, "type": out_type,
             "slot_index": index, "links": []}
            for index, (out_name, out_type) in enumerate(
                zip(oi[cls].get("output_name") or [], oi[cls].get("output") or []))
        ]
        node["properties"] = {"Node name for S&R": cls}
        node["widgets_values"] = widgets_values
        nodes.append(node)
        id2node[node_id] = node

    # 连线：把 spec 里的 links_in 变成 links 数组 + 两端引用。
    for spec in spec_nodes:
        target_id = int(spec["id"])
        target = id2node[target_id]
        for input_name, (origin_id, origin_slot) in (spec.get("links_in") or {}).items():
            link_id += 1
            origin = id2node[int(origin_id)]
            origin_type = origin["outputs"][int(origin_slot)]["type"]
            target_slot = next((i for i, e in enumerate(target["inputs"])
                                if e["name"] == input_name), None)
            if target_slot is None:
                raise KeyError(f"节点 {target_id}({target['type']}) 没有输入 {input_name}")
            # 类型必须对得上，不然画布上会连出一条红虚线、运行直接报错。
            expected_type = target["inputs"][target_slot].get("type")
            if expected_type and expected_type != origin_type:
                raise TypeError(
                    f"节点 {target_id}({target['type']}).{input_name} 期望 {expected_type}，"
                    f"但来源是 {origin_type}")
            links.append([link_id, int(origin_id), int(origin_slot),
                          target_id, target_slot, origin_type])
            origin["outputs"][int(origin_slot)]["links"].append(link_id)
            target["inputs"][target_slot]["link"] = link_id

    # 拓扑 order：从没有入边的节点开始编号。
    indegree = {node["id"]: 0 for node in nodes}
    children = collections.defaultdict(list)
    for _lid, origin_id, _oslot, target_id, _tslot, _typ in links:
        indegree[target_id] += 1
        children[origin_id].append(target_id)
    queue = collections.deque([nid for nid in indegree if indegree[nid] == 0])
    topo = []
    while queue:
        current = queue.popleft()
        topo.append(current)
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    for order, nid in enumerate(topo):
        id2node[nid]["order"] = order

    workflow = {
        "id": str(uuid.uuid4()),
        "revision": 0,
        "last_node_id": max(node["id"] for node in nodes),
        "last_link_id": link_id,
        "nodes": nodes,
        "links": links,
        "groups": groups,
        "config": {},
        "extra": {"ds": {"scale": 0.75, "offset": [80, 80]},
                  "frontendVersion": "1.59.6"},
        "version": 0.4,
    }
    os.makedirs(UI_DIR, exist_ok=True)
    path = os.path.join(UI_DIR, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(workflow, fh, ensure_ascii=False, indent=2)
    return path, workflow


def ui_to_api(workflow: dict, oi: dict) -> dict:
    """把 UI 工作流反向还原成 API prompt，用于和 examples/ 的 API 版对比。"""
    nodes = {node["id"]: node for node in workflow["nodes"]}
    links = {link[0]: link for link in workflow["links"]}
    prompt = {}
    for node_id, node in nodes.items():
        cls = node["type"]
        if cls in NO_SCHEMA_NODES:
            continue
        values = node.get("widgets_values") or []
        entries_by_name = {entry["name"]: entry for entry in node.get("inputs") or []}
        inputs = {}
        widget_index = 0
        for entry in schema_entries(oi, cls):
            name = entry["name"]
            if entry["kind"] == "link":
                ui_entry = entries_by_name.get(name)
                if ui_entry and ui_entry.get("link") is not None:
                    _lid, origin_id, origin_slot, _tid, _tslot, _typ = links[ui_entry["link"]]
                    inputs[name] = [str(origin_id), int(origin_slot)]
                continue
            ui_entry = entries_by_name.get(name)
            if ui_entry and ui_entry.get("link") is not None:
                _lid, origin_id, origin_slot, _tid, _tslot, _typ = links[ui_entry["link"]]
                inputs[name] = [str(origin_id), int(origin_slot)]
                # 控件被“转成输入”后，widgets_values 里仍然占一个位置，
                # 只是取值来自连线；这里必须跳过该位，否则后面的控件会整体错位。
                widget_index += 1
                continue
            if widget_index < len(values):
                value = values[widget_index]
            else:
                value = None
            widget_index += 1
            # SaveVideo 这种动态组合：format.codec 子控件在 API 里对应顶层 codec。
            if name.endswith(".codec") and name != "codec":
                inputs["codec"] = value
            else:
                inputs[name] = value
        prompt[str(node_id)] = {"class_type": cls, "inputs": inputs}
    return prompt


def compare_with_api(workflow: dict, api_graph: dict, oi: dict, name: str) -> list[str]:
    """逐输入对比 UI 还原出来的 API 和原始 API 示例，返回错误列表。"""
    restored = ui_to_api(workflow, oi)
    errors = []
    for node_id, api_node in api_graph.items():
        if str(node_id) not in restored:
            errors.append(f"[{name}] 缺少节点 {node_id}")
            continue
        restored_inputs = restored[str(node_id)]["inputs"]
        for input_name, expected in api_node.get("inputs", {}).items():
            if input_name not in restored_inputs:
                errors.append(f"[{name}] 节点 {node_id} 缺少输入 {input_name}")
                continue
            actual = restored_inputs[input_name]
            if isinstance(expected, list) and len(expected) == 2 and isinstance(expected[1], int):
                okay = (isinstance(actual, list) and str(actual[0]) == str(expected[0])
                        and int(actual[1]) == int(expected[1]))
            else:
                okay = actual == expected
            if not okay:
                errors.append(f"[{name}] 节点 {node_id}.{input_name}: {actual!r} != {expected!r}")
    return errors


# ------------------------------------------------------------------ 工作流定义
MODELS = dict(
    fl2va="MiniMax\\fastvideo_fasth3_8step_v2_pruned_bf16.safetensors",
    clip="qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors",
    video_vae="minimax_h3_video_vae_int8_convrot.safetensors",
    audio_vae="minimax_h3_audio_vae_fp32.safetensors",
    lora1=("minimax\\pika_h3_flex_ref2va_v1_bf16.safetensors", 1.0),
    lora2=("minimax\\dmad_minimax_h3_8step_full_critic_comfyui.safetensors", 0.5),
    lora3=("minimax\\Motion_Repair运动连续性.safetensors", 0.3),
)
SIGMAS = "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"
SCRIPT = """第1段（5秒）
清晨的湖面，薄雾浮动，一叶小舟缓缓划过，镜头从远处缓慢推进，暖金色晨光。

第2段（5秒）
特写：船夫粗糙的手握住船桨，水珠从桨叶落下，逆光里的水雾，镜头极慢推近。

第3段（5秒）
镜头升到高处俯瞰：小舟驶向湖心，晨雾散开，远山轮廓浮现，画面安静收尾。
"""
VOICE = "directordeck_voice.wav"


def loader_node() -> dict:
    m = MODELS
    return dict(id=1, type="DirectorDeck_ModelLoader", pos=[0, 0], size=[360, 620],
                values={"fl2va_model": m["fl2va"], "text_encoder": m["clip"],
                        "video_vae": m["video_vae"], "audio_vae": m["audio_vae"],
                        "weight_dtype": "default", "vram_tier": "auto",
                        "ref2va_model": "none",
                        "lora_1": m["lora1"][0], "strength_1": m["lora1"][1],
                        "lora_2": m["lora2"][0], "strength_2": m["lora2"][1],
                        "lora_3": m["lora3"][0], "strength_3": m["lora3"][1],
                        "lora_4": "none", "strength_4": 1.0,
                        "shift_video": 12.0, "shift_audio": 3.0},
                title="① 模型加载器（链首唯一）")


def config_node() -> dict:
    return dict(id=2, type="DirectorDeck_DirectorConfig", pos=[0, 660], size=[360, 560],
                values={
                    "width": 640, "height": 352, "segment_seconds": 5.0,
                    "handoff_frames": 22, "sampler_name": "er_sde", "scheduler": "beta",
                    "steps": 10, "denoise": 1.0, "sigmas_string": SIGMAS,
                    "interpolate_to_steps": 10, "seed_strategy": "per_segment",
                    "seed_base": 12345, "preview": True, "vram_policy": "release",
                    "cleanup_segments": "ask", "seam_enabled": True,
                    "seam_window": 12, "seam_max_add": 0.10, "seam_gain_limit": 0.04,
                    "output_dir": "DirectorDeck"},
                title="② 全局配置")


def script_node(node_id=3, pos=(0, 1260)) -> dict:
    return dict(id=node_id, type="DirectorDeck_ScriptDesk", pos=list(pos), size=[360, 260],
                values={"text": SCRIPT, "mode": "auto", "default_seconds": 5.0,
                        "max_segments": 64, "keep_header": False, "regex_pattern": ""},
                title="③ 剧本加载器")


def make_m5_latent(oi):
    """M5.5：两段 latent 尾帧续写（第 2 段 continuity=latent_tail）。"""
    nodes = [
        loader_node(), config_node(), script_node(),
        take_node(10, (420, 0), 1, "provided", "start", assets_policy="clear",
                  title="第 1 段（head=0）"),
        dict(id=11, type="DirectorDeck_DirectorTake", pos=[840, 0], size=[380, 460],
             values={"segment_index": 2, "bundle_policy": "inherit",
                     "config_policy": "inherit", "assets_policy": "inherit",
                     "brief_policy": "inherit", "cast_policy": "inherit",
                     "continuity": "latent_tail", "seed": 0},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "previous_segment": (10, 0)},
             title="第 2 段（latent 尾 token 续写）"),
        dict(id=20, type="DirectorDeck_FinalCut", pos=[1260, 0], size=[420, 460],
             values={"save_manifest": True, "audio_from_source": False},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2),
                       "segment_2": (11, 0), "images_2": (11, 1), "audio_2": (11, 2)},
             title="合并（自动裁衔接头）"),
        dict(id=21, type="CreateVideo", pos=[1700, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (20, 0), "audio": (20, 1)}),
        dict(id=22, type="SaveVideo", pos=[1700, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M5_latent_chain",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (21, 0)}),
        dict(id=30, type="Note", pos=[420, 520], size=[620, 260],
             text="【M5.5 latent 尾帧续写】\n"
                  "第 2 段的 continuity 选 latent_tail：生成器直接把上一段 latent 的尾部 token\n"
                  "搬进新 latent 开头并设 noise_mask=0，省掉 RGB 解码/编码的绕路。\n"
                  "实测同规格段比 RGB 引导快约 1/3（17.1s/it vs 25.5s/it），边界亮度差 0.0038。\n"
                  "想要最高画质稳定可继续用 guide_tail；想快/想更贴原生续写用 latent_tail。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-20, -20, 400, 1480],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "两段（latent 续写）", "bounding": [400, -20, 820, 520],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "合并 / 输出", "bounding": [1240, -20, 840, 500],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M5_latent续写")


def make_m6_mix(oi):
    """M6：多角色锁音 + 自动 ducking（两路音频按优先级混音）。"""
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=5, type="LoadAudio", pos=[420, 0], size=[340, 90],
             values={"audio": "mix_a.wav"}, title="角色 A（440Hz，0~2.5s）"),
        dict(id=6, type="LoadAudio", pos=[420, 120], size=[340, 90],
             values={"audio": "mix_b.wav"}, title="角色 B（880Hz，2.0~5.17s）"),
        dict(id=7, type="DirectorDeck_VoiceLock", pos=[420, 250], size=[360, 380],
             values={"roles": "A: 1, 0.0, 0, 2\nB: 2, 0.0, 0, 1",
                     "lock_audio": True, "mix_mode": "priority",
                     "duck_db": -8.0, "attack_ms": 40, "release_ms": 200},
             links_in={"audio_1": (5, 0), "audio_2": (6, 0)},
             title="锁音 + 混音（A 优先级 2，B 优先级 1）"),
        dict(id=10, type="DirectorDeck_DirectorTake", pos=[840, 0], size=[380, 520],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "clear",
                     "brief_policy": "inherit", "cast_policy": "replace",
                     "continuity": "start", "seed": 0, "cache_mode": "auto"},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "cast": (7, 0)}),
        dict(id=40, type="DirectorDeck_FinalCut", pos=[1260, 0], size=[420, 460],
             values={"save_manifest": True, "audio_from_source": True},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2)},
             title="合并（直接混源音轨）"),
        dict(id=41, type="CreateVideo", pos=[1700, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (40, 0), "audio": (40, 1)}),
        dict(id=42, type="SaveVideo", pos=[1700, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M6_mix_rules",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (41, 0)}),
        dict(id=43, type="SaveAudio", pos=[1700, 480], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M6_mix_source"},
             links_in={"audio": (40, 1)}, title="混音后的源音轨（可逐样点分析）"),
        dict(id=50, type="Note", pos=[840, 560], size=[640, 260],
             text="【M6 多角色锁音 ducking】\n"
                  "两个角色同时说话时，priority 模式让优先级高的 A 保持原样，\n"
                  "B 在重叠区被压低 duck_db（默认 -8dB），attack/release 平滑避免爆音。\n"
                  "混音规则直接在锁音器上选：auto_duck / priority / sum；\n"
                  "每路还可以单独设增益（角色行第 3 参数）和优先级（第 4 参数）。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-20, -20, 400, 1480],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "多角色锁音与混音", "bounding": [400, -20, 420, 660],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "生成 / 输出", "bounding": [820, -20, 1260, 580],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M6_多角色混音")


def make_m8_tts(oi):
    """M8：本地 Breeze-TTS-2 两路发声 -> 锁音 -> H3。"""
    voice_a = dict(
        id=5, type="BreezeTTS2VoiceDesign", pos=[420, 0], size=[380, 520],
        values={"text": "你好，我是这部剧的女主角。",
                "instruction": "一位年轻女性，声音清澈温柔，语速偏慢，情绪平静。",
                "cfg_scale": 4.0, "max_new_tokens": 1500, "temperature": 0.9,
                "top_k": 50, "top_p": 1.0, "repetition_penalty": 1.1,
                "depth_temperature": 0.9, "depth_top_k": 50, "depth_top_p": 1.0,
                "seed": 1111},
        links_in={"breeze_model": (4, 0)}, title="女主（VoiceDesign，seed=1111）")
    voice_b = dict(
        id=6, type="BreezeTTS2VoiceDesign", pos=[420, 560], size=[380, 520],
        values={"text": "收到，我去检查船桨，五分钟以后开拍。",
                "instruction": "一位年轻男性，声音低沉沉稳，语速正常，语气干练。",
                "cfg_scale": 4.0, "max_new_tokens": 1500, "temperature": 0.9,
                "top_k": 50, "top_p": 1.0, "repetition_penalty": 1.1,
                "depth_temperature": 0.9, "depth_top_k": 50, "depth_top_p": 1.0,
                "seed": 2222},
        links_in={"breeze_model": (4, 0)}, title="男主（VoiceDesign，seed=2222）")
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=4, type="BreezeTTS2LoadModel", pos=[-20, 1120], size=[400, 260],
             values={"model": "int8 hybrid (recommended)", "dtype": "auto",
                     "device": "auto", "attention": "auto",
                     "decode_mode": "eager", "download_if_missing": False},
             title="Breeze TTS 2（int8 hybrid）"),
        voice_a, voice_b,
        dict(id=7, type="DirectorDeck_VoiceLock", pos=[840, 120], size=[360, 380],
             values={"roles": "女主: 1, 0.0, 0, 2\n男主: 2, 1.2, 0, 1",
                     "lock_audio": True, "mix_mode": "priority",
                     "duck_db": -8.0, "attack_ms": 60, "release_ms": 200},
             links_in={"audio_1": (5, 0), "audio_2": (6, 0)},
             title="锁音（女主 0s / 男主 1.2s）"),
        dict(id=10, type="DirectorDeck_DirectorTake", pos=[1260, 0], size=[380, 520],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "clear",
                     "brief_policy": "inherit", "cast_policy": "replace",
                     "continuity": "start", "seed": 0, "cache_mode": "auto"},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "cast": (7, 0)}),
        dict(id=40, type="DirectorDeck_FinalCut", pos=[1680, 0], size=[420, 460],
             values={"save_manifest": True, "audio_from_source": True,
                     "audio_crossfade_ms": 0},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2)},
             title="合并（直接混源音轨）"),
        dict(id=41, type="CreateVideo", pos=[2120, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (40, 0), "audio": (40, 1)}),
        dict(id=42, type="SaveVideo", pos=[2120, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M8_tts_lock",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (41, 0)}),
        dict(id=43, type="SaveAudio", pos=[2120, 480], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M8_tts_mix"},
             links_in={"audio": (40, 1)}),
        dict(id=44, type="SaveAudio", pos=[2120, 620], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M8_tts_a"},
             links_in={"audio": (5, 0)}),
        dict(id=45, type="SaveAudio", pos=[2120, 760], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M8_tts_b"},
             links_in={"audio": (6, 0)}),
        dict(id=50, type="Note", pos=[840, 560], size=[680, 300],
             text="【M8 本地 TTS -> 锁音】\n"
                  "Breeze-TTS-2 的两个 VoiceDesign 各出一路 AUDIO（24kHz 单声道），\n"
                  "接进锁音器 audio_1/audio_2；角色行写“女主: 1, 0.0 / 男主: 2, 1.2”\n"
                  "即可按时间轴摆放并做 priority ducking。\n"
                  "TTS 输出会被自动重采样到音频 VAE 的 32kHz；固定 seed 才能复现/命中缓存。\n"
                  "没装 ComfyUI-Breeze-TTS-2 时这组节点会消失，可改用 LoadAudio 接自己的配音。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-60, -20, 460, 1420],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "本地 TTS（Breeze-TTS-2）", "bounding": [400, -20, 420, 1160],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "锁音 / 生成 / 输出", "bounding": [820, -20, 1700, 900],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M8_TTS锁音")


def make_m9_booth(oi):
    """M9：一张台词表 -> 多角色 TTS -> CAST -> 锁音（一键批处理）。"""
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=4, type="BreezeTTS2LoadModel", pos=[-20, 1120], size=[400, 260],
             values={"model": "int8 hybrid (recommended)", "dtype": "auto",
                     "device": "auto", "attention": "auto",
                     "decode_mode": "eager", "download_if_missing": False},
             title="Breeze TTS 2（int8 hybrid）"),
        dict(id=5, type="DirectorDeck_TTSBooth", pos=[420, 0], size=[440, 820],
             values={"lines": "女主 @0.0 | 一位年轻女性，声音清澈温柔，语速偏慢，情绪平静。 | 你好，我是这部剧的女主角。\n"
                             "男主 @1.2 | 一位年轻男性，声音低沉沉稳，语气干练。 | 收到，我去检查船桨，五分钟以后开拍。",
                     "auto_start": True, "auto_split": True,
                     "pause_ms": 300, "chars_per_second": 4.5, "max_seconds": 0.0,
                     "mix_mode": "priority", "duck_db": -8.0,
                     "attack_ms": 60, "release_ms": 200,
                     "cfg_scale": 4.0, "max_new_tokens": 1500,
                     "temperature": 0.9, "top_k": 50, "top_p": 1.0,
                     "repetition_penalty": 1.1, "depth_temperature": 0.9,
                     "depth_top_k": 50, "depth_top_p": 1.0,
                     "seed": 20261128},
             links_in={"breeze_model": (4, 0)},
             title="TTS 台词表（一行一条：角色 [@起始秒] | 音色描述 | 台词）"),
        dict(id=10, type="DirectorDeck_DirectorTake", pos=[920, 0], size=[380, 520],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "clear",
                     "brief_policy": "inherit", "cast_policy": "replace",
                     "continuity": "start", "seed": 0, "cache_mode": "auto"},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "cast": (5, 0)}),
        dict(id=40, type="DirectorDeck_FinalCut", pos=[1340, 0], size=[420, 460],
             values={"save_manifest": True, "audio_from_source": True,
                     "audio_crossfade_ms": 0},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2)}),
        dict(id=41, type="CreateVideo", pos=[1780, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (40, 0), "audio": (40, 1)}),
        dict(id=42, type="SaveVideo", pos=[1780, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M9_booth",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (41, 0)}),
        dict(id=43, type="SaveAudio", pos=[1780, 480], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M9_booth_mix"},
             links_in={"audio": (40, 1)}),
        dict(id=44, type="SaveAudio", pos=[1780, 620], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M9_booth_a"},
             links_in={"audio": (5, 1)}),
        dict(id=45, type="SaveAudio", pos=[1780, 760], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M9_booth_b"},
             links_in={"audio": (5, 2)}),
        dict(id=50, type="Note", pos=[920, 560], size=[680, 300],
             text="【M9 台词表一键配音】\n"
                  "只写一张台词表：“角色 @起始秒 | 音色描述 | 台词”，每行一条。\n"
                  "TTS 台词表节点会自动逐条调 Breeze-TTS-2 生成，并按角色拼成音轨，\n"
                  "直接输出 CAST 给视频生成器锁音（不用手摆多个 TTS 节点）。\n"
                  "角色第一次出现的顺序 = ducking 优先级；固定 seed 可复现/命中缓存。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-60, -20, 460, 1420],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "台词表 -> 多角色 TTS", "bounding": [400, -20, 480, 900],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "锁音 / 生成 / 输出", "bounding": [900, -20, 1300, 900],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M9_台词表配音")


def make_m10_auto(oi):
    """M10：台词表自动排期（不写起始秒，按句估时长/分段）。"""
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=4, type="BreezeTTS2LoadModel", pos=[-20, 1120], size=[400, 260],
             values={"model": "int8 hybrid (recommended)", "dtype": "auto",
                     "device": "auto", "attention": "auto",
                     "decode_mode": "eager", "download_if_missing": False},
             title="Breeze TTS 2（int8 hybrid）"),
        dict(id=5, type="DirectorDeck_TTSBooth", pos=[420, 0], size=[440, 820],
             values={"lines": "女主 | 一位年轻女性，声音清澈温柔，语速偏慢，情绪平静。 | 你好。我是女主角。\n"
                             "男主 | 一位年轻男性，声音低沉沉稳，语气干练。 | 收到，我去检查船桨。",
                     "auto_start": True, "auto_split": True,
                     "pause_ms": 250, "chars_per_second": 4.5, "max_seconds": 0.0,
                     "mix_mode": "priority", "duck_db": -8.0,
                     "attack_ms": 60, "release_ms": 200,
                     "cfg_scale": 4.0, "max_new_tokens": 1500,
                     "temperature": 0.9, "top_k": 50, "top_p": 1.0,
                     "repetition_penalty": 1.1, "depth_temperature": 0.9,
                     "depth_top_k": 50, "depth_top_p": 1.0,
                     "seed": 20261129},
             links_in={"breeze_model": (4, 0)},
             title="台词表（不写 @秒：按句自动分段 + 自动排期）"),
        dict(id=10, type="DirectorDeck_DirectorTake", pos=[920, 0], size=[380, 520],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "clear",
                     "brief_policy": "inherit", "cast_policy": "replace",
                     "continuity": "start", "seed": 0, "cache_mode": "auto"},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "cast": (5, 0)}),
        dict(id=40, type="DirectorDeck_FinalCut", pos=[1340, 0], size=[420, 460],
             values={"save_manifest": True, "audio_from_source": True,
                     "audio_crossfade_ms": 0},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2)}),
        dict(id=41, type="CreateVideo", pos=[1780, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (40, 0), "audio": (40, 1)}),
        dict(id=42, type="SaveVideo", pos=[1780, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M10_auto",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (41, 0)}),
        dict(id=43, type="SaveAudio", pos=[1780, 480], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M10_auto_mix"},
             links_in={"audio": (40, 1)}),
        dict(id=44, type="SaveAudio", pos=[1780, 620], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M10_auto_a"},
             links_in={"audio": (5, 1)}),
        dict(id=45, type="SaveAudio", pos=[1780, 760], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M10_auto_b"},
             links_in={"audio": (5, 2)}),
        dict(id=50, type="Note", pos=[920, 560], size=[680, 260],
             text="【M10 台词自动排期】\n"
                  "台词表不写 @起始秒，节点会：按句号/问号/感叹号自动分段（auto_split），\n"
                  "生成后以真实音频长度按“上一句结束 + pause_ms”自动往后排（auto_start）。\n"
                  "写 @秒 的句子仍按写死的来，后面的自动句子接着它继续排。\n"
                  "节点还会输出 total_seconds，可用来回填全局配置的段时长。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-60, -20, 460, 1420],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "台词表（自动分段 + 自动排期）", "bounding": [400, -20, 480, 960],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "锁音 / 生成 / 输出", "bounding": [900, -20, 1300, 900],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M10_台词自动排期")


def make_m11_chain(oi):
    """M11：台词超长 -> 提醒 + 两段自动衔接（同一份 cast 复用）。"""
    lines = ("女主 | 一位年轻女性，声音清澈温柔，语速偏慢，情绪平静。 | 你好，我是女主角。今天拍湖上的戏。\n"
             "男主 | 一位年轻男性，声音低沉沉稳，语气干练。 | 收到，我去检查船桨。五分钟以后开拍。")
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=4, type="BreezeTTS2LoadModel", pos=[-20, 1120], size=[400, 260],
             values={"model": "int8 hybrid (recommended)", "dtype": "auto",
                     "device": "auto", "attention": "auto",
                     "decode_mode": "eager", "download_if_missing": False},
             title="Breeze TTS 2（int8 hybrid）"),
        dict(id=5, type="DirectorDeck_TTSBooth", pos=[420, 0], size=[440, 860],
             values={"lines": lines,
                     "auto_start": True, "auto_split": True,
                     "pause_ms": 250, "chars_per_second": 4.5, "max_seconds": 5.0,
                     "mix_mode": "priority", "duck_db": -8.0,
                     "attack_ms": 60, "release_ms": 200,
                     "cfg_scale": 4.0, "max_new_tokens": 1500,
                     "temperature": 0.9, "top_k": 50, "top_p": 1.0,
                     "repetition_penalty": 1.1, "depth_temperature": 0.9,
                     "depth_top_k": 50, "depth_top_p": 1.0,
                     "seed": 20261130},
             links_in={"breeze_model": (4, 0)},
             title="台词表（超长只提醒不缩句；输出分段计划）"),
        dict(id=10, type="DirectorDeck_DirectorTake", pos=[920, 0], size=[380, 520],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "clear",
                     "brief_policy": "inherit", "cast_policy": "replace",
                     "continuity": "start", "seed": 0, "cache_mode": "auto"},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "cast": (5, 0)}),
        dict(id=11, type="DirectorDeck_DirectorTake", pos=[920, 560], size=[380, 540],
             values={"segment_index": 2, "bundle_policy": "inherit",
                     "config_policy": "inherit", "assets_policy": "inherit",
                     "brief_policy": "inherit", "cast_policy": "inherit",
                     "continuity": "latent_tail", "seed": 0, "cache_mode": "auto"},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "previous_segment": (10, 0)}),
        dict(id=40, type="DirectorDeck_FinalCut", pos=[1340, 0], size=[420, 620],
             values={"save_manifest": True, "audio_from_source": True,
                     "audio_crossfade_ms": 0},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2),
                       "segment_2": (11, 0), "images_2": (11, 1),
                       "audio_2": (11, 2)}, title="合并两段（源音轨，天然连续）"),
        dict(id=41, type="CreateVideo", pos=[1780, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (40, 0), "audio": (40, 1)}),
        dict(id=42, type="SaveVideo", pos=[1780, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M11_chain",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (41, 0)}),
        dict(id=43, type="SaveAudio", pos=[1780, 480], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M11_chain_mix"},
             links_in={"audio": (40, 1)}),
        dict(id=44, type="SaveAudio", pos=[1780, 620], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M11_chain_a"},
             links_in={"audio": (5, 1)}),
        dict(id=45, type="SaveAudio", pos=[1780, 760], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M11_chain_b"},
             links_in={"audio": (5, 2)}),
        dict(id=50, type="Note", pos=[920, 1140], size=[760, 300],
             text="【M11 超长提醒 + 多段衔接】\n"
                  "自动排期总长超过 max_seconds 时，节点只提醒并输出分段计划（segment_count/plan），\n"
                  "不会缩句、不会加速、不会裁台词。\n"
                  "多段衔接：第 1 段 cast_policy=replace；第 2 段 cast_policy=inherit +\n"
                  "previous_segment + continuity=latent_tail。TTSBooth 的 cast 音轨是整条时间轴的，\n"
                  "每段生成器会按自己的时间窗口自动切片，所以声音天然连续。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-60, -20, 460, 1420],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "台词表（超长提醒 + 分段计划）", "bounding": [400, -20, 480, 1000],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "两段衔接 / 生成 / 输出", "bounding": [900, -20, 1300, 1480],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M11_超长两段衔接")


def make_m12_scriptsmith(oi):
    """M12：Skill + 小说 -> 编剧台 -> 剧本/TTS -> 锁音生成。"""
    novel = ("雨夜，林澈撑着伞回到老宅门口。门内走出一个男人，是十年前失踪的哥哥。"
             "哥哥只说了一句：你终于回来了。")
    nodes = [
        loader_node(), config_node(),
        dict(id=6, type="LoadImage", pos=[-20, 1120], size=[320, 340],
             values={"image": "11.png"}, title="参考图 1"),
        dict(id=7, type="LoadImage", pos=[320, 1120], size=[320, 340],
             values={"image": "睡衣.png"}, title="参考图 2"),
        dict(id=8, type="DirectorDeck_AssetShelf", pos=[-20, 1480], size=[640, 300],
             links_in={"image_1": (6, 0), "image_2": (7, 0)},
             title="素材库（2 张参考图）"),
        dict(id=3, type="DirectorDeck_ScriptSmith", pos=[420, 0], size=[460, 900],
             values={"skill": "directordeck_screenwriter", "skill_path": "",
                     "novel": novel, "language": "中文",
                     "output_format": "DirectorDeck 剧本",
                     "segment_seconds": 5.0, "max_segments": 1,
                     "provider": "本地 OpenAI 兼容 (LM Studio/Ollama)",
                     "base_url": "http://127.0.0.1:18081/v1",
                     "model": "mock-screenwriter",
                     "api_key_env": "OPENAI_API_KEY",
                     "temperature": 0.7, "max_tokens": 4096, "timeout": 180,
                     "include_refs": False, "max_context_chars": 60000},
             links_in={"assets": (8, 0)},
             title="编剧台（加载 skill，按素材库对齐角色）"),
        dict(id=4, type="BreezeTTS2LoadModel", pos=[420, 940], size=[400, 240],
             values={"model": "int8 hybrid (recommended)", "dtype": "auto",
                     "device": "auto", "attention": "auto",
                     "decode_mode": "eager", "download_if_missing": False},
             title="Breeze TTS 2"),
        dict(id=5, type="DirectorDeck_TTSBooth", pos=[880, 0], size=[440, 860],
             values={"auto_start": True, "auto_split": True,
                     "pause_ms": 300, "chars_per_second": 4.5, "max_seconds": 0.0,
                     "mix_mode": "priority", "duck_db": -8.0,
                     "attack_ms": 60, "release_ms": 200,
                     "cfg_scale": 4.0, "max_new_tokens": 1500,
                     "temperature": 0.9, "top_k": 50, "top_p": 1.0,
                     "repetition_penalty": 1.1, "depth_temperature": 0.9,
                     "depth_top_k": 50, "depth_top_p": 1.0,
                     "seed": 20261201},
             links_in={"breeze_model": (4, 0), "lines": (3, 2)},
             title="TTS 台词表（lines 来自编剧台）"),
        dict(id=10, type="DirectorDeck_DirectorTake", pos=[1360, 0], size=[380, 520],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "replace",
                     "brief_policy": "inherit", "cast_policy": "replace",
                     "continuity": "start", "seed": 0, "cache_mode": "auto"},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "assets": (8, 0), "cast": (5, 0)}),
        dict(id=40, type="DirectorDeck_FinalCut", pos=[1780, 0], size=[420, 460],
             values={"save_manifest": True, "audio_from_source": True,
                     "audio_crossfade_ms": 0},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2)}),
        dict(id=41, type="CreateVideo", pos=[2220, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (40, 0), "audio": (40, 1)}),
        dict(id=42, type="SaveVideo", pos=[2220, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M12_scriptsmith",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (41, 0)}),
        dict(id=43, type="SaveAudio", pos=[2220, 480], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M12_scriptsmith_mix"},
             links_in={"audio": (40, 1)}),
        dict(id=50, type="Note", pos=[880, 940], size=[760, 320],
             text="【M12 编剧台】\n"
                  "skill + 小说 -> 本地/远程 LLM -> 分段剧本。\n"
                  "script 接视频生成器；voice_lines 接 TTS 台词表；assets/cast 用来对齐角色和音色。\n"
                  "示例默认连 tools/mock_llm.py（127.0.0.1:18081）方便没有真实模型时联调；\n"
                  "换成 LM Studio/Ollama 或远程 API 只需改 base_url/model（Key 放环境变量）。"),
    ]
    groups = [
        {"title": "素材 / 模型 / 配置", "bounding": [-60, -20, 700, 1820],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "编剧台（Skill 小说转剧本）", "bounding": [400, -20, 500, 940],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "TTS / 锁音 / 生成 / 输出", "bounding": [860, -20, 1760, 1000],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M12_编剧台")


def make_m1(oi):
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=4, type="DirectorDeck_DirectorTake", pos=[420, 0], size=[380, 420],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "clear",
                     "brief_policy": "inherit", "cast_policy": "inherit",
                     "continuity": "start", "seed": 0},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0)},
             title="④ 视频生成器（第 1 段）"),
        dict(id=5, type="CreateVideo", pos=[860, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (4, 1), "audio": (4, 2)}),
        dict(id=6, type="SaveVideo", pos=[860, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M1_single",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (5, 0)}, title="成片保存到 output/DirectorDeck/"),
        dict(id=7, type="Note", pos=[420, 520], size=[560, 260],
             text="【M1 单段闭环】\n"
                  "直接运行即可：模型加载器 + 全局配置 + 剧本加载器 + 视频生成器。\n"
                  "想单独改这一段：接一个「段级剧本」，把 brief_policy 切成 replace；\n"
                  "想用参考图：接「资产管理器」，提示词写 @图片1 / @图片2；\n"
                  "所有 policy 必须显式选，没选会报 DD-E001（这是故意的，防止悄悄继承）。\n"
                  "时长：生成器按剧本段落秒数自动吸附到 17k+5 帧。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-20, -20, 400, 1480],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "生成", "bounding": [400, -20, 440, 500],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "输出", "bounding": [840, -20, 400, 480],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M1_单段闭环")


def make_m1_ref(oi):
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=7, type="LoadImage", pos=[420, 0], size=[300, 330],
             values={"image": "11.png"}, title="参考图 1（槽 1）"),
        dict(id=8, type="LoadImage", pos=[420, 360], size=[300, 330],
             values={"image": "睡衣.png"}, title="参考图 2（槽 2）"),
        dict(id=9, type="DirectorDeck_AssetShelf", pos=[760, 0], size=[340, 360],
             links_in={"image_1": (7, 0), "image_2": (8, 0)},
             title="资产管理器（@图片N 按槽引用）"),
        dict(id=10, type="DirectorDeck_SegmentBrief", pos=[760, 400], size=[340, 300],
             values={"text": "@图片1 的女孩穿着 @图片2 的衣服在海边散步，电影感缓慢推镜。",
                     "seconds": 5.0, "dialogue": "", "refs": "1,2"},
             title="段级剧本（覆盖第 1 段）"),
        dict(id=4, type="DirectorDeck_DirectorTake", pos=[1180, 0], size=[380, 460],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "replace",
                     "brief_policy": "replace", "cast_policy": "inherit",
                     "continuity": "start", "seed": 0},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "assets": (9, 0), "brief": (10, 0)},
             title="视频生成器（参考生视频）"),
        dict(id=5, type="CreateVideo", pos=[1620, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (4, 1), "audio": (4, 2)}),
        dict(id=6, type="SaveVideo", pos=[1620, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M1_ref2va",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (5, 0)}),
        dict(id=11, type="Note", pos=[1180, 520], size=[560, 240],
             text="【M1 参考生视频】\n"
                  "两张参考图进 AssetShelf 的槽 1/2；提示词里 @图片1 / @图片2 会被换成 <Picture N>。\n"
                  "段级剧本覆盖了原剧本第 1 段（brief_policy=replace）。\n"
                  "资产/剧本覆盖=把 policy 显式选成 replace，不接线或选 inherit 就用上一段/脚本。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-20, -20, 400, 1480],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "素材与覆盖", "bounding": [400, -20, 740, 480],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "生成 / 输出", "bounding": [1160, -20, 820, 500],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M1_参考生视频")


def take_node(node_id, pos, segment_index, bundle_policy, continuity,
              assets_policy="inherit", links=None, title=None):
    values = {"segment_index": segment_index, "bundle_policy": bundle_policy,
              "config_policy": "inherit", "assets_policy": assets_policy,
              "brief_policy": "inherit", "cast_policy": "inherit",
              "continuity": continuity, "seed": 0}
    links_in = {"bundle": (1, 0), "config": (2, 0), "script": (3, 0)}
    if links:
        links_in.update(links)
    return dict(id=node_id, type="DirectorDeck_DirectorTake", pos=list(pos),
                size=[380, 460], values=values, links_in=links_in, title=title)


def make_m2(oi):
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=4, type="DirectorDeck_FramePlanner", pos=[420, 0], size=[360, 260],
             values={"keep_full": True}, links_in={"script": (3, 0), "config": (2, 0)},
             title="帧计划器（整条链的帧数/衔接）"),
        take_node(10, (820, 0), 1, "provided", "start", assets_policy="clear",
                  title="第 1 段（head=0）"),
        take_node(11, (1240, 0), 2, "inherit", "guide_tail",
                  links={"previous_segment": (10, 0)},
                  title="第 2 段（接上一段尾巴）"),
        take_node(12, (1660, 0), 3, "inherit", "guide_tail",
                  links={"previous_segment": (11, 0)},
                  title="第 3 段（继续接）"),
        dict(id=20, type="DirectorDeck_FinalCut", pos=[2080, 0], size=[420, 500],
             values={"save_manifest": True, "audio_from_source": False},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2),
                       "segment_2": (11, 0), "images_2": (11, 1), "audio_2": (11, 2),
                       "segment_3": (12, 0), "images_3": (12, 1), "audio_3": (12, 2)},
             title="合并（自动裁衔接头）"),
        dict(id=21, type="CreateVideo", pos=[2520, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (20, 0), "audio": (20, 1)}),
        dict(id=22, type="SaveVideo", pos=[2520, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M2_chain",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (21, 0)}),
        dict(id=30, type="Note", pos=[820, 540], size=[620, 300],
             text="【M2 三段链】\n"
                  "第 1 段 normal 生成；第 2/3 段接 previous_segment，continuity=guide_tail：\n"
                  "生成器自动取上一段尾帧+尾音做 AddGuide，并做接缝曝光修正。\n"
                  "抽卡：把某段 seed 改掉重跑即可；没改的段会被 ComfyUI 缓存复用。\n"
                  "合并：FinalCut 自动裁掉每段开头的衔接头，再拼画面/音轨并写 manifest。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-20, -20, 400, 1480],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "三段生成（链式续写）", "bounding": [400, -20, 1640, 520],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "合并 / 输出", "bounding": [2060, -20, 840, 500],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M2_三段链")


def make_m3(oi):
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=5, type="LoadAudio", pos=[420, 0], size=[340, 90],
             values={"audio": VOICE}, title="台词音频（数字人）"),
        dict(id=6, type="DirectorDeck_VoiceLock", pos=[420, 130], size=[340, 300],
             values={"roles": "女主: 1, 0.0", "lock_audio": True},
             links_in={"audio_1": (5, 0)},
             title="锁音器（角色: 音频槽, 起始秒）"),
        dict(id=10, type="DirectorDeck_DirectorTake", pos=[800, 0], size=[380, 520],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "clear",
                     "brief_policy": "inherit", "cast_policy": "replace",
                     "continuity": "start", "seed": 0},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "cast": (6, 0)},
             title="一采（锁音：noise_mask=0）"),
        dict(id=20, type="DirectorDeck_Refiner", pos=[1220, 0], size=[360, 420],
             values={"mode": "latent_2nd", "denoise": 0.2, "steps": 4,
                     "sampler_name": "er_sde", "scheduler": "beta", "upscale": 2.0},
             links_in={"bundle": (1, 0), "segment": (10, 0),
                       "images": (10, 1), "audio": (10, 2)},
             title="二采（低 denoise 再采样，锁音）"),
        dict(id=21, type="CreateVideo", pos=[1660, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (10, 1), "audio": (10, 2)}),
        dict(id=22, type="SaveVideo", pos=[1660, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M3_lock_raw",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (21, 0)}, title="一采原片"),
        dict(id=31, type="CreateVideo", pos=[1660, 480], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (20, 1), "audio": (20, 2)}),
        dict(id=32, type="SaveVideo", pos=[1660, 720], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M3_lock_refined",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (31, 0)}, title="二采成片"),
        dict(id=30, type="Note", pos=[800, 560], size=[620, 320],
             text="【M3 数字人锁音 + 二采】\n"
                  "锁音器把 角色 -> 音频槽 -> 时间轴起点 映射好；生成器按时间轴切音轨，\n"
                  "编码进 AV latent 并设 noise_mask=0（音频不被采样器改）。\n"
                  "二采：把成片帧重新编码回 latent，低 denoise 4 步再修一遍，音频继续锁死。\n"
                  "注意：锁音保内容/口型；要成片音频逐样点无损，用 M4 的 audio_from_source。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-20, -20, 400, 1480],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "锁音与生成", "bounding": [400, -20, 760, 600],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "二采 / 输出", "bounding": [1200, -20, 840, 980],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M3_数字人锁音")


def make_m4(oi):
    nodes = [
        loader_node(), config_node(), script_node(),
        dict(id=5, type="LoadAudio", pos=[420, 0], size=[340, 90],
             values={"audio": VOICE}),
        dict(id=6, type="DirectorDeck_VoiceLock", pos=[420, 130], size=[340, 300],
             values={"roles": "女主: 1, 0.0", "lock_audio": True},
             links_in={"audio_1": (5, 0)}),
        dict(id=10, type="DirectorDeck_DirectorTake", pos=[800, 0], size=[380, 520],
             values={"segment_index": 1, "bundle_policy": "provided",
                     "config_policy": "inherit", "assets_policy": "clear",
                     "brief_policy": "inherit", "cast_policy": "replace",
                     "continuity": "start", "seed": 0},
             links_in={"bundle": (1, 0), "config": (2, 0), "script": (3, 0),
                       "cast": (6, 0)}),
        dict(id=40, type="DirectorDeck_FinalCut", pos=[1220, 0], size=[420, 460],
             values={"save_manifest": True, "audio_from_source": True},
             links_in={"segment_1": (10, 0), "images_1": (10, 1), "audio_1": (10, 2)},
             title="合并（音频直接用源轨，无损）"),
        dict(id=41, type="CreateVideo", pos=[1660, 0], size=[320, 200],
             values={"fps": 24.0, "bit_depth": 8, "color_space": "sRGB",
                     "chroma_subsampling": "auto", "codec": "h264"},
             links_in={"images": (40, 0), "audio": (40, 1)}),
        dict(id=42, type="SaveVideo", pos=[1660, 240], size=[360, 200],
             values={"filename_prefix": "DirectorDeck/M4_lock_source_audio",
                     "format": "auto", "format.codec": "auto", "codec": "auto"},
             links_in={"video": (41, 0)}),
        dict(id=43, type="SaveAudio", pos=[1660, 480], size=[360, 110],
             values={"filename_prefix": "DirectorDeck/M4_lock_source"},
             links_in={"audio": (40, 1)}, title="源音频（与源文件逐样点一致）"),
        dict(id=50, type="Note", pos=[800, 560], size=[620, 260],
             text="【M4 锁音无损成片】\n"
                  "和 M3 的差别只有 FinalCut 的 audio_from_source=true：\n"
                  "合并时直接使用当初锁进 latent 的源音轨，绕过音频 VAE 的相位重建，\n"
                  "成片音频与源 wav 逐样点一致（实测 FLAC 相关 1.0 / 最大差 0.0）。"),
    ]
    groups = [
        {"title": "模型 / 配置 / 剧本", "bounding": [-20, -20, 400, 1480],
         "color": "#3f789e", "font_size": 22, "flags": {}},
        {"title": "锁音与生成", "bounding": [400, -20, 760, 600],
         "color": "#8A8", "font_size": 22, "flags": {}},
        {"title": "无损合并 / 输出", "bounding": [1200, -20, 840, 640],
         "color": "#b58b2a", "font_size": 22, "flags": {}},
    ]
    return build_ui(oi, nodes, groups, "DirectorDeck_M4_锁音无损")


WORKFLOWS = [
    ("m1_single_segment_api", make_m1),
    ("m1_ref2va_api", make_m1_ref),
    ("m2_chain_api", make_m2),
    ("m3_digital_human_api", make_m3),
    ("m4_lock_finalcut_api", make_m4),
    ("m5_latent_chain_api", make_m5_latent),
    ("m6_mix_rules_api", make_m6_mix),
    ("m8_tts_lock_api", make_m8_tts),
    ("m9_tts_booth_api", make_m9_booth),
    ("m10_tts_auto_api", make_m10_auto),
    ("m11_tts_chain_api", make_m11_chain),
    ("m12_scriptsmith_api", make_m12_scriptsmith),
]


def main() -> int:
    server = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8189"
    oi = fetch_object_info(server)
    missing = [cls for _n, cls in [
        ("ModelLoader", "DirectorDeck_ModelLoader"),
        ("DirectorConfig", "DirectorDeck_DirectorConfig"),
        ("ScriptDesk", "DirectorDeck_ScriptDesk"),
        ("DirectorTake", "DirectorDeck_DirectorTake"),
    ] if cls not in oi]
    if missing:
        print("object_info 里缺少节点：", missing, "（先启动挂载了 DirectorDeck 的 ComfyUI）")
        return 1

    total_errors = 0
    for api_name, builder in WORKFLOWS:
        path, workflow = builder(oi)
        api_path = os.path.join(API_DIR, api_name + ".json")
        with open(api_path, "r", encoding="utf-8") as fh:
            api_graph = json.load(fh)
        errors = compare_with_api(workflow, api_graph, oi, api_name)
        total_errors += len(errors)
        status = "PASS" if not errors else f"FAIL({len(errors)})"
        print(f"[{status}] {os.path.basename(path)}  <-  {api_name}")
        for error in errors[:8]:
            print("    " + error)
    print("=== 全部通过 ===" if total_errors == 0 else f"=== 共 {total_errors} 处不一致 ===")
    return 0 if total_errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
