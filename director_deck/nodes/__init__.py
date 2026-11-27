"""DirectorDeck 节点层：把各个节点类汇总成 ComfyUI 需要的映射表。

加新节点的步骤（给自己留的备忘）：
1. 在 nodes/ 下新建一个文件，写节点类（INPUT_TYPES / RETURN_TYPES / FUNCTION / CATEGORY）；
2. 在这里 import 进来，加进 NODE_CLASS_MAPPINGS；
3. 同时加 NODE_DISPLAY_NAME_MAPPINGS（中文显示名，菜单里好看）；
4. 记得同步 docs/CONTRACTS.md 的节点表，参数只能追加不能改顺序。
"""

from .brief import DirectorDeckSegmentBrief
from .cache import DirectorDeckSegmentCache
from .config import DirectorDeckConfig
from .final_cut import DirectorDeckFinalCut
from .loader import DirectorDeckModelLoader
from .planner import DirectorDeckFramePlanner
from .refiner import DirectorDeckRefiner
from .script_node import DirectorDeckScriptDesk
from .script_import import DirectorDeckScriptImport
from .seam_fixer import DirectorDeckSeamFixer
from .shelf import DirectorDeckAssetShelf
from .take import DirectorDeckTake
from .tts_booth import DirectorDeckTTSBooth
from .voice_lock import DirectorDeckVoiceLock

NODE_CLASS_MAPPINGS = {
    "DirectorDeck_ModelLoader": DirectorDeckModelLoader,
    "DirectorDeck_DirectorConfig": DirectorDeckConfig,
    "DirectorDeck_AssetShelf": DirectorDeckAssetShelf,
    "DirectorDeck_ScriptDesk": DirectorDeckScriptDesk,
    "DirectorDeck_ScriptImport": DirectorDeckScriptImport,
    "DirectorDeck_SegmentBrief": DirectorDeckSegmentBrief,
    "DirectorDeck_FramePlanner": DirectorDeckFramePlanner,
    "DirectorDeck_DirectorTake": DirectorDeckTake,
    "DirectorDeck_SeamFixer": DirectorDeckSeamFixer,
    "DirectorDeck_FinalCut": DirectorDeckFinalCut,
    "DirectorDeck_SegmentCache": DirectorDeckSegmentCache,
    "DirectorDeck_VoiceLock": DirectorDeckVoiceLock,
    "DirectorDeck_TTSBooth": DirectorDeckTTSBooth,
    "DirectorDeck_Refiner": DirectorDeckRefiner,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DirectorDeck_ModelLoader": "DirectorDeck · 模型加载器",
    "DirectorDeck_DirectorConfig": "DirectorDeck · 全局配置",
    "DirectorDeck_AssetShelf": "DirectorDeck · 资产管理器",
    "DirectorDeck_ScriptDesk": "DirectorDeck · 剧本加载器",
    "DirectorDeck_ScriptImport": "DirectorDeck · 剧本导入（素材自动匹配）",
    "DirectorDeck_SegmentBrief": "DirectorDeck · 段级剧本",
    "DirectorDeck_FramePlanner": "DirectorDeck · 帧计划器",
    "DirectorDeck_DirectorTake": "DirectorDeck · 视频生成器",
    "DirectorDeck_SeamFixer": "DirectorDeck · 接缝修正器",
    "DirectorDeck_FinalCut": "DirectorDeck · 多段合并器",
    "DirectorDeck_SegmentCache": "DirectorDeck · 抽卡缓存",
    "DirectorDeck_VoiceLock": "DirectorDeck · 数字人锁音器",
    "DirectorDeck_TTSBooth": "DirectorDeck · TTS 台词表（多角色配音）",
    "DirectorDeck_Refiner": "DirectorDeck · 二采工具",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
