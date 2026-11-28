# NOTICE

`directordeck-screenplay-studio` 是 **DirectorDeck 专用的重构 skill**，不是漫剧老李套装的完整副本。

## 来源与改编说明

### 1. 漫剧老李 AIGC 全流程 Skill V8.2.0-SLIM

- 来源：`manju-laoli-skill-main/`（1 总控 `short-drama-director` + `sd-*` 子技能）；
- 许可：MIT License（见 `LICENSE-manju-laoli`）；
- 本 skill 参考/改写的内容：
  - 短剧结构、开场钩子、升级/反转/悬念节奏；
  - 人物欲望/阻力/关系与台词口语化；
  - 分镜/景别/运镜、空间与连续性；
  - 动作/打戏的“一段一回合、受力结果”写法；
  - 资产三清单（角色/场景/道具）、素材形态与交付质检思路。
- **未包含/已删除**（因为与 DirectorDeck 无关或会冲突）：
  - Seedance 2.5/2.0 模型锁、七段式投喂格式、15 秒段规则；
  - `图N` / `@CHR-` / `@SCN-` / `@PRP-` 编号体系；
  - 打戏三引擎的超长招式/参考库、五席圆桌完整流程、平台风控细则；
  - 套装总控的五道前置锁（本 skill 改为 DirectorDeck 自己的交付锁定）。
- 本 skill 中的创作规则是**面向 DirectorDeck 5 秒/段、9 图槽的精简重构**，与漫剧老李原版不逐条对应；
  需要完整 Seedance 流程时，请使用原套装。

### 2. MiniMax H3 分段无限视频生成提示词模板 V6

- 来源：用户提供的本地文件 `MiniMax H3 分段无限视频生成提示词模板 V6.md`；
- 许可：原文件未标明，按“用户自有资料”只参考其格式约定：
  `【第N段｜X秒】`、`<d>` 只放实际台词、`<Picture N>` 作为素材引用；
- 本 skill 的 H3 V6 契约以 **DirectorDeck 导入器的实际解析规则**为准，不复制模板全文。

### 3. DirectorDeck

- 交付格式、导入参数、`@图片N` 槽位、M13/M16 画布接法、校验器来自 DirectorDeck 仓库（AGPL-3.0）；
- 仓库：https://github.com/shuffleman/DirectorDeck

## 许可

- 本 skill 整体随 DirectorDeck 以 **AGPL-3.0** 发布（见 `LICENSE`）；
- 改编自漫剧老李的 MIT 部分，其 MIT 许可证与版权声明见 `LICENSE-manju-laoli`；
  按 MIT 要求保留版权与许可声明。
- 如果单独分发本 skill，请同时保留 `NOTICE.md`、`LICENSE`、`LICENSE-manju-laoli`。
