# DirectorDeck

ComfyUI 节点库：**AI 短剧导演台**。把“模型 + 素材 + 剧本 + 音色”组织成链式分段生成流水线：
每段可接入自己的素材/锁音/剧本覆盖，也可以沿用上一段；最后二采、合并成片。

> 底座：ComfyUI 0.46+ / MiniMax H3（`comfy_extras.nodes_minimax_h3`），适配层预留其它模型。
> 规划见 [docs/PLAN.md](docs/PLAN.md)，字段级契约见 [docs/CONTRACTS.md](docs/CONTRACTS.md)。

## 状态

| 阶段 | 状态 | 内容 |
|---|---|---|
| **M0 骨架** | ✅ | 契约、包结构、core 纯函数（帧数学/policy/剧本/素材）、单测、CI |
| **M1 单段闭环** | ✅ | 模型加载器、全局配置、资产管理器、剧本加载器、段级剧本、视频生成器；真机出片 |
| **M2 链式多段** | ✅ | 帧计划器、尾帧/尾音引导续写（RGB）、接缝曝光修正、多段合并、抽卡缓存；3 段 16.5s 真机出片；0.2.1 补 latent_tail 续写 |
| **M3 锁音+二采** | ✅ | 数字人锁音（逐流 noise_mask=0 真锁）、AV latent 拆合手术、二采（低 denoise 再采样）、音频 VAE 编解码；真机验证 |
| **M4 前端体验** | ✅ | 导演台浮动面板（添加下一段/覆盖节点/重抽/段清单）、后端 JSON 路由、FinalCut 源音频无损混流 |
| **M5 发布** | ✅ | 6 个画布工作流（examples/ui）、安装/工作流文档、CHANGELOG、Registry 元数据与发布 workflow |

## 快速开始

1. **安装**：把仓库目录联接/复制到 `<ComfyUI>/custom_nodes/DirectorDeck`，重启 ComfyUI（详见 [docs/INSTALL.md](docs/INSTALL.md)）。
2. **打开画布工作流**：`examples/ui/DirectorDeck_M1_单段闭环.json` → 在「模型加载器」里选模型 → 运行。
3. **多段/数字人**：换 `DirectorDeck_M2_三段链.json` / `DirectorDeck_M3_数字人锁音.json`，
   右下角「DirectorDeck 导演台」面板可一键“添加下一段 / 加覆盖 / 重抽”
   （详见 [docs/UI_WORKFLOWS.md](docs/UI_WORKFLOWS.md)）。

| 画布工作流 | 说明 |
|---|---|
| `DirectorDeck_M1_单段闭环.json` | 单镜头 5 秒 |
| `DirectorDeck_M1_参考生视频.json` | 参考图 + `@图片N` + 段级剧本 |
| `DirectorDeck_M2_三段链.json` | 3 段续写（RGB 尾帧引导）+ 接缝 + 合并 + manifest |
| `DirectorDeck_M3_数字人锁音.json` | 真锁音 + 二采 |
| `DirectorDeck_M4_锁音无损.json` | 源音频逐样点无损混流 |
| `DirectorDeck_M5_latent续写.json` | 两段 latent 尾 token 续写（0.2.1，最快） |

> 0.2.1 起续写多了一个更快的模式：把生成器的 `continuity` 选成 **`latent_tail`**，
> 第 2 段会直接搬上一段 latent 的尾部 token（mask=0 钉住），省掉 RGB 解码/编码的绕路。
> 可直接跑的 API 示例：`examples/m5_latent_chain_api.json`（画布版画法相同，把 continuity 换成 latent_tail 即可）。

## 抽卡缓存：画面级秒复用（0.2.2）

生成器新增 `cache_mode` 控件：`auto`（默认，命中就复用、没命中生成并写）/ `off` / `reroll`（强制重抽并覆盖）。
缓存内容是**画面 mp4 + 音轨/latent/锁音源轨 npz + 段元数据 json**，放在
`output/DirectorDeck/cache/segments/`；指纹覆盖 resolved 输入、提示词、种子、采样参数、引导来源和锁音签名。

| 指标（两段 latent 链） | 结果 |
|---|---|
| 冷缓存首次 | 346.7s（正常采样） |
| 重启 ComfyUI 后同工作流 | 两段全命中，整条 prompt **3.6s（墙钟 5.1s）**，约 **96×** |
| 画面一致性 | 与首次生成平均像素差 **2.76**（0–255 口径，仅 h264 重编码误差） |
| 磁盘占用 | 约 8MB/段（mp4 1.5–2.4MB + npz 4.4–5.6MB） |

## 设计要点（已定稿）

1. **链式分段 + 段级可选覆盖**：每段不接输入=沿用（policy 显式选 `inherit`）；接了=覆盖。
2. **每段必须显式指定 policy**：默认 `unset`，执行时未指定直接报错，杜绝静默继承。
3. **素材按 `@图片N` 槽位覆盖**：固定 9 槽，`merge` 按槽位替换，其余继承。
4. **段级 config 只允许安全子集；模型仅链首提供**（禁止“半条链两个模型”）。

## 节点（M2）

| 节点 | 作用 |
|---|---|
| `DirectorDeck_ModelLoader` | 主干 + 文本编码器 + 视频/音频 VAE + 最多 4 个 LoRA + flow shift |
| `DirectorDeck_DirectorConfig` | 画布/段时长/衔接帧/采样/种子/预览/显存策略 + 接缝参数 |
| `DirectorDeck_AssetShelf` | 最多 9 张参考图，槽位固定（@图片N） |
| `DirectorDeck_ScriptDesk` | 剧本 → 结构化段落（时长/对白/素材引用） |
| `DirectorDeck_SegmentBrief` | 段级剧本覆盖（接到生成器 brief 输入） |
| `DirectorDeck_FramePlanner` | 整条链的 17k+5 帧计划（head/delivery/sample/时间轴） |
| `DirectorDeck_DirectorTake` | 按段生成；接 `previous_segment` 自动续写（RGB/latent 两种）、接缝修正、**画面级抽卡缓存**（`cache_mode`） |
| `DirectorDeck_SeamFixer` | 独立接缝修正（也可单独修已有两段） |
| `DirectorDeck_FinalCut` | 多段合并：自动裁衔接头、拼音轨、写 manifest；可选 `audio_from_source` 用锁音源轨（无损） |
| `DirectorDeck_SegmentCache` | 抽卡记录（status/store/clear，只存元数据） |
| `DirectorDeck_VoiceLock` | 数字人锁音器：角色→音频槽+时间轴起点（真锁音） |
| `DirectorDeck_Refiner` | 二采工具：低 denoise 再采样（音频锁定）或 lanczos 放大 |

## 安装 / 开发

```powershell
# 1) 安装到 ComfyUI（开发期用目录联接，改完重启 ComfyUI）
New-Item -ItemType Junction -Path "<ComfyUI>/custom_nodes/DirectorDeck" -Target "<本仓库>"

# 2) 单测（零第三方依赖，stdlib unittest）
python -m unittest discover -s tests -v
```

**真机验证（不打扰正在用的 8188）**：用同一个 ComfyUI 跑第二个实例 8189：

```powershell
python -s ComfyUI\main.py --port 8189 `
  --extra-model-paths-config "<instance-model-paths>.yaml" `
  --input-directory <input> --output-directory <output>

# 另一个终端：跑示例（模型加载+采样约 5 分钟）
python tools\run_example.py examples\m1_single_segment_api.json --server http://127.0.0.1:8189
```

产物：`output/DirectorDeck/M1_single*.mp4`，运行记录在 `runs/m1_server/`。

**M2 三段链（验证数据）**：

```powershell
python tools\run_example.py examples\m2_chain_api.json --server http://127.0.0.1:8189
python tools\run_example.py examples\m2_reroll_seg2_api.json --server http://127.0.0.1:8189
```

| 指标 | 结果 |
|---|---|
| 成片 | 3 段 / 396 帧 / 16.5s / 640x352 / h264+AAC |
| 段边界亮度差 | 0.00141 与 0.00020（阈值 <0.01） |
| 续写引导 | 第 2/3 段 `guide.used=true`（22 帧尾画面 + 尾音） |
| 接缝修正 | `seam.apply=true, gain=0.96, offset≈0.027/0.030`，残余 0.0019/0.0006 |
| 抽卡缓存 | 只改第 2 段 seed 重跑：`execution_cached=["1","2","3","10"]`（模型/配置/剧本/**第 1 段**复用），总耗时 695s→406s |
| 落盘 | `output/DirectorDeck/segments/*.json`（每段元数据）、`output/DirectorDeck/manifests/*.json`（成片清单） |

**M3 数字人锁音 + 二采（验证数据）**：

```powershell
python tools\run_example.py examples\m3_digital_human_api.json --server http://127.0.0.1:8189
```

| 指标 | 结果 |
|---|---|
| 锁音生效 | 段元数据 `lock.applied=true`，roles=女主，窗口 `[0, 5.167]s`，锁入 165333 采样点 |
| 音轨内容保真 | 源音频 vs 锁音输出：**包络相关 0.9709**、频带结构一致（H3 的音频 VAE 是神经编解码器，重建波形相位会变，样点级相关不适合做指标） |
| 二采效果 | 124 帧 → 124 帧；raw vs refined **平均像素差 5.7**（画面确有再生成） |
| 二采保音 | raw vs refined **波形相关 0.9946**（二采不改音轨） |
| 段元数据 | `lock`/`refine` 字段落盘，可追溯 |

> 注：要做到“成片里音频与源文件逐样点一致”，应在最终合并时直接把源音频混流（M4 的 FinalCut 增加 `audio_from_source` 选项）；锁音目前保证的是**内容/口型对应**，不是无损封装。

## M4 前端体验（已验证）

- **浮动面板**：右下角“DirectorDeck 导演台”，按钮包括
  `添加下一段 / 加素材覆盖 / 加数字人锁音 / 加段级剧本 / 重抽选中段 / 查看段清单 / 帮助`，中英双语。
- **自动接线**：添加下一段会复制模型/配置/剧本上游连线、接 `previous_segment`、把 6 个 policy 填成
  `inherit/inherit/inherit/inherit/inherit/guide_tail`；覆盖节点会自动把对应 policy 切到 `replace`。
- **重抽**：改选中段 seed 并 `queuePrompt`。
- **后端路由**：`/directordeck/health`、`/directordeck/segments`、`/directordeck/manifests`（面板“段清单”用）。
- **验证**：`node --check` 通过；8189 的 `/extensions` 收录 `/extensions/DirectorDeck/directordeck.js`
  且 GET 返回 200；三个路由均返回真实段/清单数据。

**M4 源音频混流验证**（锁音段 → FinalCut `audio_from_source=true` → SaveAudio）：

| 指标 | 结果 |
|---|---|
| 成片 | 124 帧 / 5.16s（与一采一致） |
| 清单 | `audio_source="source"`，`total_frames=124` |
| 音频 | FLAC 与源 wav **样点相关 1.0，最大绝对差 0.0**（FLAC 无损，逐样点一致） |

## 目录

```
__init__.py              # ComfyUI 入口（插件目录根必须是包）
director_deck/
  core/                  # 纯 Python：types / frames / policy / assets / script（不 import ComfyUI）
  adapters/h3.py         # 唯一接触 ComfyUI 内核的层
  nodes/                 # 节点薄壳
  web/                   # 前端扩展（M4）
examples/                # 可运行的 API 工作流示例
tools/                   # 生成示例 / 真机跑示例 / 冒烟脚本
tests/                   # 单测
docs/                    # PLAN.md / CONTRACTS.md
```

## 工程约定

- **代码注释一律用完整、口语化的中文**（写清楚“为什么这么干”，而不只是“这行干了啥”）。
- core 不 import ComfyUI；adapters 是唯一耦合点；节点只做参数校验和组装。
- 节点参数只追加不改顺序；旧 ID 保留别名；`IS_CHANGED` 用 resolved 指纹做缓存。
- 错误统一 `DirectorError(code, message)`，中文文案 + 错误码表（CONTRACTS §10）。

## License

AGPL-3.0（见 LICENSE）。参考实现采用 clean-room 原则：只使用 ComfyUI 内核公开接口与公开文档。
