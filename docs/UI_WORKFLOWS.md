# DirectorDeck 画布工作流说明

> 5 个 UI 格式工作流在 `examples/ui/`，在 ComfyUI 里用 **Workflow → Open**（或直接拖进画布）打开。
> 对应的 API 格式在 `examples/*.json`，两者逐输入校验一致（`tools/make_ui_workflows.py` 的 round-trip 校验）。

| 工作流 | 用到的能力 | 建议场景 |
|---|---|---|
| `DirectorDeck_M1_单段闭环.json` | 加载器 + 配置 + 剧本 + 生成器 | 第一次试跑 / 单镜头 |
| `DirectorDeck_M1_参考生视频.json` | 资产管理器 + 段级剧本 + @图片N | 角色/服装参考图 |
| `DirectorDeck_M2_三段链.json` | 帧计划器 + 链式续写 + 接缝 + 合并 | 15 秒以上连续镜头 |
| `DirectorDeck_M3_数字人锁音.json` | 锁音器 + 二采 | 给定台词、要口型对上的数字人 |
| `DirectorDeck_M4_锁音无损.json` | 锁音 + 源音频无损合并 | 成片音频要与源文件逐样点一致 |
| `DirectorDeck_M5_latent续写.json` | latent 尾 token 续写 | 想更快、更接近原生续写 |

## 打开后先改什么

1. **模型加载器**：把 5 个模型/VAE 换成你机器上的文件（下拉里没有就先把文件放进对应目录）。
2. **全局配置**：分辨率（32 倍数）、段时长、衔接帧（5/22/39/56）、采样步数、种子策略。
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
| 查看段清单 | 从 `/directordeck/segments` 拉最近 20 条段记录（🔒=锁音、✨=二采） |

## 常见问题

- **首段跑完但第二段报 `DD-E008`**：没有连上一段的 `segment` 输出（M2 起第 2 段必须接 `previous_segment`）。
- **改了段 2 的素材，段 3 没跟着变**：段 3 用的是 `inherit`，应继承段 2；确认段 2 的 policy 是 `replace`/`merge`。
- **数字人成片音频与台词文件不完全一样**：M3 锁音经过音频 VAE（神经编解码器）会有相位重建；要逐样点一致请用 M4 工作流的 `audio_from_source=true`。
- **显存 12G 跑三段链很慢**：正常，RGB 尾帧引导会让每段慢一些；可先 3 秒短段验证流程。
