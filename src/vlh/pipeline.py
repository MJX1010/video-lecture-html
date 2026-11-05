"""End-to-end process for one video → talk page assets."""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.console import Console

from vlh.asr.base import get_backend
from vlh.frames.hybrid import extract_hybrid_slides
from vlh.htmlgen.models import SegmentView, SlideView, TalkPage
from vlh.htmlgen.site import write_talk_page
from vlh.ocr.paddle import maybe_ocr_slides
from vlh.util.ffmpeg import ensure_ffmpeg, probe_duration
from vlh.util.naming import parse_uwa_title, slugify

console = Console()


def process_video(
    video: Path,
    out_dir: Path,
    *,
    asr: str = "funasr",
    ocr: str = "off",
    lang: str = "zh",
    video_mode: str = "link",
    slides_only: bool = False,
    dry_run: bool = False,
    sample_interval: float = 2.0,
) -> TalkPage:
    video = video.resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    parsed = parse_uwa_title(video.name)
    slug = slugify(f"{parsed.category or 'talk'}-{parsed.title}")
    talk_work = out_dir / "talks" / slug
    talk_work.mkdir(parents=True, exist_ok=True)

    duration = 0.0
    if not dry_run:
        try:
            ensure_ffmpeg()
            duration = probe_duration(video)
        except Exception as e:  # noqa: BLE001
            console.print(f"[yellow]warn[/yellow] duration probe failed: {e}")

    # --- slides ---
    slides_meta = []
    if dry_run:
        console.print(f"[cyan]dry-run[/cyan] skip frames for {video.name}")
    else:
        console.print(f"[green]slides[/green] hybrid keyframes ← {video.name}")
        slides_meta = extract_hybrid_slides(
            video,
            talk_work,
            sample_interval=sample_interval,
        )

    ocr_map: dict[int, str] = {}
    if ocr.lower() in ("on", "true", "1", "yes") and not dry_run:
        console.print("[green]ocr[/green] paddleocr on slides")
        ocr_map = maybe_ocr_slides(slides_meta, enabled=True)

    # --- ASR ---
    segments_view: list[SegmentView] = []
    asr_backend = "none"
    asr_note = ""
    full_text = ""
    if slides_only or dry_run:
        backend = get_backend(prefer=asr, allow_missing=True)
        # force placeholder semantics
        from vlh.asr.base import PlaceholderBackend

        ph = PlaceholderBackend(
            reason="slides-only" if slides_only else "dry-run (no ASR / no frames)"
        )
        result = ph.transcribe(video, language=lang)
        asr_backend, asr_note = result.backend, result.note
    else:
        console.print(f"[green]asr[/green] backend prefer={asr}")
        backend = get_backend(prefer=asr, allow_missing=True)
        result = backend.transcribe(video, language=lang)
        asr_backend, asr_note = result.backend, result.note
        full_text = result.full_text
        segments_view = [SegmentView(s.start, s.end, s.text) for s in result.segments]
        if asr_backend == "placeholder":
            console.print(f"[yellow]asr skipped[/yellow] {asr_note}")

    video_href: str | None = None
    if video_mode == "link":
        # relative from talks/<slug>/page.html → try path relative to out_dir parent
        try:
            video_href = Path(os_path_rel(video, out_dir / "talks" / slug)).as_posix()
        except Exception:  # noqa: BLE001
            video_href = video.as_uri()
    elif video_mode == "copy":
        dest = talk_work / video.name
        if not dry_run:
            shutil.copy2(video, dest)
        video_href = video.name
    elif video_mode == "none":
        video_href = None

    talk = TalkPage(
        slug=slug,
        title=parsed.title,
        category=parsed.category,
        speaker=parsed.speaker,
        source_name=video.name,
        duration_sec=duration,
        video_href=video_href,
        slides=[
            SlideView(
                index=s.index,
                time_sec=s.time_sec,
                image_rel=f"slides/{s.image_path.name}",
                ocr_text=ocr_map.get(s.index, ""),
            )
            for s in slides_meta
        ],
        segments=segments_view,
        asr_backend=asr_backend,
        asr_note=asr_note,
        full_text=full_text,
    )
    write_talk_page(talk, out_dir)
    console.print(f"[bold green]wrote[/bold green] talks/{slug}/page.html")
    return talk


def os_path_rel(target: Path, start: Path) -> str:
    import os

    return os.path.relpath(str(target), start=str(start))
