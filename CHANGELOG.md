# Changelog

## 0.8.1 — 节点参数显示名中文化（2026-11-28）

### 变更
- 前端扩展新增**参数中文显示层**：DirectorDeck 全部 14 个节点的控件和插头在画布上显示中文
  （如“段号 / 模型策略 / 素材策略 / 抽卡缓存 / 自动匹配素材 / 源音轨无损”），
  输出口也显示中文（“段数据 / 画面 / 音轨 / 角色音色表”）。
- **API 字段名保持英文不变**，旧工作流、示例 JSON、外部脚本完全兼容；
  下拉选项值（`inherit` / `auto_duck` 等）保持英文，tooltip 用中文解释。
- 新增节点（ScriptImport）的参数名一并纳入中文显示；面板自动创建的节点也会立即中文化。

## 0.8.0 — 去掉剧本生成，改为外部剧本导入 + 素材自动匹配 + 一键建生成器（2026-11-28）

### 移除
- **彻底移除剧本生成相关功能**：`DirectorDeck_ScriptSmith` 编剧台、skill 加载器
  （`adapters/skill.py`、`skills/` 预置的漫剧老李全集与 V6 模板）、LLM 适配
  （`adapters/llm.py`）、`tools/import_skill.py` / `tools/preset_bundled_skills.py` /
  `tools/mock_llm.py`、M12 画布与示例、对应单测与文档。

### 新增
- **`DirectorDeck_ScriptImport`（剧本导入）**：外部写好的剧本直接粘进来，
  `format` 支持自动识别 / DirectorDeck 文本 / JSON 剧本 / H3 V6；
- **素材自动匹配**（`core/asset_match.py`，纯函数 + 单测）：
  - 角色名 → 素材图片槽（名字/用途相似度，兜底按顺序）；
  - 段落场景关键词 → 背景/场景槽；
  - 角色名 → 角色音色库音频槽（没接角色库就给顺序建议）；
  - 匹配结果写回每段 `@图片N`，输出可核对的 `mapping` 对照表；
- **前端一键建链**：选中「剧本导入」+ 画布上放一个「视频生成器」当模板，面板
  **按剧本建生成器** 按 `segment_count` 自动创建 N 段并接好（复制模型/配置/素材/音色接线、
  串 `previous_segment`、后续段 latent 续写）；**补全合并输出** 自动建
  FinalCut + CreateVideo + SaveVideo；
- 新增画布工作流 `DirectorDeck_M13_剧本导入.json` 与 API 示例 `examples/m13_import_api.json`；
- 新增错误码 `DD-E061`（剧本导入解析失败）。

### 验证（8189 真机，M13）
- 外部剧本 **2 段**（10.0s），素材库 2 张图 → 角色自动匹配 **2 个**（顺序兜底），
  音频槽建议 2 个；场景 0 段（2 个槽被角色占用）。
- 第 1 段 prompt 绑定 `<Picture 1> <Picture 2>`，第 2 段按角色只绑定 `<Picture 1>`；
- 两段链出片 **260 帧 / 10.83s**（124 + 158 帧，latent 衔接）。

## 0.7.0 — 预置漫剧老李 Skill 全集 + V6 提示词模板（2026-11-28）

### 新增
- **预置「漫剧老李 AIGC 全流程 Skill」全集**（MIT，V8.2.0-SLIM）到 `skills/manju_laoli/`：
  - 11 个 skill：`short-drama-director` + `sd-decision/recon/script/asset/storyboard/combat/xuanhuan/real/feed/qc-engine`；
  - 每个 skill 带 `SKILL.md` + `references/`（共 143 个文件，约 2.7MB；不含 scripts/assets/CI）；
  - 附带 `LICENSE`、`README.md`、`NOTICE.md`（来源、commit、许可以及上下文大小建议）。
- **预置「MiniMax H3 分段无限视频生成提示词模板 V6」**到 `skills/minimax_h3_v6/SKILL.md`
  （含 `NOTICE.md` 说明来源与用法）。
- `skills/` 扫描支持“套件子目录”：下拉框里显示 `manju_laoli/<子技能>` 与 `minimax_h3_v6`；
  编剧台可直接选，无需先手动导入。
- 新增维护脚本 `tools/preset_bundled_skills.py`：上游更新后可重新同步这两个 skill 源。

### 验证
- 启动后编剧台 skill 下拉共 **13 项**（内置 1 + 漫剧老李 11 + V6 1）。
- 加载检查：V6 全文 10,437 字符可解析（示例段头转回 6 段剧本）；
  `short-drama-director` 主控按默认 6 万字符上限加载并标记截断；其余子技能 3k~17k 字符。
- 单测新增 `test_bundled_skills.py`，总计 **146 个全绿**。

## 0.6.0 — 编剧台：Skill + 小说 → 剧本 → TTS → 锁音（2026-11-28）

### 新增
- **`DirectorDeck_ScriptSmith`（编剧台）**：一个节点完成
  「加载 skill → 读小说 → 调 LLM 写剧本 → 对齐素材/角色 → 出可生成的数据」：
  - `skill` 下拉框读取 `skills/` 目录（支持目录式 SKILL.md + references，也支持单文件 .md 模板），
    可用 `tools/import_skill.py` 导入外部 skill；
  - 输入小说/梗概，可选接**素材库**（9 图槽）和**角色/音色库**，提示词里只允许模型使用真实存在的
    `@图片N`、角色名和音频槽；
  - **本地/远程 LLM 都走 OpenAI 兼容协议**：本地 LM Studio/Ollama/vLLM，远程 OpenAI/DeepSeek 等；
    `base_url`/`model` 可填，model 留空自动取 `/models` 第一个；API Key 只从环境变量读；
  - **输出语言**可选：中文 / English / 日本語 / 한국어 / 跟随原文；
  - 输出 6 路：`script`（直接接视频生成器）、`script_text`（可读剧本，可直接粘剧本加载器）、
    `voice_lines`（直接接 TTS 台词表）、`character_map`（角色→图片槽/音频槽/音色）、`summary`、`raw_text`；
  - 支持两种输出格式：DirectorDeck 剧本（JSON，默认）/ H3 V6 分段提示词（自动转换回 DirectorDeck 剧本）。
- 新增工具：`tools/import_skill.py`（导入 skill）、`tools/mock_llm.py`（OpenAI 兼容 mock，便于联调）。
- 新增画布工作流 `DirectorDeck_M12_编剧台.json` 与 API 示例 `examples/m12_scriptsmith_api.json`。
- 错误码：`DD-E060`（LLM 调用失败）/ `DD-E061`（剧本解析失败）/ `DD-E062`（skill 加载失败）。
- 修复 UI 工作流生成器对“控件转输入”的取值错位（M12 的 voice_lines 直连 TTS 台词表）。

### 验证（8189 真机，M12）
- 用本地 mock LLM（`tools/mock_llm.py`）跑通：小说 → 编剧台 → 剧本/台词表 → TTS → 锁音 → H3。
- 生成剧本 **? 段**、**? 句台词**；视频生成器收到的 prompt 包含 **?**（`@图片N` 正确绑定）。
- 锁音 roles=**?**；成片 **? 帧 / ?s**。

## 0.5.0 — 台词超长提醒 + 多片段自动衔接（不缩句）（2026-11-28）

### 新增
- TTSBooth 新增 `max_seconds`（单段时长上限，0=不检查）：
  - 自动排期总长超过上限时**只提醒、不缩句、不加速、不裁台词**；
  - 摘要里标出 `⚠ 超长 X.XXs`，控制台打印超长提醒；
  - 新增输出 **`segment_count`**（需要几段）和 **`plan`**（每段建议时间窗 + 多段接线说明）。
- **多片段自动衔接**：同一份 CAST 的音轨是整条时间轴的，多段链里直接复用——
  第 1 段 `cast_policy=replace`，后续段 `cast_policy=inherit` + `previous_segment`，
  每段生成器按自己的时间窗口自动切片，声音天然连续（配合 `continuity=latent_tail` 更快）。
- 新增画布工作流 `DirectorDeck_M11_超长两段衔接.json` 与 API 示例 `examples/m11_tts_chain_api.json`。
- `core/audio.py` 新增纯函数 `plan_segments(total, max_seconds)`（只算分段窗口，不动台词），带单测。

### 修复
- **跨段限幅连续性**：上一段的限幅系数通过混音上下文继承给下一段，避免“上一段被压、
  下一段没超限就恢复原响度”的段边界电平跳变。进程内验证：段 1 限幅 0.886，
  段 2 延续 0.886（边界电平 -0.05dB）vs 重置 1.000（+1.01dB）；缓存格式升到 `cache_schema=3`。

### 兼容性
- 原有台词表、`@起始秒`、自动排期用法全部不变；新增参数/输出只追加。

### 验证（8189 真机，M11）
- M11 台词表自动排期后总长 **6.91s**（4 句），超过 5s 段长上限 → `segment_count=2`，
  计划 `0.00–5.00 / 5.00–6.91`；只提醒，**没有缩句/加速/裁台词**。
- 两段 latent 衔接出片：成片 **260 帧 / 10.83s**；FinalCut 源音轨在真实拼接点（5.175s）
  **样本级连续（jump/step=0.00）**；第二段音频与 CAST 的 B 音轨切片相关 **1.0000**
  （跨段复用同一份 cast）。
- 第二段段元数据 `lock.applied=true`、窗口 `[4.25, 10.833]s`（同一份 cast 继续锁音）。

## 0.4.0 — 台词表自动排期（按句估时长/自动分段）（2026-11-28）

### 新增
- **台词表可以省略起始秒**：节点新增 `auto_start`（默认开）——没写 `@秒` 的句子按
  “上一句结束 + `pause_ms`”自动往后排；写死 `@秒` 的句子仍按写死的排，后面的自动句接着它继续。
- **`auto_split`（默认开）**：一句里出现多个句号/问号/感叹号/分号时自动拆成多句分别生成、分别排期；
  `pause_ms` 控制句间停顿（默认 300ms）。
- **`chars_per_second`（默认 4.5）**：生成前按字数预估语速，摘要里给出“预估总长 vs 实际总长”。
- 新增输出 **`total_seconds`**（FLOAT）：自动排期后的实际总时长，方便回填全局配置的段时长。
- 新增画布工作流 `DirectorDeck_M10_台词自动排期.json` 与 API 示例 `examples/m10_tts_auto_api.json`。
- `core/audio.py` 新增三个纯函数：`split_sentences` / `estimate_speech_seconds` / `schedule_starts`，带单测。

### 兼容性
- TTSBooth 原有 `@起始秒` 用法不变；M9 显式排期示例继续可用。
- 节点参数只追加，旧工作流/API 无需改接线；新增输出排在第 6 路。

### 验证（8189 真机，M10）
- 台词表 2 行、自动分段后 **3 句**；排期 `女主@0.00+1.44s / 女主@1.69+1.76s / 男主@3.70+1.60s`；总长 **5.30s**（预估 3.99s）。
- 成片 124 帧 / 5.17s（总长 5.30s 比段窗口多 0.13s，末尾被截；可用 `total_seconds` 把段秒数调大）；音频起始点检测与摘要排期误差 ≤20ms。
- 固定种子重跑 Take **0.34s 命中缓存**；整条 prompt 22.5s（壁钟 25.1s，仅重跑 3 句 TTS）。

## 0.3.1 — 文档整理：README 只保留功能与使用方式（2026-11-28）

### 变更
- **README 不再放工程约定/开发内容**：移除“状态 / 设计要点 / 目录 / 工程约定 / 本地真机验证命令与数据”，
  README 只保留功能、节点、安装/快速开始和各功能使用方式，并附文档索引。
- 新增 `docs/ENGINEERING.md`：工程约定、仓库结构、本地开发/验证命令、历史真机验证数据、发布与 CI 说明。
- 真机验证数据统一放 `docs/ENGINEERING.md` 与 `CHANGELOG.md`，不再出现在 README。

## 0.3.0 — 台词表一键配音节点 + M8/M9 画布工作流（2026-11-28）

### 新增
- **`DirectorDeck_TTSBooth`（TTS 台词表）**：一张台词表 → 多角色 TTS → 直接可锁音的 CAST。
  - 每行格式：`角色 @起始秒 | 音色描述 | 台词`；
  - 内部自动调 Breeze-TTS-2 的 `VoiceDesign` 逐条生成（种子 = `seed + 行号`，可复现）；
  - 同一角色的多条台词按起始秒拼进同一条音轨；角色第一次出现的顺序 = ducking 优先级；
  - 输出 `cast` + 3 路可试听/保存的 `audio_1..3` + 文字摘要；
  - 可选依赖：没装 ComfyUI-Breeze-TTS-2 时报 `DD-E050`，不影响 DirectorDeck 其他节点。
- **M8 画布工作流**：`examples/ui/DirectorDeck_M8_TTS锁音.json`（两个 VoiceDesign → 锁音 → H3）。
- **M9 画布工作流**：`examples/ui/DirectorDeck_M9_台词表配音.json`（台词表节点 → 锁音 → H3）。
- API 示例：`examples/m9_tts_booth_api.json`；UI 工作流总数 9 个，全部 round-trip PASS。

### 修复
- Breeze 适配层调用节点方法返回 tuple，之前直接当 dict 用导致 `TypeError`；现在解包第一个 AUDIO。

### 验证（8189 真机）
- M9 第一次：2 条台词 → 女主音轨 2.32s、男主音轨 4.08s（起点 1.2s），H3 生成 **124 帧 / 5.17s**；
  - 成片音频与两路角色音轨拟合：A-only **corr=1.000**、B-only **corr=1.000**（g≈1.41，声道测量常数）；
  - 重叠区 ducking：中位 **-7.30dB**、最安静 10% 窗口 **-7.87dB**（目标 -8dB）。
- M9 重启后重跑：TTS 固定种子输出一致，Take **0.41s 命中缓存**；整条 prompt **43.9s**（仅重跑 TTS，无 H3 采样）。

## 0.2.5 — 本地 TTS（Breeze-TTS-2）接入锁音（2026-11-27）

### 新增
- 提供 **M8 本地 TTS 示例**：`examples/m8_tts_lock_api.json`
  - `BreezeTTS2LoadModel`（int8 hybrid）→ 两个 `BreezeTTS2VoiceDesign`（女主/男主台词与音色描述）
    → `DirectorDeck_VoiceLock`（按时间轴放置 + priority ducking）→ `Take` 真锁音生成
    → `FinalCut(audio_from_source=True)` 直接混源音轨 → `SaveAudio/SaveVideo`。
  - 同时保存两路 TTS 原声（`M8_tts_a/M8_tts_b`），方便核对时间轴/ducking。
- **锁音缓存指纹加入“音频内容哈希”**：`Take` 现在对每路实际音频波形算哈希参与指纹。
  TTS 每次生成的声音可能不同；此前只按角色名/时间轴缓存会错误复用上一次的声音。
  缓存格式随之升到 `cache_schema=2`（旧缓存自动失效）。

### 验证
- 真机 8189：两段 TTS（2.48s / 2.80s）分别放在 0s / 1.2s，H3 生成 124 帧（5.17s）锁音成片；
  成片音频与 TTS 原声的最小二乘拟合 **corr=0.999**，系数 `{A:1.414, B:0.678}`；
  A 单独段系数 1.414、B 单独段 1.407（A 停后 B 恢复满音量）。
- 重叠段 B/A 的 ducking 比例：中位 **-7.0dB**，最安静 10% 窗口 **-7.85dB**（目标 -8dB；
  窗口包含起音/释放段时会偏高）。
- TTS 输出 24kHz 单声道，VoiceLock 内部自动重采样到音频 VAE 的 32kHz，无需手转。
- **缓存可复现**：固定 TTS 种子后两次生成的原声 SHA1 完全一致（`be475e5d08d1`/`2952c99570b5`），
  重启 ComfyUI 再跑 m8 时 Take 命中磁盘缓存（段内 **0.34s**），整条 prompt **22.9s**
  （其中两路 TTS 重新合成约 15s，没有 H3 采样）。

## 0.2.4 — 跨段 ducking 一致性 + 混音快捷控件（2026-11-27）

### 新增
- **跨段 ducking 一致性**：上一段的混音上下文（每角色结尾增益、尾音、限幅系数）会传给下一段，
  `mix_gains(initial_gains=...)` 从上一段结尾的增益接着算——段边界不会“弹回 1.0”再重新压。
  上下文随段存进运行期仓库，并写进磁盘缓存（npz 的 `mix_tail/mix_limiter` + json 的 `mix_gain_state`），
  缓存命中时也保持连续；段元数据里 `lock.mix_continuity=true` 可追溯。
- **FinalCut `audio_crossfade_ms`**：段边界等功率交叉淡化，用当前段衔接头的重叠区与上一段尾部混合，
  **总时长不变**；对生成音频（分段各自生成）尤其有用，对锁音源轨是无损幂等操作。
- **前端混音快捷控件**：导演台面板新增「切换混音模式」「duck -2dB」「duck +2dB」三个按钮，
  自动定位选中生成器所接的 VoiceLock（或直接选中的 VoiceLock），改完立即生效并 toast 提示。

### 验证
- 跨段连续性（`tools/mix_rules_check.py`，两段同时说话）：第一段结尾增益 `{A:1.0, B:0.398}`，
  第二段开头 B 的增益仍是 **0.398**；对比“重置上下文”的第二段，开头 30ms B 能量 **低 5.68dB**
  （写明确实继承、没有弹回 1.0）。
- FinalCut 交叉淡化真机（M7 两段链，260 帧 / 10.83s，同一批缓存段只重跑 FinalCut）：
  - `audio_crossfade_ms=0`（硬接）：边界跳变 **0.05384**（jump/step_std **2.23**），
    边界前后 50ms RMS 0.327→0.238（明显掉档）；
  - `audio_crossfade_ms=80`：边界跳变 **0.01277**（jump/step_std **0.57**，已低于正常采样步进），
    前后 RMS 0.1864→0.1965（无掉档）。
  - 两次 FinalCut 都直接复用缓存段，执行耗时 2–4 秒。

### 其他
- 前端 `node --check` 通过；画布工作流重新生成后仍全部 PASS；单测 102 个。

## 0.2.3 — 多角色锁音自动 ducking / 混音规则（2026-11-27）

### 新增
- **锁音器支持多角色混音规则**：`mix_mode` = `auto_duck`（每帧最响的角色不被压，其他同时发言者降 `duck_db`）/
  `priority`（按角色优先级决定谁不被压）/ `sum`（只叠加）。
- `duck_db`（默认 -8dB）、`attack_ms`（默认 60ms，压下去多快）、`release_ms`（默认 200ms，恢复多快）；
  增益包络在 `core/audio.mix_gains` 里算（纯函数、可单测），适配层按采样点线性插值应用。
- **角色行扩展**：`名字: 音频槽, 起始秒, 增益dB, 优先级`（后两个可省略）；
  每路可单独调音量，优先级用于 `priority` 模式。
- 素材切入/切出加 8ms 淡入淡出（防“咔哒”）；混音后做全局限幅（防叠加削波）。
- 混音规则/增益/优先级会写进 cast 并参与缓存指纹：改了 ducking 参数会自动重新生成，不会误用旧音频。
- 验证工具：`tools/mix_rules_check.py`（合成 440/880Hz 双角色，直接量 ducking 效果，不需要 GPU）。

### 验证
- 应用层（`tools/mix_rules_check.py`）：priority 模式 B 重叠/独唱 **-7.99dB**（目标 -8dB），A 保持 **0.00dB**；
  sum 模式 **0.00dB**；auto_duck 在 B 更响时把 A 压 **-8.00dB**；单路 -6dB 增益实测 **-6.00dB**；峰值 0.508 无限幅。
- 真机 M6（8189，两路合成音频锁音 + FinalCut 源音频无损）：
  B 重叠/独唱 **-7.99dB**（目标 -8dB），A **0.00dB**；成片 124 帧 / 5.17s；峰值 0.711（未触限幅）；`lock.roles=[A,B]`、`mix.mode=priority`、`duck_db=-8`。

## 0.2.2 — 画面级抽卡缓存（2026-11-27）

### 新增
- **抽卡缓存升级为“画面级秒复用”**：生成器新增 `cache_mode` 控件
  （`auto`=命中就复用 / `off`=不读不写 / `reroll`=强制重抽并覆盖）。
  缓存内容：画面 mp4（h264 CRF 12）+ 音轨/latent/锁音源轨 npz + 段元数据 json，
  落在 `output/DirectorDeck/cache/segments/seg_<指纹>.{mp4,npz,json}`。
- **命中缓存时完全跳过条件构造、采样、VAE 解码**，直接把画面/音轨读回并补齐运行期仓库，
  所以续写/锁音/无损混流这些下游能力在缓存命中时依然可用。
- **指纹**（`core/cache.py`，纯函数）：resolved 哈希 + 提示词 + 模式 + 画布 + 帧数 +
  解析后的种子 + 采样参数 + 引导来源 + 锁音签名；`cache_schema` 升级会自动让旧缓存失效。
- 种子现在是“先定后采样”：`seed=0` 时在节点内先随机出一个固定种子再算指纹，
  否则每次随机种子都会让缓存永远命中不了。

### 验证
- 冷缓存首次运行：**346.7s**（两段：124 + 158 帧，写缓存 ~4MB mp4/段）。
- 重启 ComfyUI 清掉节点缓存后再跑同一工作流：两段均 **缓存命中**（日志 `命中缓存`），
  整条 prompt **3.6s** 完成（墙钟 5.1s）；对比冷缓存首次运行 346.7s，约 **96×**。
- 缓存帧读回后与首次生成画面**平均像素差 2.76**（0–255 口径，仅 h264 CRF 12 重编码误差）；每段缓存约 8MB（mp4 1.5–2.4MB + npz 4.4–5.6MB）。

## 0.2.1 — latent 尾帧续写（2026-11-27）

### 新增
- **`continuity=latent_tail`**：第 2 段起可以直接搬上一段 latent 的尾部 token 到新 latent 开头，
  并用 `noise_mask=0` 钉住——省掉 RGB 尾帧“解码→再编码”的绕路，更快、更接近原生续写。
- 纯函数 `core.frames` 增加 H3 时间 token 数学（`FRAME_PER_TOKEN` / 边界 / 尾 token 边界），
  带 5 个单测（158 帧/head=22 时正好搬 7 个 token、遮 22 帧）。
- 示例：`examples/m5_latent_chain_api.json`（两段链，第 2 段用 latent_tail）。

### 验证
- 真机两段链（8189，RTX 5070 12G）：**260 帧 / 10.83s**；第 2 段元数据
  `guide.mode=latent_tail`、`handoff.tokens_copied=7`、`token_start=30`、`masked_frames=22`；
  段边界亮度差 **0.00378**（阈值 <0.01）。
- 第 2 段耗时 **180.7s**（采样 17.1s/it），对比 M2 的 RGB 尾帧引导同规格段约 266s/25.5s/it，
  约 **快 1/3**；且不再有 RGB 引导带来的额外编译开销。

### 其他
- 文档更新：CONTRACTS 的 continuity 枚举、README/PLAN/UI_WORKFLOWS 的 latent 模式说明。

## 0.2.0 — M5 发布准备（2026-11-27）

首个可分发版本：M0–M5 全部落地，含 12 个节点、前端面板、5 个画布工作流。

### 新增
- **M0 契约与骨架**：`docs/CONTRACTS.md`（字段级契约 + 错误码）、core 纯函数
  （帧数学 / policy 解析 / 剧本解析 / 素材槽位 / 音频窗口）、76+ 单测、CI。
- **M1 单段闭环**：模型加载器、全局配置、资产管理器、剧本加载器、段级剧本、视频生成器；
  H3 适配层（加载/条件/采样/解码）；API 示例。
- **M2 链式多段**：帧计划器、尾帧+尾音 AddGuide 续写、接缝曝光修正、多段合并、
  抽卡缓存；3 段 16.5s 真机出片，接缝亮度差 <0.01，抽卡缓存复用。
- **M3 锁音+二采**：AV latent 拆合手术、逐流 noise_mask=0 真锁音、二采（低 denoise 再采样）。
- **M4 前端与无损音频**：浮动面板（添加下一段/覆盖节点/重抽/段清单/i18n）、
  后端 JSON 路由、FinalCut `audio_from_source` 源音频无损混流（FLAC 样点相关 1.0）。
- **M5 发布**：5 个 UI 画布工作流（round-trip 校验通过）、安装/工作流文档、
  Registry 元数据与发布 workflow。

### 已知限制
- 续写引导为 RGB 尾帧模式（latent 尾帧续写尚未实现，见 `docs/PLAN.md` D3）。
- 抽卡缓存为 ComfyUI 节点级缓存 + 元数据记录，尚无“秒级画面复用”。
- 数字人锁音保证内容/口型对应，逐样点无损需 FinalCut `audio_from_source`。
- 前端面板为浮动 DOM 面板，不是深度集成到侧边栏。

### 验证数据（本机 8189 独立实例，RTX 5070 12G）
- M1 单段：124 帧 / 5.17s / 640x352 / h264+AAC。
- M2 三段：396 帧 / 16.5s；段边界亮度差 0.00141 / 0.00020；抽卡重跑 695s→406s。
- M3 锁音：`lock.applied=true`；源音频 vs 锁音输出包络相关 0.9709；二采像素差 5.7、音频相关 0.9946。
- M4 无损：锁音段成片 FLAC 与源 wav 样点相关 1.0、最大差 0.0。

## 0.1.0 — 内部开发版（M0–M4）
仅本地验证，未发布。
