# Changelog

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
