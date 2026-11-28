# DirectorDeck 工程与开发文档

> 这份文档给**开发和维护**用：工程约定、仓库结构、本地验证方式、历史验证数据。
> README 只保留功能与使用方式，不放这些内容。

## 1. 工程约定

- **代码注释一律用完整、口语化的中文**：写清楚“为什么这么干”，而不只是“这行干了啥”。
- **分层**：`core/` 不 import ComfyUI（纯 Python，方便单测）；`adapters/` 是唯一接触 ComfyUI 内核的层；
  `nodes/` 只做参数校验和组装。
- **向后兼容**：节点参数只追加不改顺序；旧节点 ID/类型保留别名；`IS_CHANGED` 用 resolved 指纹做缓存。
- **错误处理**：统一 `DirectorError(code, message)`，中文文案 + 错误码表（`docs/CONTRACTS.md` 错误码章节）。
- **外部依赖可选**：Breeze-TTS-2 等第三方节点包只在运行时探测（`adapters/breeze_tts.py`），
  缺失时报 `DD-E050`，不能让 DirectorDeck 自己加载失败。
- **验证数据不进 README**：真机指标写进 `CHANGELOG.md` / 本文档；README 保持面向使用者。

## 2. 仓库结构

```
__init__.py              # ComfyUI 入口（插件目录根必须是包）
director_deck/
  core/                  # 纯 Python：types / frames / policy / assets / script（不 import ComfyUI）
  adapters/              # 接触 ComfyUI 内核的适配层（h3 / av_latent / segment_cache / breeze_tts ...）
  nodes/                 # 节点薄壳
  web/                   # 前端扩展（导演台浮动面板）
examples/                # 可运行的 API 工作流示例
examples/ui/             # 画布工作流（UI 0.4）
tools/                   # 生成示例 / 真机跑示例 / 验证脚本
tests/                   # 单测（stdlib unittest）
skills/                  # 独立 agent skill（不参与 ComfyUI 运行；写剧本交付层）
docs/                    # INSTALL / CONTRACTS / PLAN / UI_WORKFLOWS / ENGINEERING
runs/                    # 本地真机运行记录（不入库）
```

## 3. 本地开发与验证

```powershell
# 安装到 ComfyUI（开发期用目录联接，改完重启 ComfyUI）
New-Item -ItemType Junction -Path "<ComfyUI>/custom_nodes/DirectorDeck" -Target "<本仓库>"

# 单测（零第三方依赖，stdlib unittest）
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

**生成/校验示例**：

```powershell
python tools/gen_examples.py            # 生成 examples/*.json
python tools/make_ui_workflows.py 8189  # 生成 examples/ui/*.json 并做 UI->API round-trip 校验
node --check director_deck/web/directordeck.js
python skills/directordeck-screenplay-bridge/scripts/validate_screenplay.py 剧本.txt --format auto
```

## 4. 历史验证数据（真机 8189，RTX 5070 12G）

### M2 三段链

| 指标 | 结果 |
|---|---|
| 成片 | 3 段 / 396 帧 / 16.5s / 640x352 / h264+AAC |
| 段边界亮度差 | 0.00141 与 0.00020（阈值 <0.01） |
| 续写引导 | 第 2/3 段 `guide.used=true`（22 帧尾画面 + 尾音） |
| 接缝修正 | `seam.apply=true, gain=0.96, offset≈0.027/0.030`，残余 0.0019/0.0006 |
| 抽卡复用 | 只改第 2 段 seed 重跑：`execution_cached=["1","2","3","10"]`，总耗时 695s→406s |

### M3 数字人锁音 + 二采

| 指标 | 结果 |
|---|---|
| 锁音生效 | `lock.applied=true`，roles=女主，窗口 `[0, 5.167]s`，锁入 165333 采样点 |
| 音轨保真 | 源音频 vs 锁音输出：包络相关 0.9709（音频 VAE 是神经编解码器，样点级相关不适合做指标） |
| 二采效果 | 124→124 帧；raw vs refined 平均像素差 5.7；波形相关 0.9946 |
| 无损混流 | M4 `audio_from_source`：FLAC 与源 wav 样点相关 1.0、最大绝对差 0.0 |

### 多角色 ducking（M6）

| 场景 | 结果 |
|---|---|
| priority，B 重叠区 | -7.99dB（目标 -8dB），A 保持 0.00dB |
| sum | 0.00dB |
| auto_duck（B 更响） | A 被压 -8.00dB |
| 每路 -6dB 增益 | 实测 -6.00dB |
| 峰值 | 0.508（未触限幅） |

### 跨段一致性 / 交叉淡化（M7）

| 设置 | 边界跳变 | jump/步进 | 边界前后 RMS |
|---|---|---|---|
| 硬接 0ms | 0.05384 | 2.23 | 0.327 → 0.238（掉档） |
| 交叉淡化 80ms | 0.01277 | 0.57 | 0.186 → 0.197（平稳） |

第二段开头继承上一段增益 `{A:1.0, B:0.398}`；对比重置上下文，开头 30ms B 能量低 5.68dB。

### TTS（M8/M9）

| 项目 | 结果 |
|---|---|
| M8 两路 TTS | 成片音频与 TTS 原声拟合 corr=0.999；重叠 ducking 中位 -7.0dB、p10 -7.85dB |
| M9 台词表节点 | 女主 2.32s / 男主音轨 4.08s（1.2s 起），124 帧；单角色段拟合 corr=1.000；ducking 中位 -7.30dB、p10 -7.87dB |
| 缓存重跑 | 固定 TTS 种子后 Take 0.41s 命中缓存，整条 prompt 43.9s（无 H3 采样） |

## 5. 发布与 CI

- 版本号在 `pyproject.toml`、`director_deck/__init__.py`、`routes.py` 三处保持一致。
- 每次功能更新：跑单测 + `make_ui_workflows.py` 全部 PASS，再更新 `CHANGELOG.md` 并打 tag。
- GitHub Actions 的 CI/发布 workflow 已配置（`.github/workflows/`）；Registry 发布需要配置
  `REGISTRY_ACCESS_TOKEN`，CI 需要账号 billing 状态正常。
