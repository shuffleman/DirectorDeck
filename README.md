# DirectorDeck

ComfyUI 节点库：**AI 短剧导演台**。把「模型 + 素材 + 剧本 + 音色」组织成链式分段生成流水线：
每段可以接入自己的素材/锁音/剧本覆盖，也可以沿用上一段；最后二采、合并成片。

> 底座：ComfyUI 0.46+ / MiniMax H3（`comfy_extras.nodes_minimax_h3`），适配层预留其它模型。

## 功能

- **链式分段生成**：帧计划自动按 17k+5 对齐全链；续写支持 RGB 尾帧输入或直接搬上一段 latent 尾 token。
- **每段显式覆盖策略**：素材（`@图片N` 九宫格）、段级剧本、音色、配置都支持 `inherit/overwrite`，
  默认必选，避免“以为继承了其实没有”。
- **数字人锁音**：给定角色配音，音频流以 `noise_mask=0` 锁进 AV latent，模型只生成画面；
  成片可选用源音轨无损混流。
- **多角色混音**：`auto_duck` / `priority` / `sum` 三种规则，自动 ducking、每角色增益/优先级、
  段边界交叉淡化、跨段增益/限幅连续性。
- **抽卡缓存**：画面级 mp4 + 音轨/latent npz 磁盘缓存，命中即跳过采样；TTS 音频内容参与指纹。
- **本地 TTS**：可接 ComfyUI-Breeze-TTS-2；台词表节点一键多角色配音并直接输出可锁音的 CAST。
- **外部剧本导入**：自己写/外部生成的剧本（文本、JSON、H3 V6）粘进导入节点，
  自动匹配素材库的角色/场景/音频，并在面板一键生成整条视频生成链。
- **导演台面板**：加下一段、加覆盖、重抽、看段清单、切换混音/调 duck 电平。

## 节点

> 画布上所有参数/插头的**显示名已中文化**（如“段号 / 素材策略 / 抽卡缓存 / 自动匹配素材”）；
> 工作流 JSON 和 API 里的**字段名仍是英文**，保证旧工作流、示例和外部脚本兼容。
> 下拉选项值（`inherit` / `auto_duck` 等）也保持英文，鼠标悬停的中文 tooltip 会解释含义。

| 节点 | 作用 |
|---|---|
| `DirectorDeck_ModelLoader` | 主干 + 文本编码器 + 视频/音频 VAE + 最多 4 个 LoRA + flow shift |
| `DirectorDeck_DirectorConfig` | 分辨率预设（480p/720p/768p/1080p × 横屏/竖屏/方形）或自定义宽高、段时长、衔接帧、采样、种子、预览、显存策略 + 接缝参数 |
| `DirectorDeck_AssetShelf` | 最多 9 张参考图，槽位固定（@图片N） |
| `DirectorDeck_ScriptDesk` | 剧本 → 结构化段落（时长/对白/素材引用） |
| `DirectorDeck_SegmentBrief` | 段级剧本覆盖（接到生成器 brief 输入） |
| `DirectorDeck_FramePlanner` | 整条链的 17k+5 帧计划（head/delivery/sample/时间轴） |
| `DirectorDeck_DirectorTake` | 按段生成；自动续写、接缝修正、画面级抽卡缓存（`cache_mode`） |
| `DirectorDeck_SeamFixer` | 独立接缝修正（也可单独修已有两段） |
| `DirectorDeck_FinalCut` | 多段合并（**段数不限**，默认 4 组输入、面板可继续加）：自动裁衔接头、拼音轨、写 manifest；可选源音轨无损混流 + 边界交叉淡化 |
| `DirectorDeck_SegmentCache` | 抽卡记录（status/store/clear，只存元数据） |
| `DirectorDeck_VoiceLock` | 数字人锁音器：角色→音频槽+时间轴起点（+增益/优先级）；多角色 ducking / 混音 |
| `DirectorDeck_TTSBooth` | TTS 台词表：一张台词表 → 多角色配音 + 可锁音 CAST（可选依赖 Breeze-TTS-2） |
| `DirectorDeck_ScriptImport` | 剧本导入：外部剧本（文本/JSON/H3 V6）→ 自动匹配角色/场景/音频 → 可生成剧本 |
| `DirectorDeck_Refiner` | 二采工具：低 denoise 再采样（音频锁定）或 lanczos 放大 |

## 快速开始

1. **安装**：把仓库目录联接/复制到 `<ComfyUI>/custom_nodes/DirectorDeck`，重启 ComfyUI（详见 [docs/INSTALL.md](docs/INSTALL.md)）。
2. **打开画布工作流**：`examples/ui/DirectorDeck_M1_单段闭环.json` → 在「模型加载器」里选模型 → 运行。
3. **多段/数字人风格**：换下面的画布工作流；右下角「DirectorDeck 导演台」面板可一键加段/加覆盖/重抽。

| 画布工作流 | 说明 |
|---|---|
| `DirectorDeck_M1_单段闭环.json` | 单镜头 5 秒 |
| `DirectorDeck_M1_参考生视频.json` | 参考图 + `@图片N` + 段级剧本 |
| `DirectorDeck_M2_三段链.json` | 3 段续写（RGB 尾帧引导）+ 接缝 + 合并 + manifest |
| `DirectorDeck_M3_数字人锁音.json` | 真锁音 + 二采 |
| `DirectorDeck_M4_锁音无损.json` | 源音频逐样点无损混流 |
| `DirectorDeck_M5_latent续写.json` | 两段 latent 尾 token 续写（最快） |
| `DirectorDeck_M6_多角色混音.json` | 多角色锁音 + 自动 ducking |
| `DirectorDeck_M8_TTS锁音.json` | 两个 Breeze VoiceDesign → 锁音 → H3 |
| `DirectorDeck_M9_台词表配音.json` | 台词表一键多角色配音 → 锁音 |
| `DirectorDeck_M10_台词自动排期.json` | 不写起始秒：按句自动分段 + 自动排期 → 锁音 |
| `DirectorDeck_M11_超长两段衔接.json` | 台词超长提醒 + 两段复用同一份 CAST 自动衔接 |
| `DirectorDeck_M13_剧本导入.json` | 外部剧本导入 + 素材自动匹配 + 两段链生成 |

## 使用说明

### 1. 链式分段与续写

- 生成器按 `segment_index` 取段；接上 `previous_segment` 后，续写模式由 `continuity` 决定：
  `start`（首段）、`guide_tail`（RGB 尾帧+尾音引导）、`latent_tail`（直接搬 latent 尾 token，最快）、`none`。
- **全局画布尺寸**：在 `DirectorDeck_DirectorConfig` 里选 `分辨率`（480p / 720p / 768p / 1080p）+
  `画面比例`（16:9 横屏 / 9:16 竖屏 / 1:1 方形）即可；选预设后 `宽/高` 控件自动同步且被忽略，
  选「自定义（用宽高）」时才手填（必须是 32 的倍数）。预设尺寸已对齐 H3 的 32 倍数要求，
  例如 480p 横屏 = 864×480、768p 横屏 = 1376×768、1080p 横屏 = 1920×1088。
- **冲突规则（预设 vs 手填宽高）**：**预设优先**。选了分辨率预设时，手填宽高不生效：
  前端会把宽高控件锁成预设值（标成“预设自动”，手改会被自动改回并提示）；
  API 直接传了不一致的宽高也以预设为准，段元数据 `config.canvas_ignored` 会记录被忽略的值，
  并在控制台打印提醒。想让手填宽高生效，把 `分辨率` 改回「自定义（用宽高）」。
- 每段的素材/剧本/音色/配置都要显式选 `inherit`（沿用）或 `replace`/`overrides`（覆盖）；
  链尾用 `FinalCut` 合并（自动裁掉衔接头，写 manifest 方便追溯）。
- `guide_tail` 与 `latent_tail` 需要上一段；`latent_tail` 与 `guide_tail` 可混用，但同一链内模型必须一致。

### 2. 数字人锁音与混音

- 锁音器角色行格式：`名字: 音频槽, 起始秒, 增益dB, 优先级`（后两个可省略）；
  音频来源可以是 `LoadAudio`、Breeze-TTS-2 的 AUDIO，或台词表节点。
- 混音规则：
  - `auto_duck`（默认）：每小帧最响的角色不被压，其他同时说话的角色压低 `duck_db`；
  - `priority`：按角色优先级决定谁不被压；
  - `sum`：只叠加，不做自动压低。
- `duck_db` 默认 -8dB，`attack_ms`/`release_ms` 控制压低/恢复速度；混音参数参与缓存指纹。
- 合并时勾 `audio_from_source` 可直接用锁音源轨做逐样点无损成片；
  `audio_crossfade_ms` 在段边界做等功率交叉淡化（生成音频尤其有用）。

### 3. 抽卡缓存

- 生成器的 `cache_mode`：`auto`（命中复用/未命中生成并写）、`off`、`reroll`（强制重抽并覆盖）。
- 缓存位置 `output/DirectorDeck/cache/segments/`；删目录即可清空。
- 种子要可复现（`seed_base` 固定或显式 `seed`）才能命中；`seed=0` 时节点会先随机出固定种子再算指纹。

### 4. 本地 TTS（Breeze-TTS-2）

- 两种接法：
  1. 逐角色 TTS → `VoiceLock` 的 `audio_1..3`（保留 ducking/时间轴控制）；
  2. 整段对话用 `BreezeTTS2MultiSpeaker` 生成一路 → `VoiceLock` 单角色（`sum`）。
- TTS 输出 24kHz 单声道，锁音器会自动重采样到音频 VAE 的 32kHz。
- **台词表一键版**：`DirectorDeck_TTSBooth`，每行 `角色 [@起始秒] | 音色描述 | 台词`：
  - 起始秒可以省略（或写 `@auto`），由节点按“上一句结束 + `pause_ms`”自动往后排；
  - `auto_split` 打开时，一句里多个句号/问号/感叹号会自动拆成多句分别生成、分别排期；
  - `chars_per_second` 只用于生成前预估语速，摘要里给出「预估总长 vs 实际总长」；
  - 输出可锁音 CAST + 3 路可试听音频 + `total_seconds`（可直接回填段时长）；固定 `seed` 可复现/命中缓存。
  - **台词超长不缩句**：设 `max_seconds`（单段上限）后，超长只提醒并输出 `segment_count` / `plan`
    （每段建议时间窗）；按计划拆成多段续写即可。
  - **多段自动衔接**：同一份 CAST 的音轨是整条时间轴的，第 1 段 `cast_policy=replace`，
    后续段 `cast_policy=inherit` + `previous_segment`（`continuity=latent_tail` 更快）；
    每段生成器按自己的窗口自动切片，声音天然连续。
- 画布示例：`DirectorDeck_M8_TTS锁音.json`、`DirectorDeck_M9_台词表配音.json`、
  `DirectorDeck_M10_台词自动排期.json`、`DirectorDeck_M11_超长两段衔接.json`。

### 5. 导演台面板

右下角「DirectorDeck 导演台」：添加下一段、加素材/锁音/剧本覆盖、重抽选中段、查看段清单、
切换混音模式、duck ±2dB（自动作用到选中生成器所连的锁音器）、中英双语。

### 6. 外部剧本导入 + 一键建生成器

剧本由你自己写或外部工具生成，`DirectorDeck_ScriptImport` 负责导入、对齐、建链：

1. **粘贴剧本**：`script` 支持三种格式，`format` 选“自动识别”即可：
   - DirectorDeck 剧本（`第N段（X秒）` + `角色：台词` + 可选 `@图片N`）；
   - JSON 剧本（`characters` + `segments`）；
   - H3 V6 分段提示词（`【第N段｜X秒】` + `<d>` 台词）。
2. **自动匹配素材**：接上素材库（9 图槽）和/或角色音色库后：
   - 角色名 → 图片槽（名字/用途相似度，匹配不上按顺序兜底）；
   - 段落场景关键词 → 背景/场景槽；
   - 角色名 → 角色音色库的音频槽（没接角色库就给顺序建议）；
   - 匹配结果直接写回剧本的 `@图片N`，并输出 `mapping` 对照表供复核。
3. **输出**：`script` 接视频生成器的 `script`；`segment_count` 告诉前端要建几段。
4. **一键建生成器**：画布上先放一个“视频生成器”当模板，选中“剧本导入”节点，
   面板点 **按剧本建生成器** → 自动按段数创建/接线（复制模型、配置、素材、音色接法，
   自动串 `previous_segment`，后续段用 latent 续写）；再点 **补全合并输出** →
   自动生成 FinalCut + CreateVideo + SaveVideo。

画布示例：`examples/ui/DirectorDeck_M13_剧本导入.json`。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | 安装、模型清单、首次跑通、常见问题 |
| [docs/UI_WORKFLOWS.md](docs/UI_WORKFLOWS.md) | 9 个画布工作流怎么用、节点怎么接 |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | 字段级契约、错误码、缓存/指纹规则 |
| [docs/PLAN.md](docs/PLAN.md) | 里程碑与设计决策 |
| [docs/ENGINEERING.md](docs/ENGINEERING.md) | 开发与维护说明（仓库结构、本地验证、发布流程） |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更与真机验证记录 |

## License

AGPL-3.0（见 LICENSE）。参考实现采用 clean-room 原则：只使用 ComfyUI 内核公开接口与公开文档。
