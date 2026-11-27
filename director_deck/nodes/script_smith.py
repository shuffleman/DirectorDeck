"""DirectorDeck · 编剧台（Skill + 小说 -> 分段剧本）。

这个节点解决的是“小说怎么变成能拍的剧本”：

1. **加载 skill**：从 `skills/` 目录选一个规则包（也可以是单文件提示词模板），
   SKILL.md（可选 references）会作为 system prompt 的一部分；
2. **读小说**：输入一段小说/梗概；可选接素材库（9 图槽）和角色/音色库，
   节点会把“可用的 @图片N / 角色名 / 音色槽”列进提示词，让模型别乱编；
3. **调 LLM**：本地（LM Studio/Ollama/vLLM，OpenAI 兼容）或远程 API 都行，
   base_url/model/温度/超时都在节点上；API Key 只从环境变量读；
4. **出剧本**：整理成 DirectorDeck 能直接吃的 `DIRECTOR_SCRIPT`，
   同时输出 TTS 台词表（`角色 @秒 | 音色 | 台词`）和角色映射表；
5. **一键接生成**：`script` 接视频生成器的 script，`voice_lines` 接 TTS 台词表的 lines，
   就完成“小说 -> 剧本 -> 配音 -> 锁音生成”的接线。

输出语言可在节点上选（中文/English/日本語/한국어/跟随原文）。
"""

from __future__ import annotations

import hashlib
import json
import os

from ..adapters import llm as llm_lib
from ..adapters import skill as skill_lib
from ..core import assets as assets_lib
from ..core import screenplay as screenplay_lib
from ..core import script as script_lib
from ..core.types import (CATEGORY, TYPE_ASSETS, TYPE_CAST, TYPE_SCRIPT, error)

PROVIDER_LABELS = ("本地 OpenAI 兼容 (LM Studio/Ollama)", "远程 OpenAI 兼容 (OpenAI/DeepSeek)")
FORMAT_LABELS = ("DirectorDeck 剧本", "H3 V6 分段提示词")
LANGUAGE_CHOICES = ("中文", "English", "日本語", "한국어", "跟随原文")
LANGUAGE_TAGS = {"中文": "Chinese", "English": "English", "日本語": "Japanese",
                 "한국어": "Korean"}

MAX_NOVEL_CHARS = 30000


class DirectorDeckScriptSmith:
    """Skill + 小说 -> 结构化剧本 + TTS 台词表（可选本地/远程 LLM）。"""

    CATEGORY = f"{CATEGORY}/生成"
    FUNCTION = "write"
    RETURN_TYPES = (TYPE_SCRIPT, "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("script", "script_text", "voice_lines", "character_map",
                    "summary", "raw_text")
    DESCRIPTION = (
        "加载 skill + 输入小说，调用本地或远程 LLM 生成分段剧本；"
        "自动按素材库/角色音色库对齐 @图片N 与角色，输出可直接接视频生成器的剧本、"
        "TTS 台词表和角色映射。支持设置剧本输出语言。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "skill": (skill_lib.choices(), {
                    "tooltip": "skills/ 目录里的规则包；可用 tools/import_skill.py 导入外部 skill"}),
                "skill_path": ("STRING", {"default": "",
                                          "tooltip": "可选：直接指定 SKILL.md 或 .md 模板路径（覆盖上面的选择）"}),
                "novel": ("STRING", {"multiline": True, "default":
                                     "（把小说/梗概/章节粘到这里）\n\n例：林澈在雨夜回到老宅，"
                                     "发现门口站着十年前失踪的妹妹。她只说了一句：你终于回来了。",
                                     "tooltip": "要改编的小说/梗概"}),
                "language": (list(LANGUAGE_CHOICES), {"default": "中文",
                                                      "tooltip": "剧本描述与台词使用的语言"}),
                "output_format": (list(FORMAT_LABELS), {"default": FORMAT_LABELS[0],
                                                        "tooltip": "输出 DirectorDeck 剧本 JSON，还是 H3 V6 分段提示词"}),
                "segment_seconds": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 20.0, "step": 0.5,
                                              "tooltip": "每段目标秒数（会写进剧本提示词）"}),
                "max_segments": ("INT", {"default": 3, "min": 1, "max": 64,
                                         "tooltip": "最多生成几段"}),
                "provider": (list(PROVIDER_LABELS), {"default": PROVIDER_LABELS[0]}),
                "base_url": ("STRING", {"default": "",
                                        "tooltip": "空=按 provider 默认（本地 127.0.0.1:1234/v1；远程 api.openai.com/v1）"}),
                "model": ("STRING", {"default": "",
                                     "tooltip": "模型名；留空则自动取 /models 第一个"}),
                "api_key_env": ("STRING", {"default": "OPENAI_API_KEY",
                                           "tooltip": "API Key 从哪个环境变量读（不要把密钥写进工作流）"}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.05}),
                "max_tokens": ("INT", {"default": 4096, "min": 256, "max": 32768, "step": 128}),
                "timeout": ("INT", {"default": 180, "min": 10, "max": 1800,
                                    "tooltip": "LLM 请求超时（秒）"}),
                "include_refs": ("BOOLEAN", {"default": False,
                                             "tooltip": "是否把 skill 的 references/ 扩展资料也塞进上下文"}),
                "max_context_chars": ("INT", {"default": 60000, "min": 2000, "max": 400000, "step": 1000,
                                              "tooltip": "skill 文本最多占多少字符（防上下文爆炸）"}),
            },
            "optional": {
                "assets": (TYPE_ASSETS, {"tooltip": "素材库（9 图槽）：用于对齐 @图片N"}),
                "cast": (TYPE_CAST, {"tooltip": "角色/音色库：用于复用角色名和音频槽"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        key = {k: kwargs.get(k) for k in (
            "skill", "skill_path", "novel", "language", "output_format",
            "segment_seconds", "max_segments", "provider", "base_url", "model",
            "api_key_env", "temperature", "max_tokens", "timeout",
            "include_refs", "max_context_chars")}
        key["assets"] = id(kwargs.get("assets"))
        key["cast"] = id(kwargs.get("cast"))
        try:
            path = skill_lib.resolve(kwargs.get("skill"), kwargs.get("skill_path") or "")
            key["skill_mtime"] = os.path.getmtime(path)
        except Exception:
            pass
        return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ prompt
    @staticmethod
    def _assets_inventory(assets: dict | None) -> tuple[str, list[int]]:
        """把素材库整理成“可引用图片槽”清单。"""
        if not assets:
            return "（未连接素材库：禁止使用 @图片N，image_slot 留空）", []
        data = assets_lib.normalize_assets(assets)
        images = data.get("images") or []
        lines = []
        for index, slot in enumerate(data.get("slots") or [], start=1):
            filled = index <= len(images) and images[index - 1] is not None
            if not filled:
                continue
            name = slot.get("name") or f"图片{index}"
            role = slot.get("role") or ""
            lines.append(f"- @图片{index}：{name}" + (f"（用途：{role}）" if role else ""))
        if not lines:
            return "（素材库为空：禁止使用 @图片N，image_slot 留空）", []
        return "\n".join(lines), list(range(1, len(lines) + 1))

    @staticmethod
    def _cast_inventory(cast: dict | None) -> tuple[str, list[dict]]:
        """把角色/音色库整理成清单，要求模型优先复用。"""
        roles = list((cast or {}).get("roles") or [])
        if not roles:
            return "（未连接角色/音色库：可以自己创建角色，但要固定角色名）", []
        lines = []
        for role in roles:
            slot = (role.get("voice") or {}).get("slot")
            lines.append(f"- {role.get('name') or role.get('id')}"
                         + (f"（音频槽{slot}）" if slot else "")
                         + (f"：{role.get('voice_description')}" if role.get("voice_description") else ""))
        return "\n".join(lines), roles

    @staticmethod
    def _language_rule(language: str) -> str:
        if language == "跟随原文":
            return "与输入小说原文相同的语言（不要翻译）"
        return language

    def _contract(self, output_format: str, language: str, segment_seconds: float,
                  max_segments: int, asset_text: str, image_slots: list[int],
                  cast_text: str) -> str:
        """输出契约：不管 skill 里怎么写，最终格式以这里为准。"""
        language_rule = self._language_rule(language)
        if output_format == FORMAT_LABELS[1]:
            tag = LANGUAGE_TAGS.get(language, "Chinese")
            return (
                "【输出契约：H3 V6 分段提示词】\n"
                f"- 只输出可直接使用的提示词正文，不要解释/分析/代码围栏。\n"
                f"- 段头统一 `【第N段｜X秒】`，段数不超过 {max_segments}，每段 X 秒不超过 {segment_seconds:g}。\n"
                "- 每段最多一个说话人、一个对白标签；台词写成 `<d>[语言标记]实际台词。</d>`，"
                f"语言标记用 `[{tag}]`；台词末尾只有一个句号。\n"
                "- 音色/语气/动作/镜头/闭嘴等控制写在 `<d>` 外面。\n"
                "- 只引用素材清单里的图片，写成 `<Picture N>`；没有素材就不要写引用。\n"
                "- 每段包含：integrated_multimodal_description、时间线、overall_soundscape、non_diegetic_music。\n"
                f"- 剧本语言：{language_rule}。\n"
            )
        return (
            "【输出契约：DirectorDeck 剧本 JSON】\n"
            "只输出一个 JSON 对象（不要代码围栏、不要解释），结构：\n"
            "{\n"
            '  "title": "标题",\n'
            '  "characters": [\n'
            '    {"id": "S1", "name": "角色名", "image_slot": 1, "audio_slot": 1,\n'
            '     "voice": "年龄感/音色/语速等音色描述"}\n'
            "  ],\n"
            '  "segments": [\n'
            "    {\n"
            '      "seconds": 5,\n'
            '      "scene": "本段场景",\n'
            '      "actions": "本段画面与动作（写清楚谁、什么状态、做什么、停在哪）",\n'
            '      "image_refs": [1],\n'
            '      "dialogue": [\n'
            '        {"speaker": "S1", "text": "台词", "at": 0.8}\n'
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n"
            f"硬性要求：\n"
            f"- 全篇使用语言：{language_rule}。\n"
            f"- 段数 1~{max_segments}；每段 seconds 不超过 {segment_seconds:g}；每段只一个主要事件。\n"
            "- 台词要口语化、短（5 秒段一般不超过 16 个中文字），且只写说出口的内容；"
            "情绪/动作/镜头写在 actions 里。\n"
            f"- `image_slot` / `image_refs` 只能从这些已填图片槽里选：{image_slots or '（无）'}。\n"
            "- 角色名和音频槽优先复用角色库；不要新增库外核心角色。\n"
            "- `at` 是台词在段内的开始秒数（0 ~ seconds）。\n"
            "- 角色 id 从 S1 开始固定不变；dialogue.speaker 写角色 id。\n"
            f"素材清单：\n{asset_text}\n"
            f"角色/音色库：\n{cast_text}\n"
        )

    def _system_prompt(self, skill_text: str, contract: str) -> str:
        return (
            "你是一名 AIGC 短剧编剧，负责把小说/梗概改编成可拍摄、可锁音、可续写的分段剧本。\n"
            "下面是一个 skill 规则库，请把它当作创作、节奏、连续性、素材使用的参考规则：\n"
            "<SKILL>\n" + skill_text + "\n</SKILL>\n\n"
            "重要：如果 skill 里的输出格式/交付方式与下面的【输出契约】冲突，"
            "一律以【输出契约】为准；skill 只借用创作规则。\n\n" + contract)

    def _user_prompt(self, novel: str, language: str, segment_seconds: float,
                     max_segments: int, asset_text: str, cast_text: str) -> str:
        text = (novel or "").strip()
        note = ""
        if len(text) > MAX_NOVEL_CHARS:
            note = f"\n（小说原文过长，已截取前 {MAX_NOVEL_CHARS} 字用于本次改编）"
            text = text[:MAX_NOVEL_CHARS]
        return (
            "【小说/故事素材】\n" + text + note + "\n\n"
            "【素材库】\n" + asset_text + "\n\n"
            "【角色/音色库】\n" + cast_text + "\n\n"
            f"【任务】把上面的小说改编成 {max_segments} 段以内的短剧剧本，"
            f"每段约 {segment_seconds:g} 秒；剧本语言：{self._language_rule(language)}。\n"
            "注意：所有段落要能按顺序直接生成视频，上一段结尾要能接上下一段开头。")

    # ------------------------------------------------------------------ main
    def write(self, skill, skill_path, novel, language, output_format,
              segment_seconds, max_segments, provider, base_url, model,
              api_key_env, temperature, max_tokens, timeout, include_refs,
              max_context_chars, assets=None, cast=None):
        if not (novel or "").strip():
            raise ValueError("novel 不能为空：请把小说/梗概粘进来")
        if output_format not in FORMAT_LABELS:
            raise ValueError(f"未知输出格式 {output_format!r}")
        try:
            skill_data = skill_lib.load(
                skill, skill_path, include_refs=bool(include_refs),
                max_chars=int(max_context_chars))
        except FileNotFoundError as exc:
            raise error("DD-E062", str(exc)) from exc

        asset_text, image_slots = self._assets_inventory(assets)
        cast_text, _cast_roles = self._cast_inventory(cast)
        contract = self._contract(output_format, language, float(segment_seconds),
                                  int(max_segments), asset_text, image_slots, cast_text)
        skill_block = skill_data["text"]
        if skill_data.get("truncated"):
            skill_block += "\n（提示：skill 已按 max_context_chars 截断）"
        messages = [
            {"role": "system", "content": self._system_prompt(skill_block, contract)},
            {"role": "user", "content": self._user_prompt(
                novel, language, float(segment_seconds), int(max_segments),
                asset_text, cast_text)},
        ]
        provider_key = "local" if provider.startswith("本地") else "remote"
        response = llm_lib.chat(
            provider_key, base_url, model, messages,
            api_key_env=api_key_env, temperature=temperature,
            max_tokens=max_tokens, timeout=timeout)
        raw_text = response["text"]
        usage = response.get("usage") or {}

        if output_format == FORMAT_LABELS[1]:
            try:
                screenplay = screenplay_lib.v6_to_screenplay(raw_text, language=language)
            except ValueError as exc:
                raise error("DD-E061", f"V6 文本解析失败：{exc}；原始输出前 200 字：{raw_text[:200]}") from exc
            warnings = ["已按 V6 规则生成，并转换为 DirectorDeck 剧本"]
        else:
            data = screenplay_lib.extract_json(raw_text)
            if data is None:
                # 模型偶尔会包解释/代码围栏：纠错一次再解析。
                messages.append({"role": "assistant", "content": raw_text[:4000]})
                messages.append({"role": "user", "content":
                                 "上一条不是合法 JSON。请严格只输出输出契约里的 JSON 对象，"
                                 "不要任何解释、前后缀或代码围栏。"})
                retry = llm_lib.chat(provider_key, base_url, model, messages,
                                     api_key_env=api_key_env, temperature=temperature,
                                     max_tokens=max_tokens, timeout=timeout)
                raw_text = retry["text"]
                data = screenplay_lib.extract_json(raw_text)
                usage = retry.get("usage") or usage
                if data is None:
                    raise error("DD-E061", f"模型没有返回合法 JSON；原始输出前 200 字：{raw_text[:200]}")
            try:
                screenplay = screenplay_lib.normalize_screenplay(
                    data, default_seconds=float(segment_seconds),
                    max_segments=int(max_segments), language=language)
            except ValueError as exc:
                raise error("DD-E061", str(exc)) from exc
            warnings = list(screenplay.get("warnings") or [])

        script_text = screenplay_lib.screenplay_to_script_text(screenplay)
        voice_lines = screenplay_lib.screenplay_to_voice_lines(screenplay)
        character_map = screenplay_lib.screenplay_to_character_map(screenplay)
        script = script_lib.parse_script(script_text, mode="header",
                                         default_seconds=float(segment_seconds))
        tokens = ""
        if usage.get("total_tokens"):
            tokens = f"；tokens={usage['total_tokens']}"
        summary = (
            f"skill={skill_data['id']}（{len(skill_data['files'])} 个文件）；"
            f"模型={response.get('model')}（{provider}）；语言={language}；"
            f"格式={output_format}；标题={screenplay.get('title') or '（无）'}；"
            f"角色 {len(screenplay.get('characters') or [])} 个；"
            f"段数 {len(screenplay.get('segments') or [])}；"
            f"剧本时长 {script.get('total_seconds', 0):.1f}s；"
            f"台词 {len(voice_lines.splitlines())} 句{tokens}")
        if warnings:
            summary += "；提醒：" + " / ".join(warnings)
        print(f"[DirectorDeck] 编剧台：{summary}")
        return (script, script_text, voice_lines, character_map, summary, raw_text)
