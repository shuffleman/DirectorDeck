# DirectorDeck 交付契约（剧本导入 / 素材槽 / 画布接法）

> 本文件是 `directordeck-screenplay-studio` 的交付规则。创作规则见 `short-drama-craft.md`。
> 最终交付必须能被 `DirectorDeck_ScriptImport` 直接解析；不要输出 Seedance 投喂稿或 `图N` 编号。

## 一、导入节点参数

| 参数 | 说明 |
|---|---|
| `script` | 粘贴剧本文本 |
| `format` | `自动识别` / `DirectorDeck 剧本` / `JSON 剧本` / `H3 V6 文本` |
| `segment_seconds` | 文本没写秒数时的默认段长（默认 5.0） |
| `match_assets` | 自动匹配素材库图片槽 |
| `match_scenes` | 把场景关键词匹配到场景槽 |
| `min_score` | 匹配阈值（默认 0.55） |
| `assets` | 可选，接 `DirectorDeck_AssetShelf` |
| `cast` | 可选，接 `DirectorDeck_VoiceLock` |

自动识别顺序：JSON（`{` 开头或含 `"segments"`）→ H3 V6（有 `【第N段`）→ DirectorDeck 文本。
解析失败报 `DD-E061`。

## 二、DirectorDeck 文本（默认）

```text
第1段（5秒）
[画面] 雨夜，女主撑着伞站在老宅台阶下，男主从门内走出 @图片1
女主：你终于回来了。
男主：这十年，我一直在找你。

第2段（5秒）
[画面] 两人在雨中对视，镜头缓慢推近女主的脸 @图片1 @图片2
女主：先进屋吧。
```

规则：

- 段头 `第N段（X秒）`，N 连续；也接受“第N幕/镜/场”，但交付统一写“段”；
- 秒数 1–60，可小数；≤64 段；
- 段间空行；
- 对白：`角色：台词`；角色名 1–12 字符，不含空格/冒号/引号；
- 动作/运镜：独立行，推荐 `[画面]` 开头；动作行开头不要写 `角色：`，否则会被当对白；
- `@图片N`（N=1..9）任意位置；会进入该段 refs；
- 不要 Markdown 代码围栏。

## 三、JSON 剧本

```json
{
  "title": "雨夜重逢",
  "language": "中文",
  "characters": [
    {"id": "S1", "name": "女主", "image_slot": 1, "audio_slot": 1, "voice": "清冷年轻女声"},
    {"id": "S2", "name": "男主", "image_slot": 2, "audio_slot": 2, "voice": "低沉疲惫男声"}
  ],
  "segments": [
    {
      "index": 1,
      "seconds": 5.0,
      "scene": "老宅台阶，雨夜",
      "actions": "女主撑伞站在台阶下，男主从门内走出",
      "image_refs": [1, 2],
      "dialogue": [
        {"character": "女主", "text": "你终于回来了。", "at": 0.6},
        {"character": "男主", "text": "这十年，我一直在找你。", "at": 2.4}
      ]
    }
  ]
}
```

字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `characters[].name` | 建议 | 角色名 |
| `characters[].image_slot` | 可选 | 1–9；不填交给自动匹配 |
| `characters[].audio_slot` | 可选 | 1–9；TTS/锁音用 |
| `characters[].voice` | 可选 | 音色描述 |
| `segments[].seconds` | 建议 | 1–60 |
| `segments[].scene` | 可选 | 场景 |
| `segments[].actions` | 建议 | 画面/动作/运镜 |
| `segments[].image_refs` | 可选 | 1–9 的槽数组 |
| `segments[].dialogue[]` | 可选 | `{character, text, at?}`，`at` 为段内秒 |

不要输出 JSON 注释/尾逗号/围栏；至少一段。

## 四、H3 V6 文本

```text
【第1段｜5秒】
雨夜，女主撑着伞站在老宅台阶下，男主从门内走出。
(S1) 女主抬头看向他 <d>[克制] 你终于回来了。</d>
(S2) 男主停在门口 <d>这十年，我一直在找你。</d>
<Picture 1> <Picture 2>

【第2段｜5秒】
两人在雨中对视，镜头缓慢推近女主的脸。
(S1) <d>先进屋吧。</d>
<Picture 1>
```

规则：

- 段头 `【第N段｜X秒】`；N 连续；秒数 1–60；≤64 段；
- 对白 `(S1) 描述 <d>台词</d>`；`<d>` 内只放实际台词，可带 `[情绪]`；
- `<Picture N>` 仅 1–9；
- `integrated_multimodal_description` 等行会作为画面描述保留；
- 适用场合：用户明确要 H3 V6 提示词，或已有 V6 文本要导入 DirectorDeck；
- 不要把 V6 的 `<Picture N>` 写进 DirectorDeck 文本（DirectorDeck 文本用 `@图片N`）。

## 五、素材槽与自动匹配

- 槽位固定 1..9，`@图片N` 对应 AssetShelf 第 N 槽；
- 素材库为空/没接时写 `@图片N` 会触发 `DD-E011`；
- 不想手动绑定就完全不写 `@图片N`，让导入器按角色/场景名匹配；
- 要绑就全篇固定：同一角色同一槽；不给两个身份角色复用同一图；
- 音频槽只用于 TTS/锁音，不要和图片槽混用编号；
- 素材不够时报告缺口，不要猜槽号。

## 六、声音与锁音（可选）

H3 本身会生成音轨；需要更可控的配音时：

1. 用 `DirectorDeck_TTSBooth` 生成 CAST + 台词音频；
2. 或 `LoadAudio`/外部音频 → `DirectorDeck_VoiceLock`；
3. 把 CAST 接到视频生成器的 `cast` 输入；
4. 台词表格式：`角色 @起始秒 | 音色描述 | 台词`；起始秒可留空由 TTSBooth 自动排期；
5. 锁音模式下，视频生成器会按段窗口自动裁切音频。

剧本里的角色名必须与 CAST 角色名一致。

## 七、画布接法（M13 / M16）

### M13 剧本导入（推荐从这开始）

1. `DirectorDeck_ScriptImport` 粘贴剧本；
2. 接 `AssetShelf`（可选）；
3. 选中剧本导入节点，面板点 **按剧本建生成器**；
4. 点 **补全合并输出** 生成合并器 + 视频输出；
5. 运行；需要二采/RelayVSR 时改接 `DirectorDeck_FinalRefine`。

### M16 完整工作流（推荐从剧本到成片）

1. 剧本替换 `DirectorDeck_M16_完整工作流.json` 里剧本导入节点的 `script`；
2. 参考图换成自己的（`11.png` / `睡衣.png` 只是示例）；
3. 运行两段生成器；
4. 节点上逐个预览；
5. 点合并器 **🎬 手动合并本片**；
6. 点二次处理成片 **🎬 生成最终视频**（默认二采 + RelayVSR 2x）。

## 八、字段/节点对应表

| 剧本里的东西 | DirectorDeck 节点/参数 |
|---|---|
| 总段数 | 视频生成器数量、`segment_count` |
| 每段秒数 | 段头 `（X秒）`；全局配置 `segment_seconds` |
| 角色/场景图槽 | `AssetShelf` 的 `image_1..9`；`@图片N` |
| 角色音色 | `VoiceLock.cast` / `TTSBooth.cast` |
| 单段画面 | 视频生成器从 `script` 取对应段 |
| 段间连续性 | `previous_segment` + `continuity` |
| 最终成片 | `FinalCut` → `FinalRefine`（手动触发） |

## 九、交付前校验

```bash
python skills/directordeck-screenplay-studio/scripts/validate_screenplay.py 剧本.txt --format auto
```

检查：段号/秒数/段数、台词长度、动作行误判、`@图片N` 越界、代码围栏、JSON/V6 结构。
退出码 0=无 error；warning 不阻断，但要人工确认。
