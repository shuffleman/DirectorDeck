"""DirectorDeck 节点层：把各个节点类汇总成 ComfyUI 需要的映射表。

加新节点的步骤（给自己留的备忘）：
1. 在 nodes/ 下新建一个文件，写节点类（INPUT_TYPES / RETURN_TYPES / FUNCTION / CATEGORY）；
2. 在这里 import 进来，加进 NODE_CLASS_MAPPINGS；
3. 同时加 NODE_DISPLAY_NAME_MAPPINGS（中文显示名，菜单里好看）；
4. 记得同步 docs/CONTRACTS.md 的节点表，参数只能追加不能改顺序。
"""

from .brief import DirectorDeckSegmentBrief
from .config import DirectorDeckConfig
from .loader import DirectorDeckModelLoader
from .script_node import DirectorDeckScriptDesk
from .shelf import DirectorDeckAssetShelf
from .take import DirectorDeckTake

NODE_CLASS_MAPPINGS = {
    "DirectorDeck_ModelLoader": DirectorDeckModelLoader,
    "DirectorDeck_DirectorConfig": DirectorDeckConfig,
    "DirectorDeck_AssetShelf": DirectorDeckAssetShelf,
    "DirectorDeck_ScriptDesk": DirectorDeckScriptDesk,
    "DirectorDeck_SegmentBrief": DirectorDeckSegmentBrief,
    "DirectorDeck_DirectorTake": DirectorDeckTake,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DirectorDeck_ModelLoader": "DirectorDeck · 模型加载器",
    "DirectorDeck_DirectorConfig": "DirectorDeck · 全局配置",
    "DirectorDeck_AssetShelf": "DirectorDeck · 资产管理器",
    "DirectorDeck_ScriptDesk": "DirectorDeck · 剧本加载器",
    "DirectorDeck_SegmentBrief": "DirectorDeck · 段级剧本",
    "DirectorDeck_DirectorTake": "DirectorDeck · 视频生成器",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
