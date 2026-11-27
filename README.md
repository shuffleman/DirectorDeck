# DirectorDeck

ComfyUI 节点库：**AI 短剧导演台**。把“模型 + 素材 + 剧本 + 音色”组织成链式分段生成流水线：
每段可接入自己的素材/锁音/剧本覆盖，也可以沿用上一段；最后二采、合并成片。

> 底座：ComfyUI 0.46+ / MiniMax H3（`comfy_extras.nodes_minimax_h3`），适配层预留其它模型。
> 规划见 [docs/PLAN.md](docs/PLAN.md)，字段级契约见 [docs/CONTRACTS.md](docs/CONTRACTS.md)。

## 状态

| 阶段 | 状态 | 内容 |
|---|---|---|
| **M0 骨架** | ✅ | 契约、包结构、core 纯函数（帧数学/policy/剧本/素材）、56 个单测、CI |
| **M1 单段闭环** | ✅ | 模型加载器、全局配置、资产管理器、剧本加载器、段级剧本、视频生成器；真机出片 |
| M2 多段+合并+抽卡 | ⬜ | FramePlanner / ContinuityGuide / SegmentCache / SeamFixer / FinalCut |
| M3 锁音+二采 | ⬜ | VoiceLock（真锁音）/ Refiner |
| M4 前端体验 | ⬜ | 素材画布 / 剧本编辑器 / 添加下一段 / 抽卡按钮 |
| M5 发布 | ⬜ | 文档、示例工作流、Comfy Registry |

## 设计要点（已定稿）

1. **链式分段 + 段级可选覆盖**：每段不接输入=沿用（policy 显式选 `inherit`）；接了=覆盖。
2. **每段必须显式指定 policy**：默认 `unset`，执行时未指定直接报错，杜绝静默继承。
3. **素材按 `@图片N` 槽位覆盖**：固定 9 槽，`merge` 按槽位替换，其余继承。
4. **段级 config 只允许安全子集；模型仅链首提供**（禁止“半条链两个模型”）。

## 节点（M1）

| 节点 | 作用 |
|---|---|
| `DirectorDeck_ModelLoader` | 主干 + 文本编码器 + 视频/音频 VAE + 最多 4 个 LoRA + flow shift |
| `DirectorDeck_DirectorConfig` | 画布/段时长/衔接帧/采样/种子/预览/显存策略 |
| `DirectorDeck_AssetShelf` | 最多 9 张参考图，槽位固定（@图片N） |
| `DirectorDeck_ScriptDesk` | 剧本 → 结构化段落（时长/对白/素材引用） |
| `DirectorDeck_SegmentBrief` | 段级剧本覆盖（接到生成器 brief 输入） |
| `DirectorDeck_DirectorTake` | 按段生成：策略解析 → 条件 → 采样 → 解码（输出 segment/images/audio） |

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
