# 漫剧老李 AIGC 全流程 Skill（预置副本）

- 来源：https://github.com/lixiaoxiao9888-create/manju-laoli-skill
- 版本：V8.2.0-SLIM（README 标注）
- 提交：`5b7befe9d5ecde9ee4e624adf4456d4fe89aca2f`
- 许可：MIT（见本目录 LICENSE）
- 预置内容：11 个 skill 的 `SKILL.md` + `references/`
  （未包含 scripts/assets/CI；编剧台只读 Markdown 规则，不需要脚本）。

## 子技能列表

- `manju_laoli/sd-asset-engine`
- `manju_laoli/sd-combat-engine`
- `manju_laoli/sd-decision-engine`
- `manju_laoli/sd-feed-engine`
- `manju_laoli/sd-qc-engine`
- `manju_laoli/sd-real-engine`
- `manju_laoli/sd-recon-engine`
- `manju_laoli/sd-script-engine`
- `manju_laoli/sd-storyboard-engine`
- `manju_laoli/sd-xuanhuan-engine`
- `manju_laoli/short-drama-director`

## 用法

在「编剧台」的 skill 下拉框选择 `manju_laoli/<子技能>`：
- 只要创作规则：`include_refs=False`（默认）；
- 需要扩展资料：打开 `include_refs`，并用 `max_context_chars` 控制上下文大小
  （主控 SKILL.md 本身约 7.6 万字符，建议 6 万~12 万，超长会截断）。
