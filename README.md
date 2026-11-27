# DirectorDeck

ComfyUI 节点库：**AI 短剧导演台**。把"模型 + 素材 + 剧本 + 音色"组织成链式分段生成流水线：
每段可接入自己的素材/锁音/剧本覆盖，也可以沿用上一段；最后二采、合并成片。

> 目标底座：ComfyUI 0.46+ / MiniMax H3（`comfy_extras.nodes_minimax_h3`），也在 adapter 层预留其它模型。
> 规划与决策见 [docs/PLAN.md](docs/PLAN.md)，字段级契约见 [docs/CONTRACTS.md](docs/CONTRACTS.md)。

## 状态

- **M0 骨架**（当前）：包结构、数据契约、纯函数核心（帧数学 / policy 解析 / 剧本解析 / 素材槽位）+ 单测。
- M1 单段闭环 → M2 多段覆盖+抽卡+接缝+合并 → M3 锁音+二采 → M4 前端 → M5 发布。

## 设计要点（已定稿）

1. **链式分段 + 段级可选覆盖**：每段不接输入=沿用（policy 显式选 `inherit`）；接了=覆盖。
2. **每段必须显式指定 policy**：默认 `unset`，执行时未指定直接报错，避免静默继承。
3. **素材按 `@图片N` 槽位覆盖**：固定 9 槽，`merge` 按槽位替换。
4. **段级 config 只允许安全子集；模型仅链首提供**（禁止"半条链两个模型"）。

## 开发

```powershell
# 单元测试（零第三方依赖，stdlib unittest）
python -m unittest discover -s tests -v

# 安装到 ComfyUI（开发期用目录联接，改完重启 ComfyUI）
# Windows:
#   New-Item -ItemType Junction -Path <ComfyUI>/custom_nodes/DirectorDeck -Target <repo>
```

## 目录

```
director_deck/
  core/        # 纯 Python：types / frames / policy / assets / script（不 import ComfyUI，可单测）
  adapters/    # 唯一接触 ComfyUI 内部的层（M1 起）
  nodes/       # 节点薄壳（M1 起）
  web/         # 前端扩展（M4）
tests/         # 单测
docs/          # PLAN.md / CONTRACTS.md
```

## License

AGPL-3.0（见 LICENSE）。参考实现采用 clean-room 原则：只使用 ComfyUI 内核公开接口与公开文档。
