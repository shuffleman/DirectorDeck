# DirectorDeck 数据契约 v0.1

> 本文件是**所有节点、工作流、缓存、迁移的唯一契约**。任何字段增删都要先改这里。
> 状态：M0 阶段定稿（2026-11-27）。已确认决策：
> 1. **每段必须显式指定 policy**（默认 `unset`，执行时报错；前端自动填 `inherit`）
> 2. **素材 merge 按 `@图片N` 槽位覆盖**（槽位固定 1..9）
> 3. **段级 config 只允许安全子集；模型 bundle 只允许链首提供**

---

## 0. 全局约定

| 项 | 约定 |
|---|---|
| 节点 ID | 前缀 `DirectorDeck_`，如 `DirectorDeck_ModelLoader`；发布后**只增不改** |
| 节点分类 | `DirectorDeck/`，子类目：加载 / 素材 / 剧本 / 生成 / 后处理 / 输出 |
| socket 类型 | 全部为字符串常量（ComfyUI 自定义类型即字符串），见 §1 |
| 序列化 | 所有自定义类型在内部是 **dataclass**；跨节点传递用 dataclass 实例；落盘 JSON 必须带 `"schema": "<type>@<version>"` |
| 类型版本 | 每个类型有 `schema_version`，字段只追加，不删不改名；弃用字段保留并标记 |
| 帧率 | 固定 `fps = 24`（H3 原生）；任何需要 fps 的地方只读常量 |
| 帧网格 | 所有视频长度必须满足 `length % 17 == 5`（17k+5） |
| 错误 | 统一 `DirectorError(code, message, node, segment)`；中文文案 |
| 素材路径 | 统一复制到 `ComfyUI/input/DirectorDeck/<project>/`，类型里存**相对 input 的路径** |
| 时间 | manifest 用 ISO8601；段内时间单位=秒（float） |

---

## 1. 自定义类型总表

| 类型 | 生产节点 | 消费节点 | 一句话 |
|---|---|---|---|
| `DIRECTOR_BUNDLE` | `ModelLoader` | 生成器 | 模型组合（主干/TE/双 VAE/LoRA/档位） |
| `DIRECTOR_CONFIG` | `DirectorConfig` | 计划器/生成器/合并器 | 全局配置（唯一真相源） |
| `DIRECTOR_CONFIG_OVERRIDE` | `SegmentConfig`（可选） | 生成器 | 段级配置安全子集 |
| `DIRECTOR_ASSETS` | `AssetShelf` | 剧本/生成器/锁音 | 固定 9 槽图片（+可选音视频） |
| `DIRECTOR_SCRIPT` | `ScriptDesk` | 计划器/生成器 | 剧本原文 + 结构化段落 |
| `DIRECTOR_BRIEF` | `SegmentBrief` | 生成器 | 单段剧本覆盖 |
| `DIRECTOR_CAST` | `VoiceLock` | 生成器 | 角色 ↔ 音色/音频映射 |
| `DIRECTOR_PLAN` | `FramePlanner` | 生成器/合并器 | 每段生成计划（帧数学+顺序） |
| `DIRECTOR_SEGMENT` | `DirectorTake` | 生成器（下一段）/二采/合并 | 一段结果 + 解析后输入快照 |
| `DIRECTOR_REFINE`（M3） | `Refiner` | 合并器 | 二采参数与结果 |
| `DIRECTOR_MANIFEST` | `FinalCut` | 输出/重现 | 整片清单 |

> `DIRECTOR_TAKE_INPUTS`（解析后输入）不单独做 socket，内嵌在 `DIRECTOR_SEGMENT.resolved` 里。

---

## 2. 类型字段定义（v0.1）

### 2.1 `DIRECTOR_BUNDLE`（schema 1）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `fl2va_model` | str | ✓ | 主干（T2VA/I2VA/FL2VA 用） |
| `ref2va_model` | str | ✓ | 主干（Ref2VA/数字人用，可与 fl2va 相同） |
| `text_encoder` | str | ✓ | CLIPLoader 的 clip 名，type=`minimax` |
| `video_vae` | str | ✓ | 视频 VAE |
| `audio_vae` | str | ✓ | 音频 VAE |
| `loras` | list[{name,strength}] |  | 追加式，≤9 |
| `vram_tier` | str | ✓ | `auto/16G/12G/8G` |
| `pinned` | bool |  | 是否保持加载不卸载（默认 false） |

### 2.2 `DIRECTOR_CONFIG`（schema 1）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `width` / `height` | int | 640/352 | 须 32 倍数 |
| `aspect_ratio` | str | `16:9` | 仅用于展示/反推宽高 |
| `fps` | int | 24 | 锁死不可改 |
| `segment_seconds` | float | 5.0 | 默认每段秒数（可被 brief/script 覆盖） |
| `handoff_frames` | int | 22 | 衔接帧，只允许 5/22/39/56 |
| `sampler_name` | str | `er_sde` | |
| `sigmas_string` | str | 13 号同款 | 空=用 BasicScheduler |
| `interpolate_to_steps` | int | 10 | |
| `denoise` | float | 1.0 | |
| `seed_strategy` | str | `per_segment` | `per_segment/fixed/increment` |
| `seed_base` | int | 0 | |
| `preview` | bool | true | 采样预览开关 |
| `vram_policy` | str | `release` | `release/unload/none` |
| `output_dir` | str | `DirectorDeck` | output 子目录 |
| `cleanup_segments` | str | `ask` | `ask/auto/keep` |
| `seam_enabled` | bool | true | 段间是否自动做曝光/亮度修正（M2） |
| `seam_window` | int | 12 | 接缝匹配比较的帧数（2–48） |
| `seam_max_add` | float | 0.10 | 允许的亮度偏移上限 |
| `seam_gain_limit` | float | 0.04 | 允许的增益偏差上限 |

### 2.3 `DIRECTOR_CONFIG_OVERRIDE`（schema 1，段级安全子集）

允许字段：`segment_seconds`、`handoff_frames`、`sampler_name`、`sigmas_string`、`interpolate_to_steps`、`denoise`、`seed_strategy`、`seed_base`、`preview`、`vram_policy`。

**禁止**：`fps`、`width/height`（整链一致）、模型相关、输出目录。

### 2.4 `DIRECTOR_ASSETS`（schema 1）

```json
{
  "schema": "DIRECTOR_ASSETS@1",
  "slots": [
    {"slot": 1, "path": "DirectorDeck/demo/01_face.png", "name": "01_face.png", "role": "character", "enabled": true},
    ...  // 固定 1..9，空槽 path=null
  ],
  "audios": [{"id": "a1", "path": "...", "start": 0.0, "end": null}],
  "videos": [{"id": "v1", "path": "...", "start": 0.0, "end": null}]
}
```

- **槽位固定**：`slots[i].slot == i+1`，`@图片N` 直接对应 `slots[N-1]`；空槽参与「清除」语义。
- `enabled=false` 的槽不进入提示词绑定。
- 引用语法：正文中 `@图片1` ≡ `<Picture 1>`；`@音频1` ≡ `<Audio 1>`；`@视频1` ≡ `<Video 1>`。

### 2.5 `DIRECTOR_SCRIPT`（schema 1）

```json
{
  "schema": "DIRECTOR_SCRIPT@1",
  "raw": "全文",
  "mode": "auto",
  "segments": [
    {"index": 1, "text": "段落提示词", "seconds": 5.0,
     "dialogue": [{"character": "女主", "text": "台词"}],
     "refs": [1, 2]}
  ],
  "warnings": []
}
```

- `seconds` 由分段器从标题/正文解析，缺省用 config.segment_seconds。
- `refs` 是素材槽号（来自 `@图片N`）。

### 2.6 `DIRECTOR_BRIEF`（schema 1）

与 script 的单个 segment 同构：`{text, seconds?, dialogue, refs}`，`index` 由生成器决定。

### 2.7 `DIRECTOR_CAST`（schema 1）

```json
{
  "schema": "DIRECTOR_CAST@1",
  "roles": [
    {"id": "girl", "name": "女主",
     "start": 0.0, "gain_db": 0.0, "priority": 2,
     "voice": {"kind": "audio", "path": "DirectorDeck/demo/voice_girl.wav", "start": 0.0, "end": 5.0},
     "face_slot": 1}
  ],
  "lock_audio": true,
  "mix": {"mode": "auto_duck", "duck_db": -8.0, "attack_ms": 60, "release_ms": 200}
}
```

- `voice.kind`：`audio`（真锁音，需自研节点）/ `tts`（M3 后）/ `none`（生成音频）。
- `lock_audio=true` 时该角色音轨以 **noise_mask=0** 锁进 AV latent。
- **多角色混音（0.2.3）**：`mix.mode` = `auto_duck`（逐帧最响者不被压）/ `priority`（按 `priority` 值）/
  `sum`（只叠加）；`duck_db` 是被压分贝，`attack_ms`/`release_ms` 是压低/恢复时间；
  每路还有 `gain_db`（角色行第 3 参）与 `priority`（第 4 参）。
- **运行期字段**：`roles[i].audio_data`（AUDIO 张量）只在进程内传递，写盘/进 JSON 时会由
  `policy._serializable_cast()` 剔除；落盘的 cast 只有 `id/name/start/gain_db/priority/voice` 和 `mix`。
- **跨段混音上下文（0.2.4）**：生成器在段运行期仓库和缓存里额外保存
  `mix_context = {gain_state: {角色: 结尾增益}, tail: 尾音, sample_rate, limiter}`；
  下一段的 `build_audio_track(previous=mix_context)` 用它初始化增益包络，段边界不会重置 ducking。
- 锁音保真的验收口径：用**包络相关 + 频带结构**，不用样点相关——H3 的音频 VAE 是
  神经编解码器，解码会重建波形相位。

### 2.8 `DIRECTOR_PLAN`（schema 1）

```json
{
  "schema": "DIRECTOR_PLAN@1",
  "segments": [
    {"index": 1, "start": 0.0, "head": 0, "delivery": 124, "sample": 124, "timeline_start": 0.0}
  ],
  "total_frames": 124, "fps": 24
}
```

### 2.9 `DIRECTOR_SEGMENT`（schema 1）

```json
{
  "schema": "DIRECTOR_SEGMENT@1",
  "index": 1, "chain_key": "sha1:...",
  "resolved": { "assets": {...}, "brief": {...}, "cast": {...}, "config": {...}, "bundle_id": "...",
                "continuity": "start|guide_tail|latent_tail|none" },
  "frames": 124, "head": 0, "delivery": 124, "sample": 124,
  "images": "<IMAGE socket 附带>", "audio": "<AUDIO socket 附带>",
  "video_path": "DirectorDeck/xxx/seg_001.mp4",
  "seed": 12345, "elapsed_s": 200.3,
  "store_key": "运行期仓库 key（尾帧/尾音/素材快照，进程内存）",
  "guide": {"used": true, "head": 22, "audio": true},
  "seam": {"apply": true, "gain": 1.01, "offset": 0.004, "lowfreq": 0.003, "hard_cut": false},
  "tail": {"kind": "rgb", "frames": 22}
}
```

> **运行期数据（M2）**：segment 里不能存张量（JSON 序列化会崩），所以尾帧/尾音/素材张量
> 放在进程内 `segment_store`，segment 只带 `store_key`。ComfyUI 重启后旧 key 失效，
> 生成器会报 `DD-E008` 让用户重跑上一段（而不是悄悄生成接不上的片段）。

### 2.10 `DIRECTOR_MANIFEST`（schema 1）

```json
{
  "schema": "DIRECTOR_MANIFEST@1",
  "project": "demo", "created_at": "ISO8601",
  "config": {...}, "bundle": {...},
  "segments": [ { "index":1, "path":"...", "seed":..., "frames":..., "resolved_hash":"..." } ],
  "final": {"path": "output/DirectorDeck/demo.mp4", "frames": 396, "duration": 16.5, "audio": "locked|generated"},
  "versions": {"director_deck": "0.1.0", "comfyui": "0.46.0"}
}
```

---

## 3. Policy 枚举（**每段必须显式指定**）

- 所有 policy 的默认值 = **`unset`**；节点执行时遇到 `unset` 立即报错（`DD-E001`），不静默继承。
- 前端"添加下一段"按钮会自动填推荐值（通常是 `inherit`），并写进工作流 JSON，用户仍可改。

| 输入 | 取值 | 语义 |
|---|---|---|
| `assets_policy` | `inherit / replace / merge / clear` | `merge`=按槽位覆盖（见 §6） |
| `brief_policy` | `inherit / replace` | |
| `cast_policy` | `inherit / replace / merge_by_character` | |
| `config_policy` | `inherit / overrides` | `overrides` 需连 `DIRECTOR_CONFIG_OVERRIDE` |
| `continuity` | `start / guide_tail / latent_tail / none` | 第 1 段必须 `start`；之后 `guide_tail`（RGB 尾帧引导）或 `latent_tail`（latent 尾 token 续写，0.2.1 起）或 `none` |
| `bundle_policy` | `provided / inherit` | 第 1 段推荐 `provided`（也可 `inherit` 取全局默认）；之后必须 `inherit` |

> **基线（baseline）定义**：解析字段的"沿用"目标 = 上一段 resolved 结果；**第 1 段没有上一段时 = 链首全局默认**。
> 因此 `inherit` 在任何段都合法（第 1 段取全局默认），不会出现"空继承"。

**特例**：`clear`/`none` 不需要连接输入；其余显式覆盖策略必须连接对应输入，否则 `DD-E002`。

---

## 4. 解析算法（`core/policy.resolve_segment`）

```
输入:
  index: int                      # 0 起
  policies: dict[str,str]         # 6 个 policy
  sockets: dict[str,Any]          # 已连接输入（None=未连接）
  previous: Resolution | None     # 上一段解析结果
  defaults: dict[str,Any]         # config/bundle 全局默认
输出:
  Resolution { assets, brief, cast, config, bundle, continuity, guide }
```

步骤：

1. **校验**：所有 policy ≠ `unset`（`DD-E001`）；合法的组合（`DD-E004` 段级模型/policy 越界）。
2. **bundle**：`index==0` 允许 `provided`（连接 ModelLoader）或 `inherit`（取全局默认，缺则 `DD-E005`）；`index>0` 必须 `inherit`，沿用 previous.bundle。
3. **config**：`inherit`→previous.config（首段→defaults）；`overrides`→在允许子集内合并（`DD-E006` 非法字段）。
4. **assets**：
   - `inherit`：有上一段→`previous.assets`；第 1 段→`defaults.assets`；都没有→空
   - `replace`：必须连接
   - `merge`：必须连接；按槽位覆盖（§6）
   - `clear`：空 bundles
5. **brief**：`inherit`→previous.brief（首段→`defaults.brief`，可为空）；`replace`→必须连接。
6. **cast**：同上；`merge_by_character` 按 `role.id` 覆盖（`DD-E007` 角色不存在时警告）。
7. **continuity**：`index==0` 只允许 `start`；`>0` 允许 `guide_tail`（RGB 尾帧+尾音 AddGuide）/ `latent_tail`（直接搬上一段 latent 尾部 token 并 mask=0）/ `none`；两种“接上一段”模式在 previous 为空时都报 `DD-E008`。
8. 生成 `resolved_hash = sha1(canonical_json(resolved))`，供缓存使用。

---

## 5. 帧数学契约（`core/frames.py`）

```
grid_length(seconds)   = round((max(5, seconds*24) - 5) / 17) * 17 + 5
grid_round_up(v)       = 最小满足 x >= v 且 x % 17 == 5 的 x
context_frames(handoff)= 5/22/39/56 中第一个 >= handoff（夹到 5..56）
segment_plan(index)    = index==0 ? (head=0, sample=grid_length)
                                   : head=context_frames(handoff),
                                     sample=grid_round_up(grid_length+head),
                                     delivery=sample-head
timeline_start[i]      = sum(delivery[0..i-1]) / 24
```

验收示例：5s、handoff=22 → 段1 `124/124/124`；段2 `head=22, sample=158, delivery=136`；与 AICG3D 13 号实测一致。

---

## 6. 素材槽位与引用契约（`core/assets.py`）

- 固定槽 1..9（`AssetSlot.slot` 即 `@图片N` 的 N）；空槽合法。
- `merge(base, override)`：`override.slots[i]` 非空则替换；`override` 空槽不动 base（要清空用 `clear`/`replace`）。
- 引用解析：`@图片N` / `@音频N` / `@视频N`；越界引用 → `DD-E010`；引用空槽 → `DD-E011`。
- 提示词生成：`@图片N` → `<Picture N>`；绑定后按出现顺序重编号（可选，默认保持原号）。

---

## 7. 剧本解析契约（`core/script.py`）

- 模式：`auto / header / blank / divider / line / regex`。
- 自动：标题（第N段、镜头N、Shot N、N.）> 分隔线（`---`）> 空行 > 整段。
- 时长：`（5秒）`、`5s`、`0:05`；未标则用 `default_seconds`。
- 对白：`角色: 台词`、`角色：台词`、`「台词」`（前者含角色时绑定角色）。
- 素材引用：正文 `@图片N` 写入该段 `refs`。
- 输出 `Script.raw/segments/warnings`，段数上限默认 64。

---

## 8. 缓存/抽卡指纹与画面级复用（0.2.2）

### 8.1 指纹（`core/cache.py`）

```
segment_fingerprint = "sha1:" + sha1(canonical_json({
  cache_schema,             # 缓存格式版本，升级自动失效
  resolved_hash,            # §4.8（含 bundle/config/assets/brief/cast/continuity）
  prompt, mode,             # 最终提示词 / t2va|ref2va
  width, height, length,    # 画布与采样帧数
  seed,                     # 解析后的种子（seed=0 时节点内先随机定下来）
  sampler, scheduler, steps, denoise, sigmas, interpolate,
  continuity, guide_prev,   # 引导模式与上一段 store_key
  lock                      # 锁音签名：applied/roles/window + audio_hash（每路波形哈希）
}))
```

### 8.2 磁盘缓存（`adapters/segment_cache.py`）

- 目录：`output/DirectorDeck/cache/segments/seg_<32hex>.{mp4,npz,json}`
- `mp4`：画面（h264 CRF 12 / yuv420p，约 1–3MB/段；有轻微重编码误差，见 CHANGELOG）
- `npz`：音轨 float、latent 尾部（latent_tail 续写用）、锁音源轨（audio_from_source 用）
- `json`：段结果元数据 + 画面尺寸（读回解码用）
- `SegmentCache.mode`（生成器控件）：`auto`=命中复用、未命中生成并写；`off`=不读不写；`reroll`=无视命中、重新生成并覆盖。
- **锁音内容哈希**：`lock.audio_hash` 由每路角色实际波形算出（0.2.5+）。TTS 每次生成可能不同，
  只按角色名/时间轴缓存会错误复用旧声音；`cache_schema>=2` 必须带它。
- 命中时跳过：条件构造、采样、VAE 解码；下游的续写/锁音/无损混流仍可用（运行期仓库会从缓存补齐）。
- 载入失败/损坏/版本不符一律按“未命中”处理，不影响正常出片；写盘失败也不影响出片（错误码 `DD-E040` 仅用于显式 I/O 失败）。

### 8.3 失效规则

- 段 N 的输入/resolved/种子/引导来源任一变化 → 指纹变 → 自动重新生成。
- `cache_schema` +1 → 所有旧缓存失效。
- 重抽段 N：N+1 的 `guide_prev`（=段 N 的 store_key）变化 → 自动跟着重跑。

---

## 9. 节点契约表（16 节点 v0.1）

| # | node_id | 输出 | 关键输入（required / optional） |
|---|---|---|---|
| 1 | `DirectorDeck_ModelLoader` | BUNDLE | fl2va/ref2va/TE/video_vae/audio_vae（COMBO）、lora_1..9、strength_1..9、vram_tier |
| 2 | `DirectorDeck_DirectorConfig` | CONFIG | width/height/aspect_ratio/segment_seconds/handoff_frames/sampler/sigmas/interpolate/denoise/seed_strategy/seed_base/preview/vram_policy/output_dir/seam_enabled/seam_window/seam_max_add/seam_gain_limit |
| 3 | `DirectorDeck_AssetShelf` | ASSETS | slots 1..9（IMAGE 可选）、audio_1..3（AUDIO 可选）、@引用说明 |
| 4 | `DirectorDeck_ScriptDesk` | SCRIPT | text、mode、default_seconds、max_segments、keep_header |
| 5 | `DirectorDeck_SegmentBrief` | BRIEF | text、seconds、dialogue（多行）、refs |
| 6 | `DirectorDeck_VoiceLock` | CAST + STRING | roles（多行“角色: 槽号, 起始秒, 增益dB, 优先级”）、lock_audio、mix_mode(auto_duck/priority/sum)、duck_db、attack_ms、release_ms、audio_1..3（可选 AUDIO） |
| 7 | `DirectorDeck_FramePlanner` | PLAN + STRING | script、config、keep_full（可选） |
| 8 | `DirectorDeck_ContinuityGuide` | CONDITIONING/IMAGE | **已并入 DirectorTake**：`continuity=guide_tail` 走 RGB 尾帧+尾音 AddGuide；`continuity=latent_tail` 直接搬上一段 latent 尾部 token（0.2.1），都不需要独立节点 |
| 9 | `DirectorDeck_DirectorTake` | SEGMENT + IMAGE + AUDIO | bundle、config、script、continuity、segment_index、seed、cache_mode(auto/off/reroll) + optional: previous_segment、assets、brief、cast |
| 10 | `DirectorDeck_SeamFixer` | IMAGE + STRING | prev_images、cur_images、cur_head + optional: enabled、window、max_add、gain_limit |
| 11 | `DirectorDeck_SegmentCache` | SEGMENT + STRING | segment、mode(status/store/clear)、scope（可选） |
| 12 | `DirectorDeck_Refiner` | SEGMENT + IMAGE + AUDIO | bundle、segment、images、audio + optional: mode(latent_2nd/lanczos2x)、denoise、steps、sampler_name、scheduler、upscale |
| 13 | `DirectorDeck_FinalCut` | IMAGE + AUDIO + MANIFEST | segment_1/images_1/audio_1（必填）+ segment_2..4/images_2..4/audio_2..4（可选）+ save_manifest、audio_from_source、audio_crossfade_ms（0.2.4） |
| 14 | `DirectorDeck_OutputLibrary`（可选） | path+FILE | segment/manifest、dir、naming |
| 15 | `DirectorDeck_PromptSmith`（可选） | STRING | template/task、remote provider（默认关） |
| 16 | `DirectorDeck_DirectorRunner`（M4，可选） | ALL | plan/config、run_mode |
| 17 | `DirectorDeck_TTSBooth`（0.5.0） | CAST + AUDIO×3 + STRING + FLOAT + INT + STRING | breeze_model（BREEZE_TTS2_MODEL）、lines（`角色 [@起始秒] \| 音色描述 \| 台词`）、auto_start、auto_split、pause_ms、chars_per_second、max_seconds、mix_mode/duck_db/attack_ms/release_ms、Breeze 生成参数（cfg_scale/max_new_tokens/temperature/top_k/top_p/repetition_penalty/depth_*/seed）；输出 `total_seconds`、`segment_count`、`plan`；**超长只提醒不缩句**，多段复用同一份 CAST；**可选依赖 ComfyUI-Breeze-TTS-2**，缺包报 `DD-E050` |

参数顺序规则：**只追加**；`*_policy` 放在对应输入旁；旧 ID 提供别名。

---

## 10. 错误码

| code | 含义 |
|---|---|
| `DD-E001` | policy 未指定（unset） |
| `DD-E002` | 显式覆盖策略但输入未连接 |
| `DD-E003` | （保留，当前未使用）历史错误码：首段 inherit 曾视为非法；现按「基线=全局默认」处理 |
| `DD-E004` | policy 组合非法（段级模型 / continuity 越界） |
| `DD-E005` | 第 1 段必须 provided bundle |
| `DD-E006` | config overrides 含非安全字段 |
| `DD-E007` | merge_by_character 角色不存在（警告级） |
| `DD-E008` | guide_tail 但无上一段 |
| `DD-E010` | 素材引用越界（@图片N > 9） |
| `DD-E011` | 引用素材为空槽/文件缺失 |
| `DD-E020` | 帧长不是 17k+5 |
| `DD-E021` | 宽高不是 32 倍数 |
| `DD-E030` | 数字人锁音：音轨缺失/长度不匹配 |
| `DD-E031` | 链内 bundle 不一致 |
| `DD-E050` | TTS 节点不可用（未安装 ComfyUI-Breeze-TTS-2，或台词表格式错误） |

---

## 11. 版本与迁移

- 类型 JSON 带 `schema`；加载旧版本时走 `core/migrate.py` 逐版本升级。
- 节点参数只追加；删除字段时保留解析但标 deprecated。
- 发布后节点 ID 不合并、不改名；旧 ID 保留别名映射。
- 主版本升级（类型不兼容）写迁移脚本 + 在 release notes 给出。

## 12. 未决问题

- Registry PublisherId 注册与首发（`shuffleman`）；
- latent 尾帧续写（D3 后半）与抽卡画面级复用；
- 多角色音频混音的自动 ducking（M4 后可选）。

## 13. 前端与工作流（M4/M5）

### 13.1 前端扩展

- 文件：`director_deck/web/directordeck.js`；由根 `__init__.py` 的 `WEB_DIRECTORY` 暴露，
  访问路径 `/extensions/DirectorDeck/directordeck.js`。
- 只依赖 `app` / `api` / `LiteGraph` 公开接口；浮动面板按钮：
  添加下一段 / 加素材覆盖 / 加数字人锁音 / 加段级剧本 / 重抽选中段 / 查看段清单 / 帮助。
- 自动接线约定：添加下一段 = 复制 bundle/config/script 上游 + 接 previous_segment +
  policy 填 `inherit×5 + guide_tail`；覆盖节点 = 创建后把对应 policy 切 `replace`。

### 13.2 后端路由（只读）

| 方法/路径 | 返回 |
|---|---|
| `GET /directordeck/health` | `{ok, time, version}` |
| `GET /directordeck/segments?limit=N` | 最近 N 条段元数据（含 `lock`/`seam`/`refine` 字段） |
| `GET /directordeck/manifests?limit=N` | 最近 N 条成片清单 |

### 13.3 画布工作流（UI 0.4）

| 文件（examples/ui/） | 对应 API 示例 |
|---|---|
| `DirectorDeck_M1_单段闭环.json` | `m1_single_segment_api.json` |
| `DirectorDeck_M1_参考生视频.json` | `m1_ref2va_api.json` |
| `DirectorDeck_M2_三段链.json` | `m2_chain_api.json` |
| `DirectorDeck_M3_数字人锁音.json` | `m3_digital_human_api.json` |
| `DirectorDeck_M4_锁音无损.json` | `m4_lock_finalcut_api.json` |
| `DirectorDeck_M5_latent续写.json` | `m5_latent_chain_api.json`（0.2.1） |
| `DirectorDeck_M6_多角色混音.json` | `m6_mix_rules_api.json`（0.2.3） |
| `DirectorDeck_M8_TTS锁音.json` | `m8_tts_lock_api.json`（0.2.5） |
| `DirectorDeck_M9_台词表配音.json` | `m9_tts_booth_api.json`（0.3.0） |
| `DirectorDeck_M10_台词自动排期.json` | `m10_tts_auto_api.json`（0.4.0） |

生成与校验：`python tools/make_ui_workflows.py [server]` —— 从运行中 ComfyUI 拉 `object_info`，
按真实控件顺序生成 `widgets_values`，再用 `ui_to_api()` 反向还原并与 API 示例逐输入比对
（PASS 才算生成成功）。
