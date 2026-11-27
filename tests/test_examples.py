"""示例工作流的结构单测（不需要 ComfyUI，纯 JSON 校验）。

门禁点：
- 引用的节点 id 必须存在；
- 连线 [节点id, 输出槽] 必须指向真实节点；
- 每条连线至少带 2 个元素；
- 示例里必须出现我们的节点（防止改坏示例）。
"""

import json
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(REPO, "examples")


def load(name):
    with open(os.path.join(EXAMPLES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


class ExampleTest(unittest.TestCase):
    def _check(self, graph):
        self.assertIsInstance(graph, dict)
        for node_id, node in graph.items():
            self.assertIn("class_type", node, f"节点 {node_id} 缺少 class_type")
            for input_name, value in (node.get("inputs") or {}).items():
                # 连线是 [node_id, slot]；普通参数就是值。
                if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                    self.assertIn(str(value[0]), graph,
                                  f"{node_id}.{input_name} 连线指向不存在的节点 {value[0]}")

    def test_single(self):
        graph = load("m1_single_segment_api.json")
        self._check(graph)
        classes = {n["class_type"] for n in graph.values()}
        for expected in ("DirectorDeck_ModelLoader", "DirectorDeck_DirectorConfig",
                         "DirectorDeck_ScriptDesk", "DirectorDeck_DirectorTake",
                         "CreateVideo", "SaveVideo"):
            self.assertIn(expected, classes)

    def test_ref2va(self):
        graph = load("m1_ref2va_api.json")
        self._check(graph)
        classes = {n["class_type"] for n in graph.values()}
        for expected in ("DirectorDeck_AssetShelf", "DirectorDeck_SegmentBrief",
                         "LoadImage", "DirectorDeck_DirectorTake"):
            self.assertIn(expected, classes)
        # 参考生视频示例必须真的接了素材和 brief，否则测不到覆盖逻辑。
        take = next(n for n in graph.values()
                    if n["class_type"] == "DirectorDeck_DirectorTake")
        self.assertIn("assets", take["inputs"])
        self.assertIn("brief", take["inputs"])
        self.assertEqual(take["inputs"]["brief_policy"], "replace")

    def test_m2_chain(self):
        graph = load("m2_chain_api.json")
        self._check(graph)
        classes = {n["class_type"] for n in graph.values()}
        for expected in ("DirectorDeck_FramePlanner", "DirectorDeck_DirectorTake",
                         "DirectorDeck_FinalCut", "CreateVideo", "SaveVideo"):
            self.assertIn(expected, classes)
        takes = [n for n in graph.values() if n["class_type"] == "DirectorDeck_DirectorTake"]
        self.assertEqual(len(takes), 3)
        # 第 2/3 段必须接 previous_segment，且 continuity=guide_tail。
        chained = [n for n in takes if "previous_segment" in n["inputs"]]
        self.assertEqual(len(chained), 2)
        for node in chained:
            self.assertEqual(node["inputs"]["continuity"], "guide_tail")
            self.assertEqual(node["inputs"]["bundle_policy"], "inherit")
        cut = next(n for n in graph.values() if n["class_type"] == "DirectorDeck_FinalCut")
        for key in ("segment_3", "images_3", "audio_3"):
            self.assertIn(key, cut["inputs"])

    def test_m3_digital_human(self):
        graph = load("m3_digital_human_api.json")
        self._check(graph)
        classes = {n["class_type"] for n in graph.values()}
        for expected in ("LoadAudio", "DirectorDeck_VoiceLock",
                         "DirectorDeck_DirectorTake", "DirectorDeck_Refiner",
                         "CreateVideo", "SaveVideo"):
            self.assertIn(expected, classes)
        take = next(n for n in graph.values()
                    if n["class_type"] == "DirectorDeck_DirectorTake")
        self.assertIn("cast", take["inputs"])
        self.assertEqual(take["inputs"]["cast_policy"], "replace")
        refiner = next(n for n in graph.values()
                       if n["class_type"] == "DirectorDeck_Refiner")
        self.assertEqual(refiner["inputs"]["mode"], "latent_2nd")
        self.assertLessEqual(float(refiner["inputs"]["denoise"]), 0.5)


if __name__ == "__main__":
    unittest.main()
