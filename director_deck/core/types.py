"""DirectorDeck 的“名词表”：自定义类型名、policy 枚举、错误码、各种常量。

这个文件是纯 Python，故意不 import 任何 ComfyUI 的东西。
原因很简单：core 层要能在普通 Python 环境里跑单测，不能在 CI 上还要装 ComfyUI。

口语化说明：
- ComfyUI 的“自定义连线类型”其实就是个字符串，节点 RETURN_TYPES 写什么字符串，
  下游能接的也是同一个字符串，所以这里统一用常量，别手滑拼错。
- policy 是“这一段到底用谁的素材/音色/剧本”的开关。我们定了个规矩：
  **每段必须自己显式选一个**，默认值给 `unset`，谁敢不选就当场报错，
  免得出现“以为继承了结果没继承”的幽灵 bug。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 命名相关
# 我们所有节点 ID 都加这个前缀，防止和别人的插件撞名（ComfyUI 里节点 ID 是全局唯一的）。
NODE_PREFIX = "DirectorDeck_"

# 节点在右键菜单里的分类根目录。
CATEGORY = "DirectorDeck"

# ---------------------------------------------------------------- 自定义连线类型
# 这些字符串就是节点之间“插头”的形状。新增类型时记得同步 docs/CONTRACTS.md。
TYPE_BUNDLE = "DIRECTOR_BUNDLE"                  # 模型组合（主干/TE/双 VAE/LoRA）
TYPE_CONFIG = "DIRECTOR_CONFIG"                  # 全局配置
TYPE_CONFIG_OVERRIDE = "DIRECTOR_CONFIG_OVERRIDE"  # 段级配置覆盖（只允许安全字段）
TYPE_ASSETS = "DIRECTOR_ASSETS"                  # 9 槽素材包
TYPE_SCRIPT = "DIRECTOR_SCRIPT"                  # 结构化剧本
TYPE_BRIEF = "DIRECTOR_BRIEF"                    # 单段剧本覆盖
TYPE_CAST = "DIRECTOR_CAST"                      # 角色 -> 音色/人脸映射
TYPE_PLAN = "DIRECTOR_PLAN"                      # 整条链的帧计划
TYPE_SEGMENT = "DIRECTOR_SEGMENT"                # 一段生成结果
TYPE_MANIFEST = "DIRECTOR_MANIFEST"              # 成片清单（M2 起用）

# 类型内部再带一个 schema 版本号，将来字段变了可以写迁移，不至于把老工作流读崩。
SCHEMA_VERSION = 1

# ---------------------------------------------------------------- 硬性常量
# H3 是原生 24fps，别想着改它；改了这个值后面时长、帧数、音轨全乱。
FPS = 24

# H3 的时间栅格是 17k+5：帧数必须满足 17 的倍数再加 5（124、158、175、243……）。
# 这不是我们定的，是模型训练时的时序 patch 大小决定的，填错模型会直接报错。
FRAME_STEP = 17
FRAME_OFFSET = 5

# 段与段之间“接住上一段结尾多少帧”，H3 只认这几个值（也是 17k+5 的子集）。
HANDOFF_GRID = (5, 22, 39, 56)

# 素材槽固定 9 个：提示词里写 @图片3，指的就是第 3 槽。槽位固定才好做 merge。
ASSET_SLOT_COUNT = 9

# 一次剧本最多拆多少段。只是防呆，真拍不了这么多。
MAX_SEGMENTS = 64

# ---------------------------------------------------------------- policy 枚举
# 注意：所有 policy 的“未选择”状态统一叫 unset；节点的默认值也是它。
# 执行时一旦发现 unset，直接抛 DD-E001，绝不偷偷按沿用来处理。
POLICY_UNSET = "unset"

# 素材：沿用 / 整包替换 / 按槽位覆盖 / 明确清空。
# clear 是给“这一段我就是不要参考图”用的，不然“没连”和“连了个空的”分不清。
ASSETS_POLICIES = ("inherit", "replace", "merge", "clear")

# 段级剧本：沿用脚本里那一段 / 用本段 Brief 覆盖。
BRIEF_POLICIES = ("inherit", "replace")

# 音色：沿用 / 整包替换 / 按角色 id 覆盖（只换你点名的角色，其他照旧）。
CAST_POLICIES = ("inherit", "replace", "merge_by_character")

# 配置：沿用 / 只覆盖白名单里的安全字段。
CONFIG_POLICIES = ("inherit", "overrides")

# 画面衔接：第 1 段只能 start；之后要么接着上一段尾巴（guide_tail），要么明确断链（none）。
CONTINUITY_MODES = ("start", "guide_tail", "none")

# 模型只能链首提供（provided），后面段落只能继承（inherit）。
# 为什么？换模型等于换了一条链，latent 空间都对不上了，硬接只会出鬼片。
BUNDLE_POLICIES = ("provided", "inherit")

# DirectorTake 必须一次性凑齐的六个策略键，少一个都不让跑。
REQUIRED_POLICY_KEYS = (
    "bundle_policy",
    "config_policy",
    "assets_policy",
    "brief_policy",
    "cast_policy",
    "continuity",
)

# 段级配置能改的东西：都是“不影响链结构”的参数。
# 宽高、fps、模型、输出目录故意不让改——半条链换画布/换模型，后面全得重来。
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

# ---------------------------------------------------------------- 错误码
# 每个错误码都配了一句人话，给前端/i18n 用；真正报错时会把具体细节接在后面。
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
    """DirectorDeck 的统一异常。

    继承 ValueError 是为了让 ComfyUI 把它当普通输入错误展示（而不是红屏崩溃），
    同时我们保留了 code，方便前端按错误码做提示或自动修复。
    """

    def __init__(self, code: str, message: str, *, node: str | None = None,
                 segment: int | None = None):
        self.code = code
        self.message = message
        self.node = node
        self.segment = segment
        super().__init__(self.__str__())

    def __str__(self) -> str:
        # 拼一句“哪个节点的第几段出了什么问题”，用户不用去翻代码就能定位。
        where = []
        if self.segment is not None:
            where.append(f"第 {self.segment + 1} 段")
        if self.node:
            where.append(self.node)
        prefix = f"[{self.code}] " + ("（" + " / ".join(where) + "）" if where else "")
        return prefix + self.message


def error(code: str, detail: str = "", **kwargs) -> DirectorError:
    """按错误码拼一个异常：标准文案 + 具体细节。

    这样调用方只需要 raise error("DD-E006", f"width 不在白名单")，
    不用每次都手写一整句话。
    """
    base = ERROR_MESSAGES.get(code, "未知错误")
    msg = f"{base}：{detail}" if detail else base
    return DirectorError(code, msg, **kwargs)


def check_choice(name: str, value, choices, *, code: str = "DD-E004") -> str:
    """校验“某个策略字段选得对不对”。

    两种情况会炸：
    1) 没选（None 或 unset）—— 这是我们最在意的，报 DD-E001；
    2) 选了但不在允许列表里 —— 报 DD-E004。
    返回校验通过的值，方便链式写法。
    """
    if value is None or value == POLICY_UNSET:
        raise error("DD-E001", f"{name} 必须显式指定（可选：{', '.join(choices)}）")
    if value not in choices:
        raise error(code, f"{name}={value!r} 不在允许值 {list(choices)} 内")
    return value
