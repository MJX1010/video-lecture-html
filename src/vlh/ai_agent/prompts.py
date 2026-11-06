"""Prompt templates for AI lecture analysis (Simplified Chinese, grounded)."""

from __future__ import annotations

PROMPT_VERSION = "ai-v1"

SYSTEM = """你是资深游戏技术课程笔记编辑。任务：阅读演讲转写，整理成准确、易读的中文学习笔记。
硬性规则：
1. 只依据给定转写与幻灯片 OCR，禁止编造未出现的技术结论、数据、产品名或实验结果。
2. 明显 ASR 错词可按上下文修正（如 ASTC/CUDA/URP/Shader/GC/DrawCall），不确定处标注「（转写可能有误）」。
3. 使用简体中文；专业术语保留英文缩写并附中文解释。
4. 输出必须是合法 JSON 对象，不要 Markdown 代码围栏，不要额外说明。
"""


def chapter_user_prompt(
    *,
    talk_title: str,
    chapter_index: int,
    chapter_count: int,
    start: float,
    end: float,
    transcript: str,
    ocr_text: str = "",
) -> str:
    ocr_block = f"\n【幻灯片 OCR】\n{ocr_text}\n" if ocr_text.strip() else ""
    return f"""请分析以下演讲片段并重写为精读笔记。

【演讲标题】{talk_title}
【章节】第 {chapter_index}/{chapter_count} 章
【时间范围秒】{start:.1f} - {end:.1f}
【转写正文】
{transcript}
{ocr_block}
请输出 JSON，字段：
{{
  "title": "简洁准确的章节标题（不超过24字）",
  "rewrite": "精读正文：结构清晰的散文/分段说明，忠实复述讲者内容，可分多段，用 \\n\\n 分段",
  "key_points": ["要点1", "要点2"],
  "terms": [{{"term": "术语", "definition": "简短解释"}}],
  "uncertain": ["不确定或转写可能有误的点"]
}}
要求：key_points 2-6 条；terms 可为空数组；rewrite 不要写成流水账口头禅，要整理成可阅读笔记。
"""


def reduce_user_prompt(
    *,
    talk_title: str,
    duration_sec: float,
    chapter_summaries_json: str,
) -> str:
    return f"""下面是同一演讲各章分析结果（JSON 数组）。请汇总为整讲学习笔记。

【演讲标题】{talk_title}
【时长秒】{duration_sec:.1f}
【各章结果】
{chapter_summaries_json}

请输出 JSON：
{{
  "one_liner": "一句话摘要（不超过40字）",
  "overview": "内容概览，2-4 段，用 \\n\\n 分段",
  "key_points": ["核心要点1", "...共5-10条"],
  "glossary": [{{"term": "术语", "definition": "解释"}}],
  "practice_tips": ["实践建议1", "..."],
  "limitations": ["仅当转写明确提到时才写局限/开放问题，否则空数组"],
  "further_keywords": ["延伸学习关键词"]
}}
禁止引入各章结果中未出现的新事实。
"""


def verify_user_prompt(*, chapter_title: str, source: str, rewrite: str) -> str:
    return f"""检查章节重写是否忠实于转写。

【章节标题】{chapter_title}
【转写摘录】
{source[:6000]}
【重写正文】
{rewrite[:6000]}

输出 JSON：
{{
  "ok": true,
  "issues": ["如有幻觉或不忠实处列出"],
  "rewrite_fixed": "若需修正则给出修正后全文，否则与原文相同"
}}
只修正明显幻觉；不要扩写新内容。
"""
