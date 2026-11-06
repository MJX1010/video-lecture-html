"""Rebuild talk HTML + analysis from existing meta.json (no ASR / no frame extraction)."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from vlh.analysis import build_analysis
from vlh.htmlgen.models import AnalysisView, ChapterView, SiteIndex, TalkPage
from vlh.htmlgen.site import talk_from_meta, write_site_index, write_talk_page

console = Console()


def attach_analysis(talk: TalkPage) -> TalkPage:
    """Run rule-based analysis and attach to talk (also fills full_text)."""
    result = build_analysis(
        title=talk.title,
        segments=[{"start": s.start, "end": s.end, "text": s.text} for s in talk.segments],
        slides=[
            {"index": s.index, "time_sec": s.time_sec, "image": s.image_rel, "ocr": s.ocr_text}
            for s in talk.slides
        ],
        duration_sec=talk.duration_sec,
    )
    talk.full_text = result.full_text or talk.full_text
    talk.analysis = AnalysisView(
        overview=result.overview,
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
                segment_count=c.segment_count,
            )
            for c in result.chapters
        ],
        full_text=result.full_text,
        stats=result.stats,
        method=result.method,
        label=result.label,
    )
    return talk


def enrich_talk_dir(talk_dir: Path, *, force: bool = True) -> TalkPage:
    meta_path = talk_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"missing meta.json in {talk_dir}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    slug = talk_dir.name
    talk = talk_from_meta(meta, slug=slug)
    if force or talk.analysis is None:
        attach_analysis(talk)
    return talk


def enrich_site(
    site_dir: Path,
    *,
    site_title: str = "UWA Learning",
    force: bool = True,
    limit: int = 0,
) -> tuple[int, int, list[str]]:
    """Walk talks/*/meta.json, rebuild analysis + page.html + index.

    Returns (ok, failed, error_messages).
    """
    site_dir = Path(site_dir)
    talks_root = site_dir / "talks"
    if not talks_root.is_dir():
        raise FileNotFoundError(f"no talks/ under {site_dir}")

    dirs = sorted(p for p in talks_root.iterdir() if p.is_dir() and (p / "meta.json").exists())
    if limit > 0:
        dirs = dirs[:limit]

    talks: list[TalkPage] = []
    errors: list[str] = []
    ok = 0
    for i, d in enumerate(dirs, 1):
        console.print(f"[cyan]enrich[/cyan] [{i}/{len(dirs)}] {d.name}")
        try:
            talk = enrich_talk_dir(d, force=force)
            write_talk_page(talk, site_dir)
            talks.append(talk)
            ok += 1
        except Exception as e:  # noqa: BLE001
            msg = f"{d.name}: {e}"
            console.print(f"[red]failed[/red] {msg}")
            errors.append(msg)

    write_site_index(SiteIndex(title=site_title, talks=talks, out_dir=site_dir))
    console.print(
        f"[bold green]done[/bold green] {ok}/{len(dirs)} talks → {site_dir / 'index.html'}"
    )
    return ok, len(errors), errors
