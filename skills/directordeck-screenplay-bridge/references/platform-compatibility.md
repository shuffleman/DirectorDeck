# 与 manju-laoli 套装 / H3 V6 模板的兼容说明

这个文件针对实际目录 `F:\AI-Video\剧本生成` 里的另外两套东西：

- `manju-laoli-skill-main/`：漫剧老李 V8.2.0-SLIM（1 总控 `short-drama-director` + 10 个 `sd-*` 子技能）；
- `MiniMax H3 分段无限视频生成提示词模板 V6.md`：H3 的 V6 提示词模板（不是 skill，是模板）。

本 skill 与它们**没有重名、没有同路径文件冲突**；真正需要处理的是“交付层重叠”：

| 维度 | 本 skill | manju-laoli / sd-feed | 处理 |
|---|---|---|---|
| 目标平台 | DirectorDeck 剧本导入 | Seedance 2.5/2.0 投喂稿 | **按交付目标二选一** |
| 素材编号 | `@图片1..9` | `图N` / `@CHR-` / `@SCN-` / `@PRP-`；**明确禁用 `@图片N`** | 不混用；见下方 |
| 分段 | 第N段（X秒），1–60s，≤64 段 | Seedance 15 秒段/七段式投喂稿 | 不跨平台套规则 |
| 交付层 | 只做 DirectorDeck 导入格式 | `sd-feed-engine` 是 Seedance 投喂层 | 同一份稿只能有一个交付层 |
| 创作 | 不负责 | 总控 + `sd-*` 负责 | 本 skill 不抢创作 |

## 一、硬冲突只有一条：素材编号

`sd-feed-engine` 的“术语口径（最高优先级）”明确写着：

> 素材编号统一「图N」……禁用：`@图片N` / `@ImageN` / `@Video N` / `@Audio N`……

而 DirectorDeck 的导入契约要求 `@图片N`（对应 AssetShelf 第 N 槽）。

**这不是谁对谁错，而是两个平台写法不同。** 同一份稿不能同时满足：

- 目标 = Seedance：用 manju 的 `图N`，本 skill 不接管；
- 目标 = DirectorDeck：用 `@图片N`，`sd-feed-engine` 不接管；
- 两个都要：交付**两份文件**，明确标注，不要混在同一份稿里；
- **目标不明确时先问用户“交付到 Seedance 还是 DirectorDeck”**，不要默认选一个。

如果用户要从 manju 的 `图N` 映射到 DirectorDeck `@图片N`，必须先拿到明确的
`图N ↔ @图片N` 对照（用户给，或按素材槽位顺序确认），不能默认等同。

## 二、触发/路由不冲突

- manju 的子技能描述都标注“**套装内部技能 · 全流程用户通常无需直接调用**”，
  正常应由总控 `short-drama-director` 路由；
- 本 skill 只在“目标明确是 DirectorDeck 导入”时触发，不认泛泛的“写剧本/写小说”；
- 所以正常分工是：
  - 创作/分镜/Seedance 投喂 → manju 总控；
  - 交到 DirectorDeck → 本 skill。

如果主 agent 同时加载了两边，按这个顺序执行：

```
manju 总控/子技能（创作、锁、分镜、Seedance 投喂）
        ↓  仅当用户明确要“导入 DirectorDeck”
本 skill（只做 DirectorDeck 交付格式与校验）
```

**不要**在本 skill 内重新执行 manju 的六阶段编剧链、五道前置锁、五席圆桌审核；
也不要让 manju 的 `sd-feed-engine` 再封装一次 DirectorDeck 稿。

## 三、manju 的锁和本 skill 的关系

`short-drama-director` 有五道前置锁（素材来源/模型版本/画幅/交付形态/段缝衔接）和画风锁。

- 这些属于**创作与平台参数**，权威在 manju 总控；
- 本 skill 不替用户回答这些锁，也不覆盖；
- 如果用户没说清“交付到哪个平台”，先按 manju 的流程问清；确认是 DirectorDeck 后，本 skill 才接手；
- 画幅/模型版本等已定参数会体现在 DirectorDeck 全局配置或节点里，本 skill 不重复定义。

## 四、和 `sd-script-engine` 的润色层

`sd-script-engine` 的“外来剧本润色层”会给台词补神态/动作/语气位，且规定
“只补表演层、不改台词/事件/人物、产出回签用户确认”。

本 skill **消费**这份润色结果，不重复润色：

- 保留它的角色名、台词、事件、人物关系、结局；
- 把它的表演/调度信息放进 DirectorDeck 的 `[画面]` 行或 JSON 的 `actions`；
- 只因为“DirectorDeck 动作行不能以 `角色：` 开头”这类格式原因做结构转换；
- 如果它给的台词超过目标段长，拆句/拆段，不改意思。

## 五、和 H3 V6 模板

`MiniMax H3 分段无限视频生成提示词模板 V6.md` 是模板不是 skill；它的核心格式与本 skill 的
`H3 V6 文本` 契约一致：

- 段头 `【第N段｜X秒】`；
- 台词 `(S1) ... <d>台词</d>`；
- 素材 `<Picture N>`。

分工：

- 用户要生成 H3 V6 提示词本体 → 用 V6 模板，本 skill 不重写创作/分镜；
- 用户要把 V6 文本导入 DirectorDeck → 本 skill 只做解析校验/必要时转换；
- V6 模板对 `<d>` 内“只能有一句实际台词”等规则属于创作/提示词规则，本 skill 不覆盖；
- 导入器限制单段 1–60 秒、≤64 段；V6 模板如果生成更长/更多段，拆文件，不要截断。

## 六、一出问题先看这里

| 现象 | 原因 | 处理 |
|---|---|---|
| 稿子里同时出现 `图1` 和 `@图片1` | 两个交付层混用 | 拆成 Seedance 稿和 DirectorDeck 稿两份 |
| DirectorDeck 导入报 `@图片N` 空槽 | 用了 manju 的图N 编号，或槽位没图 | 先确认 AssetShelf 槽位；不要猜编号 |
| manju 要求七段式，DirectorDeck 只有 9 图槽 | 平台不同 | 按目标平台选一份；不要互相裁剪 |
| 同时要求“Seedance 投喂稿 + DirectorDeck 导入稿” | 双交付 | 先出创作稿，再分别由 sd-feed 和本 skill 各出一份，标注文件名 |
| V6 模板有 `<Picture N>`，DirectorDeck 文本里也写 `<Picture N>` | 格式串了 | DirectorDeck 文本用 `@图片N`；H3 V6 才用 `<Picture N>` |
