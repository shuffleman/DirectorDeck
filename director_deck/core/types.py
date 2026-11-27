"""DirectorDeck 类型常量、policy 枚举、错误码。

纯 Python，不依赖 ComfyUI —— core 层所有模块都可以在 ComfyUI 外单测。
"""

from __future__ import annotations

# ------------------------------------------------------------------ 命名
NODE_PREFIX = "DirectorDeck_"
CATEGORY = "DirectorDeck"

# socket 类型（ComfyUI 自定义类型就是字符串）
TYPE_BUNDLE = "DIRECTOR_BUNDLE"
TYPE_CONFIG = "DIRECTOR_CONFIG"
TYPE_CONFIG_OVERRIDE = "DIRECTOR_CONFIG_OVERRIDE"
TYPE_ASSETS = "DIRECTOR_ASSETS"
TYPE_SCRIPT = "DIRECTOR_SCRIPT"
TYPE_BRIEF = "DIRECTOR_BRIEF"
TYPE_CAST = "DIRECTOR_CAST"
TYPE_PLAN = "DIRECTOR_PLAN"
TYPE_SEGMENT = "DIRECTOR_SEGMENT"
TYPE_MANIFEST = "DIRECTOR_MANIFEST"

SCHEMA_VERSION = 1

# ------------------------------------------------------------------ 常量
FPS = 24
FRAME_STEP = 17
FRAME_OFFSET = 5
HANDOFF_GRID = (5, 22, 39, 56)
ASSET_SLOT_COUNT = 9
MAX_SEGMENTS = 64

# ------------------------------------------------------------------ policy 枚举
POLICY_UNSET = "unset"

ASSETS_POLICIES = ("inherit", "replace", "merge", "clear")
BRIEF_POLICIES = ("inherit", "replace")
CAST_POLICIES = ("inherit", "replace", "merge_by_character")
CONFIG_POLICIES = ("inherit", "overrides")
CONTINUITY_MODES = ("start", "guide_tail", "none")
BUNDLE_POLICIES = ("provided", "inherit")

# DirectorTake 必须显式给出的策略键（缺一不可，值为 unset 也报错）
REQUIRED_POLICY_KEYS = (
    "bundle_policy",
    "config_policy",
    "assets_policy",
    "brief_policy",
    "cast_policy",
    "continuity",
)

# 段级 config 允许覆盖的安全子集（模型/画布/输出目录等不允许）
CONFIG_OVERRIDE_ALLOWED = frozenset({
    "segment_seconds",
    "handoff_frames",
    "sampler_name",
    "sigmas_string",
    "interpolate_to_steps",
    "denoise",
    "seed_strategy",
    "seed_base",
    "preview",
    "vram_policy",
})

# ------------------------------------------------------------------ 错误码
ERROR_MESSAGES = {
    "DD-E001": "policy 未指定",
    "DD-E002": "显式覆盖策略但输入未连接",
    "DD-E003": "第一段不能 inherit（应使用 provided / 全局默认）",
    "DD-E004": "policy 组合非法",
    "DD-E005": "缺少 bundle（第一段必须连接模型加载器）",
    "DD-E006": "config overrides 含非安全字段",
    "DD-E007": "merge_by_character 角色不存在（警告）",
    "DD-E008": "guide_tail 需要上一段",
    "DD-E010": "素材引用越界（@图片N > 9）",
    "DD-E011": "引用素材为空槽或文件缺失",
    "DD-E020": "帧长不是 17k+5",
    "DD-E021": "宽高不是 32 的倍数",
    "DD-E030": "数字人锁音：音轨缺失或长度不匹配",
    "DD-E031": "链内模型 bundle 不一致",
}


class DirectorError(ValueError):
    """统一错误类型：code 用于前端/i18n，message 面向用户（中文）。"""

    def __init__(self, code: str, message: str, *, node: str | None = None,
                 segment: int | None = None):
        self.code = code
        self.message = message
        self.node = node
        self.segment = segment
        super().__init__(self.__str__())

    def __str__(self) -> str:
        where = []
        if self.segment is not None:
            where.append(f"第 {self.segment + 1} 段")
        if self.node:
            where.append(self.node)
        prefix = f"[{self.code}] " + ("（" + " / ".join(where) + "）" if where else "")
        return prefix + self.message


def error(code: str, detail: str = "", **kwargs) -> DirectorError:
    """按错误码构造异常，detail 追加在标准文案后。"""
    base = ERROR_MESSAGES.get(code, "未知错误")
    msg = f"{base}：{detail}" if detail else base
    return DirectorError(code, msg, **kwargs)


def check_choice(name: str, value, choices, *, code: str = "DD-E004") -> str:
    if value is None or value == POLICY_UNSET:
        raise error("DD-E001", f"{name} 必须显式指定（可选：{', '.join(choices)}）")
    if value not in choices:
        raise error(code, f"{name}={value!r} 不在允许值 {list(choices)} 内")
    return value
