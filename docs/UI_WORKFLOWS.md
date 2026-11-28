# DirectorDeck 画布工作流说明

> 13 个 UI 格式工作流在 `examples/ui/`，在 ComfyUI 里用 **Workflow → Open**（或直接拖进画布）打开。
> 节点参数在画布上显示中文；工作流文件里的字段名仍是英文（API/旧工作流兼容）。
> 对应的 API 格式在 `examples/*.json`，两者逐输入校验一致（`tools/make_ui_workflows.py` 的 round-trip 校验）。

| 工作流 | 用到的能力 | 建议场景 |
|---|---|---|
| `DirectorDeck_M1_单段闭环.json` | 加载器 + 配置 + 剧本 + 生成器 | 第一次试跑 / 单镜头 |
| `DirectorDeck_M1_参考生视频.json` | 资产管理器 + 段级剧本 + @图片N | 角色/服装参考图 |
| `DirectorDeck_M2_三段链.json` | 帧计划器 + 链式续写 + 接缝 + 合并 | 15 秒以上连续镜头 |
| `DirectorDeck_M3_数字人锁音.json` | 锁音器 + 二采 | 给定台词、要口型对上的数字人 |
| `DirectorDeck_M4_锁音无损.json` | 锁音 + 源音频无损合并 | 成片音频要与源文件逐样点一致 |
| `DirectorDeck_M5_latent续写.json` | latent 尾 token 续写 | 想更快、更接近原生续写 |
| `DirectorDeck_M6_多角色混音.json` | 多角色锁音 + 自动 ducking | 两个以上角色同时说话 |
| `DirectorDeck_M8_TTS锁音.json` | 本地 Breeze-TTS-2 两路发声 → 锁音 | 想用本地 TTS 当配音 |
| `DirectorDeck_M9_台词表配音.json` | 台词表一键多角色配音 → 锁音 | 台词都是文本、想少摆节点 |
| `DirectorDeck_M10_台词自动排期.json` | 不写起始秒，按句自动分段/自动排期 | 懒得算每句起点、想先跑起来 |
| `DirectorDeck_M11_超长两段衔接.json` | 超长提醒 + 多段复用同一份 CAST 衔接 | 台词总长超过一段的时长 |
| `DirectorDeck_M13_剧本导入.json` | 外部剧本导入 + 素材自动匹配 | 剧本在外部写、想一键建生成链 |
| `DirectorDeck_M16_完整工作流.json` | 外部剧本 + 素材匹配 + 两段生成 + 手动合并 + 二次处理成片 | **想直接跑完整链路**：从剧本到最终 mp4 |

## 完整工作流（M16）推荐操作顺序

1. 打开 `DirectorDeck_M16_完整工作流.json`，在「模型加载器」里确认模型；
   参考图 `11.png` / `睡衣.png` 换成你自己的（脚本里对应角色/场景会自动匹配）；
2. 直接点 **运行**：两段视频生成器跑完，节点上可以逐个预览带音频的 mp4；
3. 点合并器上的 **🎬 手动合并本片**；
4. 点二次处理成片上的 **🎬 生成最终视频**：默认走“潜空间二采 + RelayVSR 2x”，
   结果保存到 `output/DirectorDeck/final/`，节点上直接显示成片预览与 json 报告。

## 打开后先改什么

1. **模型加载器**：把 5 个模型/VAE 换成你机器上的文件（下拉里没有就先把文件放进对应目录）。
2. **全局配置**：分辨率（480p/720p/768p/1080p + 横屏/竖屏/方形，或自定义 32 倍数宽高）、
   段时长、衔接帧（5/22/39/56）、采样步数、种子策略。
   > 冲突规则：**预设优先**。选预设时宽高被锁成预设值（手改会被改回并提示）；
   > 要手填宽高请把“分辨率”改成「自定义（用宽高）」。
3. **剧本加载器**：直接写剧本；标题里的 `（5秒）` 会作为该段时长。
4. 需要参考图/锁音时，把对应 LoadImage/LoadAudio 换成本地素材。

## policy 速查（每段必须显式选）

| 输入 | 可选值 | 什么时候用 |
|---|---|---|
| `bundle_policy` | `provided`（第 1 段）/ `inherit`（之后） | 模型只在链首指定 |
| `config_policy` | `inherit` / `overrides` | 段级微调采样参数 |
| `assets_policy` | `inherit` / `replace` / `merge` / `clear` | merge=按 `@图片N` 槽位覆盖 |
| `brief_policy` | `inherit` / `replace` | 单独改某段文案 |
| `cast_policy` | `inherit` / `replace` / `merge_by_character` | 换音色/锁音 |
| `continuity` | `start`（第 1 段）/ `guide_tail` / `latent_tail` / `none` | `guide_tail`=RGB 尾帧+尾音引导；`latent_tail`=直接搬上一段 latent 尾部 token（更快，0.2.1）；`none`=新镜头硬切，不引导 |

> 默认值是 `unset`：不选就报 `DD-E001`，这是故意的，防止“以为继承了其实没有”。

## 外部剧本导入 + 一键建生成器

1. 画布放一个「剧本导入」节点（`DirectorDeck_M13_剧本导入.json` 已带），
   把外部剧本粘进 `script`：支持 DirectorDeck 文本、JSON、H3 V6；`format` 保持“自动识别”；
2. 可选把素材库（9 图槽）和/或角色音色库接进来；节点会输出 `mapping` 对照表，
   把角色 → @图片N、段落 → 场景图、角色 → 音频槽都列出来（不想匹配就关 `match_assets`）；
3. 画布上保留一个「视频生成器」当模板，选中「剧本导入」节点，点面板 **按剧本建生成器**：
   按 `segment_count` 自动创建 N 段、复制模型/配置/素材/音色接法、串 `previous_segment`；
4. 再点 **补全合并输出**：自动生成 FinalCut（段数不限，自动补齐动态输入）+ CreateVideo + SaveVideo；
   需要二采/RelayVSR 时，再把 FinalCut 的 images/audio 接到「二次处理成片」节点。

> 建链按钮只做“接线和参数”，不替你选模型；模型加载器/配置/素材的接法来自模板节点。

## 多段合并器：不限段数 + 手动合并

- 合并器画布上默认声明 **4 组** 输入（segment/images/audio），但**段数没有上限**：
  - 面板点 **补全合并输出**：按画布上生成器的数量自动给合并器补 `segment_5...` 等动态输入并接好；
  - 或选中合并器点 **合并器 +1 段输入**，手动加一组输入后再连线；
- 后端把动态输入当额外 kwargs 收进来，按编号顺序合并；缺席/不完整的组会被跳过并在控制台提示；
- manifest 里新增 `segment_count`，方便确认实际合了几段。
- **默认手动合并**：`merge_mode=手动` 时，普通排队不会合并（`ExecutionBlocker` 静默阻断下游保存），
  点合并器节点上的 **🎬 手动合并本片** 按钮才合并一次；改成 `自动` 可恢复旧行为。
  > 旧工作流升级后，跑完各段要手动点一次合并才出成片。

## 二次处理成片（二采 / RelayVSR / 二采 LoRA）

- 在合并器后面接 `DirectorDeck_FinalRefine`（二次处理成片），`bundle` 接模型加载器，
  `images`/`audio` 接合并器输出；可选接 `segment`（拿 prompt/种子）和 `config`（沿用输出目录）。
- 处理模式：关闭 / 潜空间二采 / RelayVSR 2x / 潜空间二采 + RelayVSR 2x / Lanczos。
- 二采参数全在节点上：prompt、seed、denoise、steps、采样器/调度器、**二采 LoRA + 强度**。
- RelayVSR：模型/Flash VAE 下拉、detail、锁曝光；`free_vram` 在超分前释放 H3。
- 输出：`output/<output_dir>/final/<prefix>_时间戳.mp4` + 同名 `.json` 报告，节点上直接显示成片预览。
- **手动触发**：默认 `run_mode=手动`，普通排队不处理；点节点上的 **🎬 生成最终视频** 才执行。
  > 二采/超分比较吃显存：RelayVSR 约 5GB；1080p 2x 先确认显存。

## 视频生成器上的预览 / 再次生成

每个生成器节点跑完都会显示本段带音频的 **mp4 预览**；节点上还有 **🔄 再次生成本段** 按钮，
点一下换种子并只重跑本段（上游未变的节点走缓存）。预览文件在 ComfyUI 的 temp 目录，重启会清空。

## 接本地 TTS（Breeze-TTS-2）

画布上按这个顺序接即可（API 示例 `examples/m8_tts_lock_api.json`）：

1. `Breeze-TTS-2 Load Model`（model 选 **int8 hybrid (recommended)**，decode_mode 建议 `eager`）；
2. 每个角色一个 `Breeze TTS 2 Voice Design`（或 `Voice Clone`/`Voice Direction`），填台词与音色描述，种子固定便于复现；
3. 各 TTS 的 `AUDIO` 接到 `DirectorDeck Voice Lock` 的 `audio_1..3`，角色行写 `角色名: 槽号, 起始秒, 增益dB, 优先级`；
4. Voice Lock 的 `cast` 接 `Director Take`（`cast_policy=replace`），后面照常 `FinalCut(audio_from_source=True)` 混源音轨。

注意：TTS 音频长度要落在该段采样窗口内；角色起始秒按整条时间轴算，超出窗口的尾巴会被截断。

### 一键版：TTS 台词表

`DirectorDeck_M9_台词表配音.json` 里只有一个「TTS 台词表」节点：

```
女主 @0.0 | 一位年轻女性，声音清澈温柔，语速偏慢。 | 你好，我是这部剧的女主角。
男主 @1.2 | 一位年轻男性，声音低沉沉稳，语气干练。 | 收到，我去检查船桨，五分钟以后开拍。
```

- 每行 `角色 @起始秒 | 音色描述 | 台词`；同一角色可写多行；
- **起始秒可省略**（或写 `@auto`）：`auto_start` 打开时按“上一句结束 + `pause_ms`”自动排；
  写了 `@秒` 的句子仍按写死的来，后面的自动句接着它继续；
- **`auto_split`**：一句里有多个句号/问号/感叹号时自动拆成多句分别生成、分别排期；
- `chars_per_second` 只用于生成前预估（摘要里对比预估/实际总长）；
- 角色第一次出现的顺序 = ducking 优先级；`seed` 固定可复现；
- 输出 `cast` 直接接视频生成器（`cast_policy=replace`），`audio_1..3` 可接 SaveAudio 试听，
  `total_seconds` 可回填全局配置的段时长。

### 台词超长怎么办（不缩句）

- 在台词表节点上设 `max_seconds`（例如 5.0）；超长时节点只提醒，输出 `segment_count` 和 `plan`：
  `plan` 会给出每段建议时间窗（如“第1段 0.00–5.00s / 第2段 5.00–7.80s”）。
- 按 `segment_count` 接对应数量的生成器做多段续写：
  第 1 段 `cast_policy=replace`；后续段 `cast_policy=inherit` + `previous_segment`
  （`continuity=latent_tail` 最快）。**同一份 cast 不用重新生成**：它的音轨是整条时间轴的，
  每段生成器按自己的窗口自动切片。
- 不会自动缩句、不会加速、不会裁台词；如果确实要短，请自己改台词文案。

## 多角色锁音的角色行格式

```
女主: 1, 0.0            # 音频槽 1，时间轴 0 秒开始
旁白: 2, 3.0, -3, 2     # 槽 2，3 秒开始，音量 -3dB，优先级 2
```

- `mix_mode`：`auto_duck`（逐帧最响者不被压）/ `priority`（按优先级）/ `sum`（只叠加）；
- `duck_db`（默认 -8）、`attack_ms`/`release_ms`（默认 60/200）控制压低与恢复；
- 混音参数会进 cast / 缓存指纹，改了会重新生成。

## 抽卡缓存（生成器的 `cache_mode`）

- `auto`（默认）：同一段输入 + 同一种子跑过就直接读回上次的 mp4/npz，跳过采样；
- `off`：完全不读写磁盘缓存；
- `reroll`：无视缓存、强制重抽并覆盖缓存。
- 缓存目录：`output/DirectorDeck/cache/segments/`；想清理直接删目录即可。
- 注意：要让 `auto` 有意义，种子要可复现（`seed_base` 固定或显式填 `seed`）；`seed=0` 时节点会先随机出一个种子再算指纹。

## 浮动面板（右下角）

| 按钮 | 行为 |
|---|---|
| 添加下一段 | 以选中段为模板新建下一段，自动复制模型/配置/剧本连线、接 `previous_segment`、policy 填 inherit/guide_tail |
| 加素材覆盖 | 新建资产管理器并接到选中段，`assets_policy` 自动切 `replace` |
| 加数字人锁音 | 新建锁音器并接 `cast`，`cast_policy` 自动切 `replace` |
| 加段级剧本 | 新建段级剧本并接 `brief`，`brief_policy` 自动切 `replace` |
| 重抽选中段 | 随机换该段 seed 并立即排队（上游未变的段会被 ComfyUI 缓存复用） |
| 切换混音模式 | 在选中生成器所连的 VoiceLock 上循环切换 `auto_duck / priority / sum` |
| duck -2dB / +2dB | 调整该 VoiceLock 的 `duck_db`（-24~0 之间，0.5 步进） |
| 查看段清单 | 从 `/directordeck/segments` 拉最近 20 条段记录（🔒=锁音、✨=二采） |

## 常见问题

- **首段跑完但第二段报 `DD-E008`**：没有连上一段的 `segment` 输出（M2 起第 2 段必须接 `previous_segment`）。
- **改了段 2 的素材，段 3 没跟着变**：段 3 用的是 `inherit`，应继承段 2；确认段 2 的 policy 是 `replace`/`merge`。
- **数字人成片音频与台词文件不完全一样**：M3 锁音经过音频 VAE（神经编解码器）会有相位重建；要逐样点一致请用 M4 工作流的 `audio_from_source=true`。
- **显存 12G 跑三段链很慢**：正常，RGB 尾帧引导会让每段慢一些；可先 3 秒短段验证流程。
