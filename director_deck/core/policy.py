"""分段覆盖/继承解析（契约 §3/§4，已按「每段必须显式指定」定稿）。

规则：
- 所有 policy 必须显式给出，值为 `unset` 时报 DD-E001；
- 基线 = previous（上一段解析结果），没有 previous 时 = 全局默认（链首节点）；
- 显式覆盖（replace/merge/overrides/clear）优先，且必须连接对应输入；
- 只有第 1 段可以是 bundle_policy=provided / continuity=start；
- 结果算 canonical hash 供缓存/抽卡指纹使用。
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
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_cast(data: Mapping[str, Any] | None) -> dict:
    base = {"schema": "DIRECTOR_CAST@1", "roles": list((data or {}).get("roles") or []),
            "lock_audio": bool((data or {}).get("lock_audio", False))}
    return base


def merge_cast_by_character(base: Mapping[str, Any] | None,
                            override: Mapping[str, Any] | None) -> dict:
    """按角色 id 覆盖；未出现的角色沿用 base。"""
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
    return out


@dataclass
class Resolution:
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
        return {
            "index": self.index,
            "bundle": self.bundle,
            "config": self.config,
            "assets": assets_lib.normalize_assets(self.assets),
            "brief": self.brief,
            "cast": _normalize_cast(self.cast),
            "continuity": self.continuity,
            "guide": self.guide,
        }

    @property
    def hash(self) -> str:
        return "sha1:" + hashlib.sha1(
            canonical_json(self.canonical()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        data = self.canonical()
        data["hash"] = self.hash
        data["warnings"] = self.warnings
        return data


def _require_socket(sockets: Mapping[str, Any], name: str, policy_name: str) -> Any:
    value = sockets.get(name)
    if value is None:
        raise error("DD-E002", f"{policy_name} 为显式覆盖，但输入 `{name}` 未连接")
    return value


def resolve_segment(*, index: int, policies: Mapping[str, str],
                    sockets: Mapping[str, Any] | None = None,
                    previous: Resolution | None = None,
                    defaults: Mapping[str, Any] | None = None) -> Resolution:
    """解析一段的最终输入。

    Args:
        index: 段序号（0 起）
        policies: 6 个 policy（见 types.REQUIRED_POLICY_KEYS）
        sockets: 已连接输入，key: bundle/config_override/assets/brief/cast
        previous: 上一段 Resolution（第 1 段为 None）
        defaults: 链首全局默认（bundle/config/assets/brief/cast）
    """
    if index < 0:
        raise error("DD-E004", f"index 不能为负：{index}")
    sockets = dict(sockets or {})
    defaults = dict(defaults or {})

    missing = [key for key in REQUIRED_POLICY_KEYS
               if key not in policies or policies.get(key) == "unset"]
    if missing:
        raise error("DD-E001", f"缺少/未指定：{', '.join(missing)}")

    bundle_policy = check_choice("bundle_policy", policies["bundle_policy"], BUNDLE_POLICIES)
    config_policy = check_choice("config_policy", policies["config_policy"], CONFIG_POLICIES)
    assets_policy = check_choice("assets_policy", policies["assets_policy"], ASSETS_POLICIES)
    brief_policy = check_choice("brief_policy", policies["brief_policy"], BRIEF_POLICIES)
    cast_policy = check_choice("cast_policy", policies["cast_policy"], CAST_POLICIES)
    continuity = check_choice("continuity", policies["continuity"], CONTINUITY_MODES)

    # ---------------- bundle：只允许链首提供，之后必须继承 ----------------
    if index == 0:
        if bundle_policy == "provided":
            bundle = _require_socket(sockets, "bundle", "bundle_policy=provided")
        else:  # inherit -> 全局默认
            bundle = defaults.get("bundle")
            if not bundle:
                raise error("DD-E005", "第一段缺少模型 bundle（请连接 ModelLoader）")
    else:
        if bundle_policy != "inherit":
            raise error("DD-E004", "第 2 段起的 bundle_policy 必须是 inherit（模型只能在链首指定）")
        if previous is not None:
            bundle = previous.bundle
        else:
            bundle = defaults.get("bundle")
            if not bundle:
                raise error("DD-E005", "缺少上一段/全局模型 bundle")
    bundle = dict(bundle) if isinstance(bundle, Mapping) else {}

    # ---------------- config ----------------
    base_config = dict(previous.config) if previous is not None else dict(defaults.get("config") or {})
    if config_policy == "inherit":
        config = base_config
    else:
        overrides = _require_socket(sockets, "config_override", "config_policy=overrides")
        unknown = set(overrides) - CONFIG_OVERRIDE_ALLOWED
        if unknown:
            raise error("DD-E006", f"段级不允许覆盖：{sorted(unknown)}")
        config = dict(base_config)
        config.update(dict(overrides))

    # ---------------- assets ----------------
    base_assets = (previous.assets if previous is not None
                   else defaults.get("assets"))
    if assets_policy == "inherit":
        assets = assets_lib.normalize_assets(base_assets)
    elif assets_policy == "replace":
        assets = assets_lib.normalize_assets(
            _require_socket(sockets, "assets", "assets_policy=replace"))
    elif assets_policy == "merge":
        override = assets_lib.normalize_assets(
            _require_socket(sockets, "assets", "assets_policy=merge"))
        assets = assets_lib.merge_assets(base_assets, override)
    else:  # clear
        assets = assets_lib.empty_assets()

    # ---------------- brief ----------------
    if brief_policy == "replace":
        brief = _require_socket(sockets, "brief", "brief_policy=replace")
        brief = dict(brief) if isinstance(brief, Mapping) else {"text": str(brief)}
    else:
        brief = previous.brief if previous is not None else defaults.get("brief")

    # ---------------- cast ----------------
    base_cast = previous.cast if previous is not None else defaults.get("cast")
    if cast_policy == "inherit":
        cast = _normalize_cast(base_cast)
    elif cast_policy == "replace":
        cast = _normalize_cast(_require_socket(sockets, "cast", "cast_policy=replace"))
    else:  # merge_by_character
        override = _require_socket(sockets, "cast", "cast_policy=merge_by_character")
        cast = merge_cast_by_character(base_cast, override)

    # ---------------- continuity ----------------
    warnings: list[str] = []
    if index == 0:
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
        else:
            guide = None

    if cast.get("lock_audio"):
        roles = [r for r in cast.get("roles") or [] if r.get("voice")]
        if not roles:
            warnings.append("lock_audio=True 但没有任何角色绑定音轨")

    return Resolution(index=index, bundle=bundle, config=config, assets=assets,
                      brief=brief, cast=cast, continuity=continuity,
                      guide=guide, warnings=warnings)


def resolve_chain(segments: list[Mapping[str, Any]], *,
                  defaults: Mapping[str, Any],
                  sockets_by_index: Mapping[int, Mapping[str, Any]] | None = None) -> list[Resolution]:
    """按顺序解析整条链（测试/计划器用）。segments[i] 至少含 policies 键。"""
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
