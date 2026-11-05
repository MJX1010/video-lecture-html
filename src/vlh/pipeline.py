"""End-to-end process for one video -> talk page assets."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from rich.console import Console

from vlh.asr.base import PlaceholderBackend, get_backend
from vlh.frames.hybrid import extract_hybrid_slides
from vlh.htmlgen.models import SegmentView, SlideView, TalkPage
from vlh.htmlgen.site import write_talk_page
from vlh.ocr.paddle import maybe_ocr_slides
from vlh.util.ffmpeg import ensure_ffmpeg, extract_audio_wav, probe_duration
from vlh.util.naming import parse_uwa_title, talk_slug

console = Console()


def slug_for(video: Path) -> str:
    return talk_slug(video.name)


def load_existing_talk(video: Path, out_dir: Path, *, require_asr: bool = True) -> TalkPage | None:
    """Return TalkPage rebuilt from meta.json if this video was already processed (resume)."""
    talk_dir = Path(out_dir) / "talks" / slug_for(video)
    meta_p = talk_dir / "meta.json"
    if not meta_p.exists() or not (talk_dir / "page.html").exists():
        return None
    try:
        m = json.loads(meta_p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if require_asr and (m.get("asr_backend") in (None, "none", "placeholder") or not m.get("segments")):
        return None
    segs = [SegmentView(s["start"], s["end"], s["text"]) for s in m.get("segments", [])]
    return TalkPage(
        slug=m["slug"],
        title=m.get("title") or video.stem,
        category=m.get("category"),
        speaker=m.get("speaker"),
        source_name=m.get("source_name") or video.name,
        duration_sec=float(m.get("duration_sec") or 0.0),
        video_href=m.get("video_href"),
        slides=[
            SlideView(index=s["index"], time_sec=s["time_sec"], image_rel=s["image"], ocr_text=s.get("ocr", ""))
            for s in m.get("slides", [])
        ],
        segments=segs,
        asr_backend=m.get("asr_backend", "none"),
        asr_note=m.get("asr_note", ""),
        full_text="".join(s.text for s in segs).strip(),
    )


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
    backend=None,
) -> TalkPage:
    video = video.resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    parsed = parse_uwa_title(video.name)
    slug = slug_for(video)
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
        console.print(f"[green]slides[/green] hybrid keyframes <- {video.name}")
        slides_meta = extract_hybrid_slides(video, talk_work, sample_interval=sample_interval)
        console.print(f"[green]slides[/green] {len(slides_meta)} kept")

    ocr_map: dict[int, str] = {}
    if ocr.lower() in ("on", "true", "1", "yes") and not dry_run:
        console.print("[green]ocr[/green] paddleocr on slides")
        ocr_map = maybe_ocr_slides(slides_meta, enabled=True)

    # --- ASR ---
    segments_view: list[SegmentView] = []
    full_text = ""
    if slides_only or dry_run:
        ph = PlaceholderBackend(reason="slides-only" if slides_only else "dry-run (no ASR / no frames)")
        result = ph.transcribe(video, language=lang)
        asr_backend, asr_note = result.backend, result.note
    else:
        if backend is None:
            backend = get_backend(prefer=asr, allow_missing=True)
        console.print(f"[green]asr[/green] backend={getattr(backend, 'name', '?')}")
        tmpdir = Path(tempfile.mkdtemp(prefix="vlh_"))
        try:
            wav = extract_audio_wav(video, tmpdir / "audio.wav")
            result = backend.transcribe(wav, language=lang)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        asr_backend, asr_note = result.backend, result.note
        full_text = result.full_text
        segments_view = [SegmentView(s.start, s.end, s.text) for s in result.segments]
        console.print(f"[green]asr[/green] {len(segments_view)} segments, {len(full_text)} chars")
        if asr_backend == "placeholder":
            console.print(f"[yellow]asr skipped[/yellow] {asr_note}")

    video_href: str | None = None
    if video_mode == "link":
        try:
            video_href = Path(os_path_rel(video, talk_work)).as_posix()
        except Exception:  # noqa: BLE001
            video_href = video.as_uri()
    elif video_mode == "copy":
        dest = talk_work / video.name
        if not dry_run:
            shutil.copy2(video, dest)
        video_href = video.name

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