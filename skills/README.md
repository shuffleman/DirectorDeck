# DirectorDeck Skills

这个目录放**独立 agent skill**，不参与 ComfyUI 节点运行，也不依赖 `DirectorDeck_ScriptImport` 之外的任何东西。

当前只有一个：

| 目录 | 作用 |
|---|---|
| `directordeck-screenplay-bridge/` | 把任意来源的剧本草稿整理成 DirectorDeck「剧本导入」可用的外部剧本（DirectorDeck 文本 / JSON / H3 V6），并做分段/台词/素材槽校验 |

## 它解决什么问题

DirectorDeck 已经去掉了“生成剧本”的节点，剧本从外部生成后导入。
但外部创作 skill（短剧、漫剧、小说、分镜）通常输出自己的格式，不能直接粘贴进
`DirectorDeck_ScriptImport`。这个 skill 是两者之间的**交付适配层**：

```
创作 skill / 用户 ──→ [DirectorDeck 剧本交付桥] ──→ 剧本导入节点
                        只做格式、分段、台词长度、素材槽校验
```

## 为什么不会和其他 skill 冲突

1. **唯一命名空间**：`directordeck-screenplay-bridge`，不用 `screenwriter` / `story` /
   `drama` / `novel` 这类通用名；
2. **窄触发**：只认 `DirectorDeck`、`剧本导入`、`@图片N`、`H3 V6` 等交付信号；
   单纯“写剧本/写小说/写分镜”不会触发；
3. **职责隔离**：创作内容（题材/角色/剧情/文风/结局）完全交给其他 skill；
   本 skill 只做交付格式；
4. **冲突裁决写死**：用户 > 其他创作 skill 的内容 > 本 skill 的格式；
   格式装不下时拆段/拆句，不删剧情、不改角色；
5. **不抢写文件**：默认只输出文本/报告；用户给路径才保存。

详见 `directordeck-screenplay-bridge/references/coexistence-rules.md`。

## 安装到 agent

这是标准 `SKILL.md` 结构，可用于支持 Agent Skills 的 agent。把它放到对应
skill 目录即可（不同工具路径不同，常见如 `~/.claude/skills/`、`~/.dsh/skills/`）：

```bash
# 示例：Claude Code 风格
cp -r skills/directordeck-screenplay-bridge ~/.claude/skills/

# 示例：Windows
xcopy /E /I skills\directordeck-screenplay-bridge "%USERPROFILE%\.claude\skills\directordeck-screenplay-bridge"
```

也可以不安装，直接把 `SKILL.md` 内容作为系统提示/子 agent 指令使用。

> 注意：ComfyUI 的 `DirectorDeck` 节点不会加载这个目录；它只是给写剧本的 agent 用的规则包。

## 一起用（推荐流程）

1. **创作阶段**：使用你已有的短剧/漫剧/小说/分镜 skill 产出故事、人物、分场、台词；
2. **交接阶段**：把创作稿 + 交付参数（格式、段长、总时长、素材槽）交给本 skill；
3. **交付阶段**：本 skill 输出可直接粘贴进 `DirectorDeck_ScriptImport` 的剧本；
4. **校验阶段**：运行独立校验器：

```bash
python skills/directordeck-screenplay-bridge/scripts/validate_screenplay.py 剧本.txt --format auto
```

退出码 0=通过（可能有 warning），1=有 error。`--json` 输出机器可读报告。

## 文件结构

```
skills/
  README.md
  directordeck-screenplay-bridge/
    SKILL.md                     # 主规则（触发、共存契约、交付规则）
    references/
      directordeck-formats.md    # 三种导入格式的精确契约与示例
      coexistence-rules.md       # 与其他 skill 的冲突裁决
      handoff-schema.md          # 创作 skill → 交付桥的交接字段
    scripts/
      validate_screenplay.py     # 独立格式校验器（纯标准库）
```

## License

本 skill 与 DirectorDeck 仓库一致：AGPL-3.0。
