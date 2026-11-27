# DirectorDeck 开发计划

> 完整背景见 [CONTRACTS.md](CONTRACTS.md)。本文件只保留可执行计划与已定决策。

## 已确认决策（2026-11-27）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 模型范围 | H3 优先；adapter 层隔离，后续可扩展 |
| D2 | 多段方式 | 节点 + 前端"添加下一段" + CLI 三件套；先把节点做稳 |
| D3 | 续写模式 | M2 先 RGB 尾帧（core AddGuide），M3 补 latent 尾帧（自定义张量节点） |
| D4 | 二采 | M3 先成片超分（SeedVR2 核心节点），再 H3 latent 二采 |
| D5 | 锁音 | 自研节点做真锁音（分路 noise_mask=0），M2 底座 / M3 数字人模式 |
| D6 | 前端 | M1 轻量 widget，M4 完整 web extension |
| D7 | 素材存储 | 复制到 `ComfyUI/input/DirectorDeck/<project>/`，类型里存相对路径 |
| D8 | 许可证 | AGPL-3.0；clean-room，不复制 GPL 参考实现代码 |
| **D9** | **段级覆盖默认** | **每段必须显式指定 policy**；默认 `unset`，未指定报错；前端"添加下一段"自动填 `inherit` |
| D10 | 素材 merge | **按 `@图片N` 槽位覆盖**（固定 9 槽） |
| D11 | 段级 config | 只允许安全子集；模型 bundle 只能链首 |

## 里程碑

| 阶段 | 交付 | 验收 |
|---|---|---|
| **M0**（✅ 完成） | 仓库骨架、CONTRACTS、core 纯函数（frames/policy/assets/script）、单测、CI | `python -m unittest discover -s tests` 全绿（56 用例） |
| **M1**（✅ 完成） | `adapters/h3.py`、节点（Loader/Config/AssetShelf/ScriptDesk/SegmentBrief/DirectorTake）、API 示例、真机验证 | 8189 实例：124 帧 / 5.16s / 640x352 / h264+AAC 出片；参考生视频示例同步验证 |
| **M2**（✅ 完成） | FramePlanner、接续写（尾帧+尾音 AddGuide）、SeamFixer（曝光匹配）、FinalCut（裁头+合并+manifest）、SegmentCache（抽卡记录） | 8189 实例 3 段链：396 帧 / 16.5s / 640x352；段边界亮度差 0.00141 与 0.00020（<0.01）；改第 2 段 seed 重跑 `execution_cached=["1","2","3","10"]`，只重跑 2/3 段（695s→406s） |
| **M3**（✅ 完成） | VoiceLock（音频 VAE 编码 → 替换音频流 → noise_mask=0 真锁）、AV latent 拆合层、Refiner（低 denoise 再来一遍 + 锁音）、音频时间窗口数学 | 8189 实例：`lock.applied=true`；源音频 vs 锁音输出包络相关 0.9709、频带一致；二采 124→124 帧、像素差 5.7、raw vs refined 音频相关 0.9946 |
| **M4**（✅ 完成） | 前端浮动面板（添加下一段/覆盖节点/重抽/段清单/i18n）、后端 JSON 路由、FinalCut 源音频无损混流 | `node --check` 通过；`/extensions` 收录前端 JS 且 200；路由返回真实段数据；锁音段成片 FLAC 与源 wav 样点相关 1.0 / 最大差 0.0 |
| M5 | 文档、4 个示例工作流、Comfy Registry 发布 | 一键安装 + 示例可跑 |

## 工程约定

- 节点 ID `DirectorDeck_*`；参数只追加；旧 ID 保留别名；`IS_CHANGED` 用 resolved 指纹。
- core 不 import ComfyUI；adapters 是唯一耦合点。
- 错误统一 `DirectorError(code, message)`，中文文案 + 错误码表（CONTRACTS §10）。
- 提交信息：`Add ...`, `Fix ...`, `Update ...`, `Refactor ...`。

## 风险

1. ComfyUI 版本耦合（H3 内核内部 API）→ adapter 隔离 + 真机回归。
2. 12G 显存 RGB 续写慢（实测 ~3.4×）→ M3 latent 续写。
3. 静态图无法循环 → D2 三件套。
4. 许可证合规 → clean-room。
5. 发布后兼容 → 参数追加 + 迁移脚本。
