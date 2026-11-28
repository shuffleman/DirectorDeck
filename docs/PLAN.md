# DirectorDeck 开发计划

> 完整背景见 [CONTRACTS.md](CONTRACTS.md)。本文件只保留可执行计划与已定决策。

## 已确认决策（2026-11-27）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 模型范围 | H3 优先；adapter 层隔离，后续可扩展 |
| D2 | 多段方式 | 节点 + 前端"添加下一段" + CLI 三件套；先把节点做稳 |
| D3 | 续写模式 | **两种都已实现**：M2 先 RGB 尾帧（core AddGuide）；0.2.1 补 `latent_tail`（直接搬上一段 latent 尾部 token + mask=0，更快） |
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
| **M5**（✅ 完成） | 6 个 UI 画布工作流（round-trip 校验）、docs/INSTALL.md、docs/UI_WORKFLOWS.md、CHANGELOG、Registry 元数据与 publish workflow | 全部工作流 API round-trip PASS；安装文档可照做；`node --check` / 单测通过；发布需用户提供 Registry token |
| **0.2.1**（✅） | latent 尾帧续写（`continuity=latent_tail`） | 两段 260 帧 / 10.83s；边界亮度差 0.00378；同规格段比 RGB 引导快约 1/3 |
| **0.2.2**（✅） | 画面级抽卡缓存（`cache_mode` + mp4/npz 磁盘缓存） | 冷跑 346.7s → 重启后全命中 3.6s（约 96×）；画面平均像素差 2.76；约 8MB/段 |
| **0.2.3**（✅） | 多角色锁音自动 ducking / 混音规则（auto_duck/priority/sum + 每路增益/优先级 + 平滑包络 + 限幅） | 应用层 priority 实测 -7.99dB（目标 -8）、sum 0.00dB；真机 M6 两路锁音成片验证 |
| **0.2.4**（✅） | 跨段 ducking 一致性（增益状态/尾音上下文 + 缓存持久化）+ FinalCut 等功率交叉淡化 + 前端混音快捷控件 | 第二段开头继承 B=0.398（对比重置低 5.68dB）；M7 真机 crossfade 对比；`node --check` 通过 |
| **0.2.5**（✅） | 本地 TTS（Breeze-TTS-2）接入锁音示例；锁音缓存指纹加入音频内容哈希（cache_schema=2） | M8 真机两路 TTS 成片；拟合 corr=0.999；重叠 ducking 中位 -7.0dB/p10 -7.85dB；TTS 24k→32k 自动重采样 |
| **0.3.0**（✅） | TTS 台词表节点（台词表→多角色 TTS→CAST）；M8/M9 画布工作流 | M9 真机 2 角色/124 帧；单角色段 corr=1.000，ducking 中位 -7.30dB/p10 -7.87dB；缓存重跑 Take 0.41s；9 个 UI 工作流 round-trip 全 PASS |
| **0.3.1**（✅） | 文档整理：README 只保留功能与使用方式；工程约定/目录/开发验证移到 docs/ENGINEERING.md | README 无开发内容；验证数据统一在 ENGINEERING + CHANGELOG |
| **0.4.0**（✅） | 台词表自动排期：auto_start / auto_split / pause_ms / chars_per_second + total_seconds 输出；M10 画布工作流 | M10 真机：自动分段 3 句、自动排期起点与摘要一致；10 个 UI 工作流 round-trip 全 PASS |
| **0.5.0**（✅） | 台词超长提醒（max_seconds + segment_count/plan，不缩句）+ 多段复用同一份 CAST 自动衔接；M11 画布工作流 | M11 真机：超长提醒/分段计划；两段 latent 衔接成片，跨段 CAST 切片连续；11 个 UI 工作流全 PASS |
| **0.6.0**（✅） | 编剧台 ScriptSmith：skill 加载 + 小说转剧本（本地/远程 OpenAI 兼容 LLM、输出语言、素材/角色对齐、script + voice_lines 输出）；M12 画布；import_skill / mock_llm 工具 | M12 真机：mock LLM → 剧本 → TTS → 锁音成片；12 个 UI 工作流全 PASS；140 单测 |
| **0.7.0**（✅） | 预置漫剧老李 Skill 全集（11 个 skill + references）与 H3 V6 提示词模板到 `skills/`；skill 扫描支持套件子目录 | 13 项 skill 可选；V6 可解析；146 单测 |
| **0.8.0**（✅） | **移除剧本生成与 skill/LLM**；新增外部剧本导入 + 角色/场景/音频自动匹配（ScriptImport）；前端一键建生成器/合并输出；M13 画布 | M13 真机导入两段剧本链；匹配报告；11 个 UI 工作流全 PASS |
| **0.8.1**（✅） | 节点参数显示名中文化（前端 label 层，API 字段名保持英文） | 14 个节点控件/插头/输出中文显示；JS `node --check` 通过；138 单测 |
| **0.8.2**（✅） | 全局配置分辨率预设（480p/720p/768p/1080p × 横屏/竖屏/方形）+ 前端宽高自动同步；`core/frames.resolve_canvas` 纯函数 + 单测 | 480p 真机 864×480 单段出片；11 个 UI 工作流 PASS；145 单测 |
| **0.8.3**（✅） | 明确冲突规则：分辨率预设优先；`canvas_source/canvas_ignored` 落盘；前端锁宽高 + 提示；段级 override 禁止分辨率 | 480p 冲突数据仍出 864×480；JS check；145 单测 |
| **0.9.0**（✅） | FinalCut 无限段：动态输入 `segment_5...` + 前端“+1段输入”/“补全合并输出”自动加；manifest `segment_count` | M14 真机 5 段 620 帧/25.83s；146 单测 |
| **0.10.0**（✅） | 生成器节点视频预览 + “再次生成本段”按钮；合并器手动合并门闩（merge_mode/merge_token + DOM 按钮） | M14 手动模式不出成片、token=1 后 10.2s 出 620 帧成片；预览 mp4 带 AAC；11 个 UI 工作流 PASS |
| **0.11.0**（✅） | 新增二次处理成片节点：潜空间二采 + 二采 LoRA + RelayVSR 2x + 目标分辨率 + 手动“生成最终视频”并直存 mp4；修复预览黑屏（*255） | 真机 1 段 480p：二采+LoRA+Relay 155.3s 出 1728×960 非黑屏成片；147 单测 |
| **0.11.1**（✅） | 输入/输出插头显示名也中文化（`beforeRegisterNodeDef` display_name + addInput/addOutput label）；修复节点 DOM 按钮不显示/被拉伸 | 无头浏览器新建+加载 M13 工作流验证全部中文；无漏网插头；147 单测 |
| **0.12.0**（✅） | 完整工作流 M16：外部剧本 + 素材自动匹配 → 两段生成 → 手动合并 → 二次处理成片（二采+RelayVSR），画布一键打开 | UI round-trip PASS；148 单测；真机跑通整条链 |

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
