# MiniMax H3 分段无限视频生成提示词模板 V6（预置副本）

- 来源：用户提供的本地文件 `MiniMax H3 分段无限视频生成提示词模板 V6.md`
- 许可：未标明，按“用户自有资料”随仓库预置，仅用于编剧台的规则加载
- 适用：H3 分段提示词（`【第N段｜X秒】` + `<d>` 对白标签）

## 用法

在「编剧台」：
1. `skill` 选 `minimax_h3_v6`；
2. `output_format` 选 **H3 V6 分段提示词**；
3. 可选 `include_refs=False`（单文件无 references）。

节点会把 V6 文本自动转换成 DirectorDeck 剧本 / TTS 台词表，方便直接接视频生成器。
