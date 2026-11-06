from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
class ChapterView:
    index: int
    title: str
    start: float
    end: float
    slide_index: int | None
    slide_image: str | None
    paragraphs: list[str] = field(default_factory=list)
    segment_count: int = 0

    @property
    def anchor(self) -> str:
        return f"ch-{self.index}"

    @property
    def start_label(self) -> str:
        sec = max(0, int(self.start))
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


@dataclass
class AnalysisView:
    overview: str = ""
    key_points: list[str] = field(default_factory=list)
    chapters: list[ChapterView] = field(default_factory=list)
    full_text: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    method: str = "rule-based"
    label: str = "自动整理"


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
    analysis: AnalysisView | None = None


@dataclass
class SiteIndex:
    title: str
    talks: list[TalkPage]
    out_dir: Path
