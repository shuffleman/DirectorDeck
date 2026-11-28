# DirectorDeck 剧本工坊 Skill

这个目录放**独立 agent skill**，不参与 ComfyUI 节点运行，也不依赖 DirectorDeck 节点之外的运行时。

当前只有一个，**取代之前的 `directordeck-screenplay-bridge`**：

| 目录 | 作用 |
|---|---|
| `directordeck-screenplay-studio/` | DirectorDeck 专用剧本工坊：创作 → 分段 → 台词/镜头 → 资产槽 → 导入格式 → 质检 |

## 它是什么

一个**单 skill 覆盖全流程**的 DirectorDeck 剧本工坊：把创意、小说、大纲或外部剧本，
重构成可直接导入 DirectorDeck 的分段剧本。

它把几套规则压缩成一份：

- 短剧结构、开场钩子、升级/反转/悬念；
- 人物欲望/阻力、台词口语化；
- 镜头/动作/连续性、5 秒段写法；
- 资产三清单与 `@图片N` 素材槽；
- DirectorDeck 文本 / JSON / H3 V6 三种交付格式；
- 交付前独立校验器；
- M13/M16 画布的接法。

不是 Seedance 投喂工具，不输出七段式、`图N`/`@CHR-` 体系。

## 安装到 agent

标准 `SKILL.md` 结构，可放到支持 Agent Skills 的 agent 的 skill 目录：

```bash
# 示例：Claude Code 风格
cp -r skills/directordeck-screenplay-studio ~/.claude/skills/

# Windows
xcopy /E /I skills\directordeck-screenplay-studio "%USERPROFILE%\.claude\skills\directordeck-screenplay-studio"
```

也可以直接把 `SKILL.md` 作为系统提示/子 agent 指令使用。

> ComfyUI 的 DirectorDeck 节点不会加载这个目录；它只给写剧本的 agent 用。

## 怎么用

1. 对 agent 说清：**交付 DirectorDeck 剧本**、总时长/段数/画幅、角色、素材槽、是否需要锁音；
2. 让 agent 按 skill 的六阶段流程：定方向 → 故事脊柱 → 人物/资产 → 分段计划 → 正式剧本 → 质检；
3. 拿到最终稿后，粘贴进 `DirectorDeck_ScriptImport`（或 M16 工作流的剧本节点）；
4. 有需要时跑校验：

```bash
python skills/directordeck-screenplay-studio/scripts/validate_screenplay.py 剧本.txt --format auto
```

退出码 0=通过（可有 warning），1=有 error。`--json` 输出机器可读报告。

## 和漫剧老李 / Seedance 的边界

目录 `F:\AI-Video\剧本生成` 里可能同时有漫剧老李套装和 H3 V6 模板：

- **Seedance 投喂 / `图N` / 七段式** → 用漫剧老李，本 skill 不接管；
- **DirectorDeck 导入 / `@图片N` / 第N段** → 用本 skill；
- 两边都要 → 拆两份文件，不混编号；
- H3 V6 模板负责提示词本体，本 skill 只在“要导入 DirectorDeck”时做解析/校验；
- 目标不明确时先问，不要默认选边。

`sd-feed-engine` 禁用 `@图片N`，DirectorDeck 又必须用 `@图片N`——这是平台差异，
同一份稿只能服务一个平台。

## 文件结构

```
skills/
  README.md
  directordeck-screenplay-studio/
    SKILL.md
    NOTICE.md                     # 漫剧老李 MIT / V6 模板来源说明
    LICENSE                       # AGPL-3.0（随 DirectorDeck）
    LICENSE-manju-laoli           # MIT（改编部分）
    references/
      short-drama-craft.md        # 短剧结构/台词/镜头/打戏/连续性
      directordeck-delivery.md    # 三种导入格式、素材槽、TTS、M13/M16 接法
      qc-checklist.md             # 交付前质检清单
    scripts/
      validate_screenplay.py      # 独立格式校验器（纯标准库）
```

## 为什么不会和别的 skill 冲突

1. 唯一名称 `directordeck-screenplay-studio`；
2. 窄触发：只认 DirectorDeck 交付目标，不认泛泛的“写剧本/写小说”；
3. 不输出 Seedance 格式，不碰 `图N` 体系；
4. 旧 bridge skill 已合并进本 skill 并移除，避免两个 DirectorDeck skill 抢触发；
5. 漫剧老李等创作套装的 Seedance 流程原样保留，按目标平台二选一。

## License

- 本 skill 随 DirectorDeck：AGPL-3.0（见 `LICENSE`）；
- 改编自漫剧老李的 MIT 部分：见 `LICENSE-manju-laoli` 与 `NOTICE.md`。
