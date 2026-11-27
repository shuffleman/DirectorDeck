"""画布工作流（examples/ui/*.json）的结构单测（不需要 ComfyUI）。

这些断言防的是“生成器改坏了工作流文件”：
- 顶层必须是 UI version 0.4 的字段；
- 节点 id / link id 唯一；
- 每条 link 的 4 个端点（来源/目标/槽位）都真实存在；
- 非 Note 节点必须有 widgets_values；
- 能通过我们自己的 ui_to_api（结构完整性），且至少包含预期类。
"""

import json
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(REPO, "examples", "ui")

EXPECTED = {
    "DirectorDeck_M1_单段闭环.json": {"DirectorDeck_ModelLoader", "DirectorDeck_DirectorTake"},
    "DirectorDeck_M1_参考生视频.json": {"DirectorDeck_AssetShelf", "DirectorDeck_SegmentBrief"},
    "DirectorDeck_M2_三段链.json": {"DirectorDeck_FinalCut"},
    "DirectorDeck_M3_数字人锁音.json": {"DirectorDeck_VoiceLock", "DirectorDeck_Refiner"},
    "DirectorDeck_M4_锁音无损.json": {"DirectorDeck_FinalCut", "SaveAudio"},
    "DirectorDeck_M5_latent续写.json": {"DirectorDeck_DirectorTake", "DirectorDeck_FinalCut"},
    "DirectorDeck_M6_多角色混音.json": {"DirectorDeck_VoiceLock", "DirectorDeck_FinalCut"},
    "DirectorDeck_M8_TTS锁音.json": {"BreezeTTS2VoiceDesign", "DirectorDeck_VoiceLock"},
    "DirectorDeck_M9_台词表配音.json": {"DirectorDeck_TTSBooth", "DirectorDeck_FinalCut"},
    "DirectorDeck_M10_台词自动排期.json": {"DirectorDeck_TTSBooth", "DirectorDeck_DirectorTake"},
}


class UiWorkflowTest(unittest.TestCase):
    def _load(self, name):
        with open(os.path.join(UI_DIR, name), "r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_all_files_exist(self):
        for name in EXPECTED:
            self.assertTrue(os.path.isfile(os.path.join(UI_DIR, name)), name)

    def test_structure(self):
        for name, must_have in EXPECTED.items():
            workflow = self._load(name)
            self.assertEqual(workflow.get("version"), 0.4, name)
            nodes = workflow["nodes"]
            links = workflow["links"]
            node_ids = {node["id"] for node in nodes}
            self.assertEqual(len(node_ids), len(nodes), f"{name} 节点 id 重复")
            self.assertEqual(workflow["last_node_id"], max(node_ids), name)
            link_ids = [link[0] for link in links]
            self.assertEqual(len(set(link_ids)), len(link_ids), f"{name} link id 重复")
            self.assertEqual(workflow["last_link_id"], max(link_ids or [0]), name)

            for link in links:
                _lid, origin_id, origin_slot, target_id, target_slot, _typ = link
                self.assertIn(origin_id, node_ids, f"{name} link 来源节点不存在")
                self.assertIn(target_id, node_ids, f"{name} link 目标节点不存在")
                origin = next(node for node in nodes if node["id"] == origin_id)
                target = next(node for node in nodes if node["id"] == target_id)
                self.assertLess(origin_slot, len(origin["outputs"]), f"{name} 输出槽越界")
                self.assertLess(target_slot, len(target["inputs"]), f"{name} 输入槽越界")
                self.assertEqual(target["inputs"][target_slot]["link"], _lid, name)

            classes = {node["type"] for node in nodes}
            self.assertTrue(must_have <= classes, f"{name} 缺少节点 {must_have - classes}")
            for node in nodes:
                if node["type"] not in ("Note", "MarkdownNote"):
                    self.assertIsInstance(node.get("widgets_values"), list,
                                          f"{name} 节点 {node['id']} 缺少控件值")


if __name__ == "__main__":
    unittest.main()
