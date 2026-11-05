from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SlideView:
    index: int
    time_sec: float
    image_rel: str
    ocr_text: str = ""


@dataclass
class SegmentView:
    start: float
    end: float
    text: str


@dataclass
class TalkPage:
    slug: str
    title: str
    category: str | None
    speaker: str | None
    source_name: str
    duration_sec: float
    video_href: str | None
    slides: list[SlideView] = field(default_factory=list)
    segments: list[SegmentView] = field(default_factory=list)
    asr_backend: str = "none"
    asr_note: str = ""
    full_text: str = ""


@dataclass
class SiteIndex:
    title: str
    talks: list[TalkPage]
    out_dir: Path
