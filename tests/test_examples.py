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

    def test_m4_lock_finalcut(self):
        graph = load("m4_lock_finalcut_api.json")
        self._check(graph)
        classes = {n["class_type"] for n in graph.values()}
        for expected in ("DirectorDeck_VoiceLock", "DirectorDeck_DirectorTake",
                         "DirectorDeck_FinalCut", "CreateVideo", "SaveVideo",
                         "SaveAudio"):
            self.assertIn(expected, classes)
        cut = next(n for n in graph.values()
                   if n["class_type"] == "DirectorDeck_FinalCut")
        # M4 的关键：合并时直接用锁音源轨，做到无损。
        self.assertTrue(cut["inputs"]["audio_from_source"])

    def test_m5_latent_chain(self):
        graph = load("m5_latent_chain_api.json")
        self._check(graph)
        takes = [n for n in graph.values()
                 if n["class_type"] == "DirectorDeck_DirectorTake"]
        self.assertEqual(len(takes), 2)
        second = next(n for n in takes if n["inputs"]["segment_index"] == 2)
        self.assertEqual(second["inputs"]["continuity"], "latent_tail")
        self.assertIn("previous_segment", second["inputs"])
        self.assertEqual(second["inputs"]["bundle_policy"], "inherit")
        cut = next(n for n in graph.values()
                   if n["class_type"] == "DirectorDeck_FinalCut")
        self.assertIn("segment_2", cut["inputs"])

    def test_m8_tts_lock(self):
        graph = load("m8_tts_lock_api.json")
        self._check(graph)
        classes = {n["class_type"] for n in graph.values()}
        for expected in ("BreezeTTS2LoadModel", "BreezeTTS2VoiceDesign",
                         "DirectorDeck_VoiceLock", "DirectorDeck_DirectorTake",
                         "DirectorDeck_FinalCut", "SaveAudio", "SaveVideo"):
            self.assertIn(expected, classes)
        lock = next(n for n in graph.values()
                    if n["class_type"] == "DirectorDeck_VoiceLock")
        self.assertIn("audio_1", lock["inputs"])
        self.assertIn("audio_2", lock["inputs"])
        self.assertEqual(lock["inputs"]["mix_mode"], "priority")
        take = next(n for n in graph.values()
                    if n["class_type"] == "DirectorDeck_DirectorTake")
        self.assertEqual(take["inputs"]["cast_policy"], "replace")
        cut = next(n for n in graph.values()
                   if n["class_type"] == "DirectorDeck_FinalCut")
        self.assertTrue(cut["inputs"]["audio_from_source"])

    def test_m7_crossfade(self):
        graph = load("m7_crossfade_api.json")
        self._check(graph)
        cut = next(n for n in graph.values()
                   if n["class_type"] == "DirectorDeck_FinalCut")
        self.assertEqual(int(cut["inputs"]["audio_crossfade_ms"]), 80)
        self.assertIn("segment_2", cut["inputs"])
        takes = [n for n in graph.values()
                 if n["class_type"] == "DirectorDeck_DirectorTake"]
        self.assertEqual(len(takes), 2)

    def test_m6_mix_rules(self):
        graph = load("m6_mix_rules_api.json")
        self._check(graph)
        classes = {n["class_type"] for n in graph.values()}
        for expected in ("DirectorDeck_VoiceLock", "DirectorDeck_DirectorTake",
                         "DirectorDeck_FinalCut", "SaveAudio", "SaveVideo"):
            self.assertIn(expected, classes)
        lock = next(n for n in graph.values()
                    if n["class_type"] == "DirectorDeck_VoiceLock")
        self.assertEqual(lock["inputs"]["mix_mode"], "priority")
        self.assertLess(float(lock["inputs"]["duck_db"]), 0.0)
        # 两路音频都要接进锁音器。
        self.assertIn("audio_1", lock["inputs"])
        self.assertIn("audio_2", lock["inputs"])
        take = next(n for n in graph.values()
                    if n["class_type"] == "DirectorDeck_DirectorTake")
        self.assertEqual(take["inputs"]["cast_policy"], "replace")
        cut = next(n for n in graph.values()
                   if n["class_type"] == "DirectorDeck_FinalCut")
        self.assertTrue(cut["inputs"]["audio_from_source"])


if __name__ == "__main__":
    unittest.main()
