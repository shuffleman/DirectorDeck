# DirectorDeck 安装与验证

> 目标：在 ComfyUI（0.46+）里加载 DirectorDeck 的 12 个节点与前端面板，并跑通一条真实链路。

## 1. 环境要求

| 项 | 要求 |
|---|---|
| ComfyUI | 0.46+（内置 `comfy_extras.nodes_minimax_h3`） |
| Python | 3.10 – 3.12（跟随 ComfyUI venv） |
| 显存 | 12G 可跑（动态 offload），16G+ 更稳 |
| 系统 | Windows / Linux 均可（开发验证在 Windows + RTX 5070 12G） |

### 需要的模型文件（放到 ComfyUI 的模型目录）

| 类型 | 用途 | 例子 |
|---|---|---|
| diffusion_models | H3 主干（fl2va/ref2va 共用） | `MiniMax/fastvideo_fasth3_8step_v2_pruned_bf16.safetensors` |
| text_encoders | H3 文本编码器（Qwen3-VL） | `qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` |
| vae | 视频 VAE | `minimax_h3_video_vae_int8_convrot.safetensors` |
| vae | 音频 VAE | `minimax_h3_audio_vae_fp32.safetensors` |
| loras（可选） | ref2va / 8 步加速 / 运动修复 | 见 `examples/*.json` 里的默认组合 |

这些名称只是示例：节点面板里选你自己已有的文件即可。

### 可选：本地 TTS（Breeze-TTS-2）

想在生成器里直接合成台词（而不是另外录音），需要额外装 **ComfyUI-Breeze-TTS-2** 节点包和模型：

| 项 | 要求 |
|---|---|
| 节点包 | `ComfyUI/custom_nodes/ComfyUI-Breeze-TTS-2`（提供 `BreezeTTS2LoadModel / VoiceDesign / VoiceClone / VoiceDirection / MultiSpeaker` 等节点） |
| 模型 | `ComfyUI/models/breezetts2/drbaph_Breeze-TTS-2-comfyui/Breeze-TTS-2-int8-hybrid.safetensors`（推荐；约 4.6GB） |
| 依赖 | 共享的 `audio_tokenizer/` 编解码器与配置文件（同一个仓库目录里） |

接入方式：TTS 节点输出 `AUDIO` → 接 `DirectorDeck_VoiceLock` 的 `audio_1/audio_2/audio_3`；
角色行写 `角色名: 槽号, 起始秒`。完整示例见 `examples/m8_tts_lock_api.json`。
TTS 输出 24kHz 单声道，锁音器会自动重采样到 32kHz。

## 2. 安装（三选一）

### A. 开发模式（推荐，改代码立即生效，重启 ComfyUI 后加载）

```powershell
# Windows：目录联接（不是复制，改仓库代码等于改插件代码）
New-Item -ItemType Junction `
  -Path "<ComfyUI>/custom_nodes/DirectorDeck" `
  -Target "F:\Comfy-Desktop\DirectorDeck"
```

```bash
# Linux/macOS：软链接
ln -s /path/to/DirectorDeck "<ComfyUI>/custom_nodes/DirectorDeck"
```

### B. ComfyUI Manager / Registry（发布后）

```bash
comfy node install director-deck
# 或在 ComfyUI Manager 里搜索 "DirectorDeck"
```

### C. 手动复制

把整个仓库目录复制到 `<ComfyUI>/custom_nodes/DirectorDeck`（目录根部必须有 `__init__.py`）。

## 3. 启动验证

重启 ComfyUI 后检查：

1. 右键菜单出现 **DirectorDeck** 分类，共 12 个节点：
   模型加载器 / 全局配置 / 资产管理器 / 剧本加载器 / 段级剧本 / 帧计划器 /
   视频生成器 / 接缝修正器 / 多段合并器 / 抽卡缓存 / 数字人锁音器 / 二采工具。
2. 浏览器右下角出现 **DirectorDeck 导演台** 浮动面板。
3. 前端 JS 被收录：浏览器打开 `http://127.0.0.1:8188/extensions`，应包含
   `/extensions/DirectorDeck/directordeck.js`。
4. 后端路由可用：`http://127.0.0.1:8188/directordeck/health` 返回 `{"ok": true, ...}`。

启动日志里应有：

```
[DirectorDeck] v0.2.0 loaded (nodes: 12)
```

## 4. 第一次跑通（单段 5 秒）

1. 画布打开 `examples/ui/DirectorDeck_M1_单段闭环.json`；
2. 在「模型加载器」里选好你的模型文件；
3. 点运行（队列），首次加载约 1–2 分钟，采样 10 步约 3–4 分钟（12G 显存）；
4. 成片在 `output/DirectorDeck/M1_single_*.mp4`，段元数据在
   `output/DirectorDeck/segments/`。

## 5. 命令行验证（可选，不打开画布）

```powershell
# 单元测试（不需要 ComfyUI，纯 stdlib）
python -m unittest discover -s tests -v

# 用独立实例 8189 跑 API 示例（不打扰主实例）
python -s ComfyUI\main.py --port 8189 `
  --extra-model-paths-config "<instance-model-paths>.yaml" `
  --input-directory <input> --output-directory <output>

python tools\run_example.py examples\m2_chain_api.json --server http://127.0.0.1:8189
```

## 6. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 菜单里没有 DirectorDeck | 目录根部缺 `__init__.py`；或没重启 ComfyUI |
| 节点在但前端面板不出现 | `WEB_DIRECTORY` 没生效：确认 `director_deck/web/directordeck.js` 存在，强刷浏览器缓存 |
| 报 `DD-E001 policy 未指定` | 这是设计：每段必须显式选 6 个 policy（不选不继承） |
| 报 `DD-E008 guide_tail 需要上一段` | 第 2 段起要接 `previous_segment`；或 ComfyUI 重启后运行期尾帧没了，重跑上一段 |
| 显存不足 / 很慢 | 12G 下动态 offload 正常；可减少段数、降分辨率或换 fp8 权重 |
| 音频与源文件不是逐样点一致 | 用 FinalCut 的 `audio_from_source=true`（M4 起支持） |

## 7. 发布（维护者）

```bash
# 需要：comfy-cli、Registry 账号、PublisherId 与 pyproject 的 [tool.comfy] 一致
comfy node publish
```

GitHub Actions 也提供了 `publish.yml`：推送 `v*` tag 时自动发布，
需要仓库 Secret `REGISTRY_ACCESS_TOKEN`。
