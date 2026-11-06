from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import AnalysisView, ChapterView, SegmentView, SiteIndex, SlideView, TalkPage


def _templates_dir() -> Path:
    """Resolve templates: packaged copy first, then repo templates/vlh."""
    packaged = Path(__file__).resolve().parent.parent / "templates"
    if (packaged / "talk.html").exists():
        return packaged
    here = Path(__file__).resolve()
    for c in (
        here.parents[3] / "templates" / "vlh",
        here.parents[2] / "templates" / "vlh",
    ):
        if (c / "talk.html").exists():
            return c
    raise FileNotFoundError(
        "Cannot find talk.html templates (expected under src/vlh/templates or templates/vlh)."
    )


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_templates_dir())),
        autoescape=select_autoescape(["html", "xml"]),
    )


def copy_static(out_dir: Path) -> None:
    src = _templates_dir() / "styles.css"
    dest_dir = out_dir / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dest_dir / "styles.css")


def talk_to_meta(talk: TalkPage) -> dict:
    meta = {
        "slug": talk.slug,
        "title": talk.title,
        "category": talk.category,
        "speaker": talk.speaker,
        "duration_sec": talk.duration_sec,
        "asr_backend": talk.asr_backend,
        "asr_note": talk.asr_note,
        "source_name": talk.source_name,
        "video_href": talk.video_href,
        "full_text": talk.full_text or (talk.analysis.full_text if talk.analysis else ""),
        "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in talk.segments],
        "slides": [
            {"index": s.index, "time_sec": s.time_sec, "image": s.image_rel, "ocr": s.ocr_text}
            for s in talk.slides
        ],
    }
    if talk.analysis:
        meta["analysis"] = {
            "overview": talk.analysis.overview,
            "key_points": talk.analysis.key_points,
            "method": talk.analysis.method,
            "label": talk.analysis.label,
            "stats": talk.analysis.stats,
            "chapters": [
                {
                    "index": c.index,
                    "title": c.title,
                    "start": c.start,
                    "end": c.end,
                    "slide_index": c.slide_index,
                    "slide_image": c.slide_image,
                    "paragraphs": c.paragraphs,
                    "segment_count": c.segment_count,
                }
                for c in talk.analysis.chapters
            ],
        }
    return meta


def write_talk_page(talk: TalkPage, site_root: Path) -> Path:
    talk_dir = site_root / "talks" / talk.slug
    talk_dir.mkdir(parents=True, exist_ok=True)
    env = _env()
    html = env.get_template("talk.html").render(talk=talk, root_href="../../")
    out = talk_dir / "page.html"
    out.write_text(html, encoding="utf-8")
    meta = talk_to_meta(talk)
    (talk_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if talk.analysis:
        analysis_payload = {
            "overview": talk.analysis.overview,
            "key_points": talk.analysis.key_points,
            "chapters": [
                {
                    "index": c.index,
                    "title": c.title,
                    "start": c.start,
                    "end": c.end,
                    "slide_index": c.slide_index,
                    "slide_image": c.slide_image,
                    "paragraphs": c.paragraphs,
                    "segment_count": c.segment_count,
                }
                for c in talk.analysis.chapters
            ],
            "full_text": talk.analysis.full_text,
            "stats": talk.analysis.stats,
            "method": talk.analysis.method,
            "label": talk.analysis.label,
        }
        (talk_dir / "analysis.json").write_text(
            json.dumps(analysis_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return out


def write_site_index(index: SiteIndex) -> Path:
    copy_static(index.out_dir)
    groups: dict[str, list[TalkPage]] = {}
    for t in index.talks:
        key = t.category or "未分类"
        groups.setdefault(key, []).append(t)
    env = _env()
    html = env.get_template("index.html").render(
        site_title=index.title,
        groups=sorted(groups.items(), key=lambda kv: kv[0]),
        talks=index.talks,
        root_href="./",
    )
    out = index.out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def talk_from_meta(meta: dict, slug: str | None = None) -> TalkPage:
    """Rebuild TalkPage from an existing meta.json (no ASR)."""
    slides = [
        SlideView(
            index=int(s.get("index") or i),
            time_sec=float(s.get("time_sec") or 0),
            image_rel=str(s.get("image") or s.get("image_rel") or ""),
            ocr_text=str(s.get("ocr") or s.get("ocr_text") or ""),
        )
        for i, s in enumerate(meta.get("slides") or [])
    ]
    segments = [
        SegmentView(
            start=float(s.get("start") or 0),
            end=float(s.get("end") or 0),
            text=str(s.get("text") or ""),
        )
        for s in meta.get("segments") or []
    ]
    analysis = None
    raw_a = meta.get("analysis")
    if isinstance(raw_a, dict) and raw_a.get("chapters") is not None:
        chapters = [
            ChapterView(
                index=int(c.get("index") or i + 1),
                title=str(c.get("title") or f"第 {i+1} 章"),
                start=float(c.get("start") or 0),
                end=float(c.get("end") or 0),
                slide_index=c.get("slide_index"),
                slide_image=c.get("slide_image"),
                paragraphs=list(c.get("paragraphs") or []),
                segment_count=int(c.get("segment_count") or 0),
            )
            for i, c in enumerate(raw_a.get("chapters") or [])
        ]
        analysis = AnalysisView(
            overview=str(raw_a.get("overview") or ""),
            key_points=list(raw_a.get("key_points") or []),
            chapters=chapters,
            full_text=str(raw_a.get("full_text") or meta.get("full_text") or ""),
            stats=dict(raw_a.get("stats") or {}),
            method=str(raw_a.get("method") or "rule-based"),
            label=str(raw_a.get("label") or "自动整理"),
        )
    return TalkPage(
        slug=slug or str(meta.get("slug") or "talk"),
        title=str(meta.get("title") or slug or "talk"),
        category=meta.get("category"),
        speaker=meta.get("speaker"),
        source_name=str(meta.get("source_name") or ""),
        duration_sec=float(meta.get("duration_sec") or 0),
        video_href=meta.get("video_href"),
        slides=slides,
        segments=segments,
        asr_backend=str(meta.get("asr_backend") or "none"),
        asr_note=str(meta.get("asr_note") or ""),
        full_text=str(meta.get("full_text") or ""),
        analysis=analysis,
    )
