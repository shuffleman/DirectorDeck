"""分段覆盖 / 继承解析（纯函数，能在 ComfyUI 外单测）。

这是整个节点库最“绕”但也最重要的逻辑：一段到底用谁的素材、谁的音色、谁的剧本、谁的配置？
我们的规则一句话：**每段必须自己选一个 policy，选了就按选的来，没选直接报错。**

为什么这么设计（吃过亏）：
- ComfyUI 的 optional 输入只有“连了/没连”两种状态，表达不了“我要覆盖成空”；
- 如果默认“没连就沿用”，用户很容易以为“这段没连=没有素材”，结果沿用了上一段的，
  生成出来才发现人物/场景串了；
- 所以每个可覆盖输入都配一个 policy 枚举。默认值 `unset`，执行时一看到 unset 就报
  DD-E001，绝不做“猜测式继承”。

解析时的“基线”是什么：
- 有上一段：基线 = 上一段解析出来的结果；
- 第一段没有上一段：基线 = 链首的全局默认（模型加载器/全局配置/全局素材那些）；
- 所以 `inherit` 在第一段也合法（等于“用全局默认”），不会出现“空继承”。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from . import assets as assets_lib
from .types import (
    ASSETS_POLICIES,
    BRIEF_POLICIES,
    BUNDLE_POLICIES,
    CAST_POLICIES,
    CONFIG_OVERRIDE_ALLOWED,
    CONFIG_POLICIES,
    CONTINUITY_MODES,
    REQUIRED_POLICY_KEYS,
    check_choice,
    error,
)


def canonical_json(value: Any) -> str:
    """稳定 JSON 序列化：同样的内容一定得到同样的字符串，用来算哈希。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_cast(data: Mapping[str, Any] | None) -> dict:
    """把音色数据扶正成标准结构（角色列表 + 是否锁音 + 混音规则）。"""
    base = {"schema": "DIRECTOR_CAST@1",
            "roles": list((data or {}).get("roles") or []),
            "lock_audio": bool((data or {}).get("lock_audio", False)),
            "mix": dict((data or {}).get("mix") or {})}
    return base


def _serializable_cast(cast: Mapping[str, Any] | None) -> dict:
    """给“要落盘/进 JSON”的场景用的 cast：把音频张量等运行期字段摘掉。

    为什么要单独一个函数：真正的 cast 里带着 audio_data（张量），采样要用；
    但 segment 元数据要写 history/磁盘，张量不能序列化，必须在这里降级。
    混音规则（mix）和每路增益/优先级是纯数据，必须保留——它们会影响画面声音。
    """
    data = _normalize_cast(cast)
    roles = []
    for role in data["roles"]:
        item = {k: v for k, v in role.items()
                if k in ("id", "name", "start", "voice", "gain_db", "priority")}
        roles.append(item)
    data["roles"] = roles
    return data


def merge_cast_by_character(base: Mapping[str, Any] | None,
                            override: Mapping[str, Any] | None) -> dict:
    """按“角色 id”合并音色：override 里点名的角色替换，其他角色保持 base。

    典型场景：整部剧 6 个角色都配好了音色，某一集只想换“男主”的声音，
    就传一个只含男主的 cast 覆盖包，其他 5 个自动继承。
    """
    out = _normalize_cast(base)
    by_id = {role.get("id"): dict(role) for role in out["roles"] if role.get("id")}
    for role in (override or {}).get("roles") or []:
        rid = role.get("id")
        if not rid:
            continue
        by_id[rid] = dict(role)
    out["roles"] = list(by_id.values())
    if "lock_audio" in (override or {}):
        out["lock_audio"] = bool(override["lock_audio"])
    if (override or {}).get("mix"):
        out["mix"] = dict(override["mix"])
    return out


def _bundle_summary(bundle: Any) -> dict:
    """把 bundle 降级成“能 JSON 序列化”的摘要。

    为什么要这一步：bundle 里装着 MODEL/CLIP/VAE 这些 Python 对象，直接塞进
    segment 元数据会让 ComfyUI 在写 history 时 JSON 序列化失败（我们踩过这个坑）。
    这里只保留 bundle_id 和加载配置（spec），出问题也能靠它们复现。
    """
    if not isinstance(bundle, Mapping):
        return {}
    if "bundle_id" in bundle:
        return {"bundle_id": bundle.get("bundle_id"),
                "spec": bundle.get("spec") or {}}
    # 兜底：只留基本类型字段，对象一律丢掉。
    return {k: v for k, v in bundle.items()
            if isinstance(v, (str, int, float, bool, type(None)))}


@dataclass
class Resolution:
    """一段解析完成后的“最终输入快照”。

    这个对象会一路传给生成器，并原样塞进 DIRECTOR_SEGMENT.resolved，
    方便事后追溯“这一段到底用了哪张图、哪个音色、哪套配置”。
    """

    index: int
    bundle: dict
    config: dict
    assets: dict
    brief: dict | None
    cast: dict
    continuity: str
    guide: dict | None = None
    warnings: list[str] = field(default_factory=list)

    def canonical(self) -> dict:
        """可序列化/可哈希的形式（图片张量会被剔除，太大且不稳定）。"""
        assets_meta = assets_lib.normalize_assets(self.assets)
        assets_meta.pop("images", None)
        return {
            "index": self.index,
            "bundle": _bundle_summary(self.bundle),
            "config": self.config,
            "assets": assets_meta,
            "brief": self.brief,
            "cast": _serializable_cast(self.cast),
            "continuity": self.continuity,
            "guide": self.guide,
        }

    @property
    def hash(self) -> str:
        """解析结果指纹。抽卡缓存的关键：这个值变了就必须重跑。"""
        return "sha1:" + hashlib.sha1(
            canonical_json(self.canonical()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        """带 hash 和 warnings 的完整字典（写进 segment 元数据用）。"""
        data = self.canonical()
        data["hash"] = self.hash
        data["warnings"] = self.warnings
        return data


def _require_socket(sockets: Mapping[str, Any], name: str, policy_name: str) -> Any:
    """“你选了 replace/merge/overrides，那就必须把输入连上”，不然报 DD-E002。"""
    value = sockets.get(name)
    if value is None:
        raise error("DD-E002", f"{policy_name} 为显式覆盖，但输入 `{name}` 未连接")
    return value


def resolve_segment(*, index: int, policies: Mapping[str, str],
                    sockets: Mapping[str, Any] | None = None,
                    previous: "Resolution | None" = None,
                    defaults: Mapping[str, Any] | None = None) -> Resolution:
    """解析一段的最终输入。

    参数：
    - index：段序号（0 起）。
    - policies：6 个策略键，缺一个/填 unset 都会报 DD-E001。
    - sockets：实际连上来的东西（bundle/config_override/assets/brief/cast）；
      没连就是 None。
    - previous：上一段的 Resolution；第一段给 None。
    - defaults：链首的全局默认值（bundle/config/assets/brief/cast）。

    返回值：Resolution，里面是“这段到底用什么”的最终答案。
    """
    if index < 0:
        raise error("DD-E004", f"index 不能为负：{index}")
    sockets = dict(sockets or {})
    defaults = dict(defaults or {})

    # ---------- 第一步：六个策略必须都选了，`unset` 一律不放过 ----------
    missing = [key for key in REQUIRED_POLICY_KEYS
               if key not in policies or policies.get(key) == "unset"]
    if missing:
        raise error("DD-E001", f"缺少/未指定：{', '.join(missing)}")

    # 每个策略的值必须在该字段允许的枚举里（顺便把 unset 再兜一遍）。
    bundle_policy = check_choice("bundle_policy", policies["bundle_policy"], BUNDLE_POLICIES)
    config_policy = check_choice("config_policy", policies["config_policy"], CONFIG_POLICIES)
    assets_policy = check_choice("assets_policy", policies["assets_policy"], ASSETS_POLICIES)
    brief_policy = check_choice("brief_policy", policies["brief_policy"], BRIEF_POLICIES)
    cast_policy = check_choice("cast_policy", policies["cast_policy"], CAST_POLICIES)
    continuity = check_choice("continuity", policies["continuity"], CONTINUITY_MODES)

    # ---------- 第二步：模型 bundle（只允许链首指定） ----------
    if index == 0:
        if bundle_policy == "provided":
            # 第一段必须从模型加载器接过来。
            bundle = _require_socket(sockets, "bundle", "bundle_policy=provided")
        else:  # inherit：第一段没有上一段，只能吃全局默认
            bundle = defaults.get("bundle")
            if not bundle:
                raise error("DD-E005", "第一段缺少模型 bundle（请连接模型加载器）")
    else:
        # 之后的段：只能继承，不能换模型。换模型=换一条链，得从头开始。
        if bundle_policy != "inherit":
            raise error("DD-E004", "第 2 段起的 bundle_policy 必须是 inherit（模型只能在链首指定）")
        bundle = previous.bundle if previous is not None else defaults.get("bundle")
        if not bundle:
            raise error("DD-E005", "缺少上一段/全局模型 bundle")
    # 浅拷贝一下，避免下游手滑改到原始对象。
    bundle = dict(bundle) if isinstance(bundle, Mapping) else {}

    # ---------- 第三步：配置（沿用或只覆盖安全字段） ----------
    base_config = dict(previous.config) if previous is not None else dict(
        defaults.get("config") or {})
    if config_policy == "inherit":
        config = base_config
    else:
        overrides = _require_socket(sockets, "config_override", "config_policy=overrides")
        # 白名单外的一律拒绝：宽高/fps/模型这些改了会破坏整条链的假设。
        unknown = set(overrides) - CONFIG_OVERRIDE_ALLOWED
        if unknown:
            raise error("DD-E006", f"段级不允许覆盖：{sorted(unknown)}")
        config = dict(base_config)
        config.update(dict(overrides))

    # ---------- 第四步：素材（沿用/替换/按槽合并/清空） ----------
    base_assets = previous.assets if previous is not None else defaults.get("assets")
    if assets_policy == "inherit":
        assets = assets_lib.normalize_assets(base_assets)
    elif assets_policy == "replace":
        assets = assets_lib.normalize_assets(
            _require_socket(sockets, "assets", "assets_policy=replace"))
    elif assets_policy == "merge":
        # 按 @图片N 槽位覆盖：只换你接进来的那几槽，其余继续用上一段。
        override = assets_lib.normalize_assets(
            _require_socket(sockets, "assets", "assets_policy=merge"))
        assets = assets_lib.merge_assets(base_assets, override)
    else:  # clear：这一段明确不要任何素材
        assets = assets_lib.empty_assets()

    # ---------- 第五步：段级剧本（沿用脚本段落 或 用 Brief 覆盖） ----------
    if brief_policy == "replace":
        brief = _require_socket(sockets, "brief", "brief_policy=replace")
        brief = dict(brief) if isinstance(brief, Mapping) else {"text": str(brief)}
    else:
        brief = previous.brief if previous is not None else defaults.get("brief")

    # ---------- 第六步：音色 ----------
    base_cast = previous.cast if previous is not None else defaults.get("cast")
    if cast_policy == "inherit":
        cast = _normalize_cast(base_cast)
    elif cast_policy == "replace":
        cast = _normalize_cast(_require_socket(sockets, "cast", "cast_policy=replace"))
    else:  # merge_by_character：只换点名角色
        override = _require_socket(sockets, "cast", "cast_policy=merge_by_character")
        cast = merge_cast_by_character(base_cast, override)

    # ---------- 第七步：画面衔接 ----------
    warnings: list[str] = []
    if index == 0:
        # 第一段没有“上一段的尾巴”可接，只能 start。
        if continuity != "start":
            raise error("DD-E004", "第一段 continuity 必须是 start")
        guide = None
    else:
        if continuity == "start":
            raise error("DD-E004", "只有第一段可以用 continuity=start")
        if continuity == "guide_tail":
            if previous is None:
                raise error("DD-E008", "continuity=guide_tail 但缺少上一段")
            guide = {"source_index": previous.index, "mode": "guide_tail"}
        else:  # none：明确断链，新镜头硬切
            guide = None

    # 锁音开启了却一个角色都没绑音轨 —— 不至于报错，但必须提醒。
    if cast.get("lock_audio"):
        roles = [r for r in cast.get("roles") or [] if r.get("voice")]
        if not roles:
            warnings.append("lock_audio=True 但没有任何角色绑定音轨")

    return Resolution(index=index, bundle=bundle, config=config, assets=assets,
                      brief=brief, cast=cast, continuity=continuity,
                      guide=guide, warnings=warnings)


def resolve_chain(segments: list[Mapping[str, Any]], *,
                  defaults: Mapping[str, Any],
                  sockets_by_index: Mapping[int, Mapping[str, Any]] | None = None
                  ) -> list[Resolution]:
    """把整条链按顺序解析一遍（测试/计划器用）。

    每一段都依赖上一段的解析结果，所以只能顺序算，不能并行。
    """
    sockets_by_index = sockets_by_index or {}
    resolutions: list[Resolution] = []
    for index, segment in enumerate(segments):
        previous = resolutions[-1] if resolutions else None
        resolutions.append(resolve_segment(
            index=index,
            policies=segment["policies"],
            sockets=sockets_by_index.get(index, {}),
            previous=previous,
            defaults=defaults,
        ))
    return resolutions
