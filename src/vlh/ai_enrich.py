"""AI Agent enrich: read→analyze→organize→rewrite, then rebuild HTML."""

from __future__ import annotations

import json
import traceback
from pathlib import Path

from rich.console import Console

from vlh.ai_agent.pipeline import AIAnalysisResult, run_ai_analysis
from vlh.enrich import attach_analysis, enrich_talk_dir
from vlh.htmlgen.models import (
    AIAnalysisView,
    AIChapterView,
    AnalysisView,
    ChapterView,
    SiteIndex,
    TalkPage,
)
from vlh.htmlgen.site import talk_from_meta, write_site_index, write_talk_page
from vlh.llm.client import LLMClient, LLMConfig, resolve_llm_config

console = Console()


def _ai_to_views(result: AIAnalysisResult) -> AIAnalysisView:
    return AIAnalysisView(
        one_liner=result.one_liner,
        overview=result.overview,
        key_points=result.key_points,
        glossary=result.glossary,
        practice_tips=result.practice_tips,
        limitations=result.limitations,
        further_keywords=result.further_keywords,
        chapters=[
            AIChapterView(
                index=c.index,
                title=c.title,
                start=c.start,
                end=c.end,
                slide_index=c.slide_index,
                slide_image=c.slide_image,
                rewrite=c.rewrite,
                key_points=c.key_points,
                terms=c.terms,
                uncertain=c.uncertain,
            )
            for c in result.chapters
        ],
        model=result.model,
        provider=result.provider,
        prompt_version=result.prompt_version,
        method=result.method,
        label=result.label,
        status=result.status,
        error=result.error,
        stats=result.stats,
    )


def _ai_as_analysis_view(result: AIAnalysisResult) -> AnalysisView:
    """Also populate legacy analysis fields so older template bits still work."""
    return AnalysisView(
        overview=result.overview or result.one_liner,
        key_points=result.key_points,
        chapters=[
            ChapterView(
                index=c.index,
                title=c.title,
                start=c.start,
                end=c.end,
                slide_index=c.slide_index,
                slide_image=c.slide_image,
                paragraphs=c.paragraphs,
                segment_count=0,
            )
            for c in result.chapters
        ],
        full_text="",
        stats=result.stats,
        method=result.method,
        label=result.label,
    )


def ai_enrich_talk_dir(
    talk_dir: Path,
    *,
    client: LLMClient,
    concurrency: int = 4,
    verify: bool = False,
    fallback_rule: bool = True,
) -> TalkPage:
    meta_path = talk_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"missing meta.json in {talk_dir}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    talk = talk_from_meta(meta, slug=talk_dir.name)
    segments = [{"start": s.start, "end": s.end, "text": s.text} for s in talk.segments]
    slides = [
        {"index": s.index, "time_sec": s.time_sec, "image": s.image_rel, "ocr": s.ocr_text}
        for s in talk.slides
    ]
    cache_path = talk_dir / "ai_analysis.json"

    def progress(msg: str) -> None:
        console.print(f"  [dim]{talk.slug[:28]}…[/dim] {msg}")

    try:
        result = run_ai_analysis(
            title=talk.title,
            segments=segments,
            slides=slides,
            duration_sec=talk.duration_sec,
            client=client,
            cache_path=cache_path,
            concurrency=concurrency,
            verify=verify,
            progress=progress,
        )
        talk.ai_analysis = _ai_to_views(result)
        talk.analysis = _ai_as_analysis_view(result)
        if not talk.full_text:
            from vlh.analysis.build import concatenate_full_text

            talk.full_text = concatenate_full_text(segments)
        # Persist AI result summary into ai_analysis.json already done by pipeline;
        # also write a status sibling for quick checks
        status = {
            "status": "ok",
            "model": result.model,
            "provider": result.provider,
            "one_liner": result.one_liner,
            "stats": result.stats,
        }
        (talk_dir / "ai_status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return talk
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        console.print(f"[red]ai failed[/red] {talk_dir.name}: {err}")
        (talk_dir / "ai_status.json").write_text(
            json.dumps(
                {"status": "failed", "error": err, "trace": traceback.format_exc()[-2000:]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if not fallback_rule:
            raise
        # Rule fallback
        talk = enrich_talk_dir(talk_dir, force=True)
        if talk.analysis:
            talk.analysis.label = "自动整理（AI 失败回退）"
            talk.analysis.method = "rule-fallback"
        return talk


def ai_enrich_site(
    site_dir: Path,
    *,
    site_title: str = "UWA Learning",
    config: LLMConfig | None = None,
    concurrency: int = 4,
    verify: bool = False,
    limit: int = 0,
    only_slug: str | None = None,
    fallback_rule: bool = True,
) -> tuple[int, int, list[str]]:
    site_dir = Path(site_dir)
    talks_root = site_dir / "talks"
    if not talks_root.is_dir():
        raise FileNotFoundError(f"no talks/ under {site_dir}")

    if config is None:
        config = resolve_llm_config()
    client = LLMClient(config)
    console.print(
        f"[bold]LLM[/bold] provider={config.provider} model={config.model} "
        f"base={config.base_url} concurrency={concurrency}"
    )

    dirs = sorted(p for p in talks_root.iterdir() if p.is_dir() and (p / "meta.json").exists())
    if only_slug:
        dirs = [d for d in dirs if only_slug in d.name]
        if not dirs:
            raise FileNotFoundError(f"no talk matching slug substring: {only_slug}")
    if limit > 0:
        dirs = dirs[:limit]

    talks: list[TalkPage] = []
    errors: list[str] = []
    ok = 0
    # For index completeness, load all talks; update processed ones with AI
    all_dirs = sorted(p for p in talks_root.iterdir() if p.is_dir() and (p / "meta.json").exists())
    processed: dict[str, TalkPage] = {}

    for i, d in enumerate(dirs, 1):
        console.rule(f"ai-enrich [{i}/{len(dirs)}] {d.name[:48]}")
        try:
            talk = ai_enrich_talk_dir(
                d,
                client=client,
                concurrency=concurrency,
                verify=verify,
                fallback_rule=fallback_rule,
            )
            write_talk_page(talk, site_dir)
            processed[d.name] = talk
            ok += 1
        except Exception as e:  # noqa: BLE001
            msg = f"{d.name}: {e}"
            console.print(f"[red]failed[/red] {msg}")
            errors.append(msg)

    # Build full index: prefer freshly processed, else load meta (may already have ai)
    for d in all_dirs:
        if d.name in processed:
            talks.append(processed[d.name])
            continue
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        talks.append(talk_from_meta(meta, slug=d.name))

    write_site_index(SiteIndex(title=site_title, talks=talks, out_dir=site_dir))
    console.print(f"[bold green]done[/bold green] ai-ok={ok} fail={len(errors)} → {site_dir/'index.html'}")
    return ok, len(errors), errors
