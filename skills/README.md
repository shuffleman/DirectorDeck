# DirectorDeck Skills

这个目录放「编剧/导演规则包」，供 `DirectorDeck_ScriptSmith`（编剧台）加载。

## 已预置

| 目录/ID | 内容 |
|---|---|
| `directordeck_screenwriter` | DirectorDeck 自带的精简短剧编剧规则 |
| `manju_laoli/<子技能>` | 漫剧老李 AIGC 全流程 Skill V8.2.0-SLIM：主控 `short-drama-director` + 10 个 `sd-*-engine`（带 references，共 143 个文件，约 2.7MB；MIT，见 `manju_laoli/LICENSE` 与 `NOTICE.md`） |
| `minimax_h3_v6` | MiniMax H3 分段无限视频生成提示词模板 V6（含 `NOTICE.md` 来源说明） |

编剧台 skill 下拉框会直接列出这些项；漫剧老李主控 SKILL.md 约 7.6 万字符，
默认 `max_context_chars=60000` 会截断，需要完整规则时调大该值（注意模型上下文窗口）。

## 目录结构

一个 skill 可以是一个目录：

```
skills/
  my_skill/
    SKILL.md          # 必须：主规则（可带 YAML frontmatter：name/description）
    references/       # 可选：扩展资料（include_refs=true 时一起塞进上下文）
      xxx.md
```

也可以直接放一个单文件 `.md`（当成单文件提示词模板，比如 MiniMax H3 V6 模板）。

## 导入外部 skill

```powershell
# 目录式 skill（例如 manju-laoli 的 short-drama-director）
python tools/import_skill.py <repo>/short-drama-director

# 单文件提示词模板（例如 V6 模板 .md）
python tools/import_skill.py "F:\AI-Video\Test\MiniMax H3 分段无限视频生成提示词模板 V6.md" --name minimax_h3_v6
```

导入后重启 ComfyUI，在编剧台的 `skill` 下拉框里选择。

## 注意

- skill 是“规则参考”，**最终输出格式以节点追加的《输出契约》为准**；
- 单文件 skill 和目录 skill 都支持；`references/` 越大越吃上下文，可在节点上关掉
  `include_refs` 或调小 `max_context_chars`；
- 内置 `directordeck_screenwriter` 是 DirectorDeck 自带的短剧编剧规则，可直接用。
