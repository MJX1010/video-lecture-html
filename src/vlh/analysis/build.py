"""Build readable chapterized analysis from meta segments + slides (no LLM required)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# Cue words for key-point extraction (Simplified Chinese + common EN)
_CUE_RE = re.compile(
    r"(总结|综上|因此|所以|注意|核心|关键|重点|建议|结论|本质|原则|"
    r"首先|其次|最后|换句话说|也就是说|举例|例如|比如|"
    r"important|summary|key|note that|in conclusion)",
    re.IGNORECASE,
)
_FILLER_RE = re.compile(r"^(呃|嗯|啊|那个|就是|然后|对|好|行|这个|那个啥)[，。、\s]*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；\n])|(?<=[.!?])\s+")


@dataclass
class Chapter:
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


@dataclass
class AnalysisResult:
    overview: str
    key_points: list[str]
    chapters: list[Chapter]
    full_text: str
    stats: dict[str, Any]
    method: str = "rule-based"
    label: str = "自动整理"

    def to_dict(self) -> dict[str, Any]:
        return {
            "overview": self.overview,
            "key_points": self.key_points,
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
                    "anchor": c.anchor,
                }
                for c in self.chapters
            ],
            "full_text": self.full_text,
            "stats": self.stats,
            "method": self.method,
            "label": self.label,
        }


def _clean_text(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _is_filler(t: str) -> bool:
    return bool(_FILLER_RE.match(t.strip()))


def _fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def concatenate_full_text(segments: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in segments:
        t = _clean_text(str(s.get("text") or ""))
        if t and not _is_filler(t):
            parts.append(t)
    # Join with nothing for CJK continuity; keep space if Latin-heavy chunk ends
    out: list[str] = []
    for p in parts:
        if not out:
            out.append(p)
            continue
        prev = out[-1]
        if prev[-1].isalnum() and p[0].isalnum() and (prev[-1].isascii() or p[0].isascii()):
            out.append(" " + p)
        else:
            out.append(p)
    return "".join(out)


def merge_segments_to_paragraphs(
    segments: list[dict[str, Any]],
    *,
    max_chars: int = 180,
    max_gap: float = 1.8,
) -> list[str]:
    """Merge short ASR fragments into readable paragraphs."""
    paras: list[str] = []
    buf: list[str] = []
    buf_start: float | None = None
    last_end: float | None = None
    buf_chars = 0

    def flush() -> None:
        nonlocal buf, buf_chars, buf_start, last_end
        if not buf:
            return
        text = concatenate_full_text([{"text": b} for b in buf])
        text = _clean_text(text)
        if text:
            # Prefer ending on sentence boundary when possible
            paras.append(text)
        buf = []
        buf_chars = 0
        buf_start = None
        last_end = None

    for s in segments:
        t = _clean_text(str(s.get("text") or ""))
        if not t or _is_filler(t):
            continue
        start = float(s.get("start") or 0)
        end = float(s.get("end") or start)
        gap = (start - last_end) if last_end is not None else 0.0
        would = buf_chars + len(t)
        hard_break = (
            gap > max_gap
            or would > max_chars
            or (buf and buf[-1][-1:] in "。！？；.!?" and would > max_chars * 0.55)
        )
        if hard_break and buf:
            flush()
        if buf_start is None:
            buf_start = start
        buf.append(t)
        buf_chars += len(t)
        last_end = end
        if t[-1:] in "。！？.!?" and buf_chars >= max_chars * 0.7:
            flush()
    flush()
    return paras


def _pick_chapter_boundaries(
    slides: list[dict[str, Any]],
    duration: float,
    *,
    target_min: int = 8,
    target_max: int = 20,
) -> list[dict[str, Any]]:
    """Choose chapter starts from slides; cluster if too many."""
    slides = sorted(slides, key=lambda s: float(s.get("time_sec") or 0))
    if not slides:
        # Synthetic chapters every ~3 minutes
        if duration <= 0:
            return [{"time_sec": 0.0, "index": 0, "image": None}]
        step = max(120.0, duration / 12)
        out = []
        t = 0.0
        i = 0
        while t < duration - 30:
            out.append({"time_sec": t, "index": i, "image": None})
            t += step
            i += 1
        if not out:
            out.append({"time_sec": 0.0, "index": 0, "image": None})
        return out

    if len(slides) <= target_max:
        return [
            {
                "time_sec": float(s.get("time_sec") or 0),
                "index": int(s.get("index") if s.get("index") is not None else i),
                "image": s.get("image") or s.get("image_rel"),
            }
            for i, s in enumerate(slides)
        ]

    # Too many slides: keep first, then prefer large time gaps; fill to ~target_max
    times = [float(s.get("time_sec") or 0) for s in slides]
    gaps = [(i, times[i] - times[i - 1]) for i in range(1, len(times))]
    gaps.sort(key=lambda x: x[1], reverse=True)
    keep_idx = {0}
    for i, _g in gaps:
        if len(keep_idx) >= target_max:
            break
        keep_idx.add(i)
    # Also ensure roughly even coverage
    if len(keep_idx) < target_min:
        step = max(1, len(slides) // target_min)
        for i in range(0, len(slides), step):
            keep_idx.add(i)
            if len(keep_idx) >= target_min:
                break
    keep_sorted = sorted(keep_idx)
    # Merge chapters that are too tiny (< 25s) into previous
    merged: list[int] = [keep_sorted[0]]
    for i in keep_sorted[1:]:
        if times[i] - times[merged[-1]] < 25:
            continue
        merged.append(i)
    return [
        {
            "time_sec": times[i],
            "index": int(slides[i].get("index") if slides[i].get("index") is not None else i),
            "image": slides[i].get("image") or slides[i].get("image_rel"),
        }
        for i in merged
    ]


def _title_from_text(paras: list[str], fallback: str) -> str:
    for p in paras:
        # Prefer first sentence with some substance
        for sent in _SENTENCE_SPLIT.split(p):
            s = _clean_text(sent)
            if len(s) < 6 or _is_filler(s):
                continue
            if len(s) > 36:
                s = s[:36].rstrip("，,、 ") + "…"
            return s
    return fallback


def _extract_key_points(paras: list[str], *, limit: int = 8) -> list[str]:
    scored: list[tuple[int, str]] = []
    for p in paras:
        for sent in _SENTENCE_SPLIT.split(p):
            s = _clean_text(sent)
            if len(s) < 10 or len(s) > 120:
                continue
            score = 0
            if _CUE_RE.search(s):
                score += 5
            if any(k in s for k in ("优化", "性能", "方案", "架构", "实现", "实践", "对比")):
                score += 2
            if score:
                scored.append((score, s))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    seen: set[str] = set()
    out: list[str] = []
    for _sc, s in scored:
        key = s[:24]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    if len(out) < 3:
        # Fallback: first sentences of early dense paragraphs
        for p in paras:
            for sent in _SENTENCE_SPLIT.split(p):
                s = _clean_text(sent)
                if 12 <= len(s) <= 100:
                    key = s[:24]
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(s)
                    if len(out) >= min(5, limit):
                        return out
    return out


def build_analysis(
    *,
    title: str,
    segments: list[dict[str, Any]],
    slides: list[dict[str, Any]],
    duration_sec: float = 0.0,
) -> AnalysisResult:
    segments = sorted(segments or [], key=lambda s: float(s.get("start") or 0))
    slides = slides or []
    duration = float(duration_sec or 0)
    if duration <= 0 and segments:
        duration = float(segments[-1].get("end") or segments[-1].get("start") or 0)

    full_text = concatenate_full_text(segments)
    bounds = _pick_chapter_boundaries(slides, duration)

    # Ensure start at 0
    if not bounds or float(bounds[0]["time_sec"]) > 1.0:
        bounds = [{"time_sec": 0.0, "index": None, "image": None}] + list(bounds)

    chapters: list[Chapter] = []
    for i, b in enumerate(bounds):
        start = float(b["time_sec"])
        end = float(bounds[i + 1]["time_sec"]) if i + 1 < len(bounds) else (duration or start + 1)
        if end <= start:
            end = start + 1
        segs = [
            s
            for s in segments
            if start <= float(s.get("start") or 0) < end
            or (i == len(bounds) - 1 and float(s.get("start") or 0) >= start)
        ]
        # Last chapter: include remaining
        if i == len(bounds) - 1:
            segs = [s for s in segments if float(s.get("start") or 0) >= start]
        paras = merge_segments_to_paragraphs(segs)
        fallback = f"第 {i + 1} 章 · {_fmt_time(start)}"
        ch_title = _title_from_text(paras, fallback)
        if not paras:
            ch_title = fallback
        chapters.append(
            Chapter(
                index=i + 1,
                title=ch_title,
                start=start,
                end=end,
                slide_index=b.get("index"),
                slide_image=b.get("image"),
                paragraphs=paras,
                segment_count=len(segs),
            )
        )

    # Drop empty tiny chapters in the middle (keep first/last if they have content later)
    cleaned: list[Chapter] = []
    for c in chapters:
        if not c.paragraphs and (c.end - c.start) < 40:
            continue
        cleaned.append(c)
    if not cleaned:
        cleaned = chapters
    # Reindex
    for i, c in enumerate(cleaned, 1):
        c.index = i

    all_paras = [p for c in cleaned for p in c.paragraphs]
    overview = _make_overview(title, all_paras, len(cleaned), duration)
    key_points = _extract_key_points(all_paras)

    stats = {
        "duration_sec": duration,
        "segment_count": len(segments),
        "slide_count": len(slides),
        "chapter_count": len(cleaned),
        "char_count": len(full_text),
        "paragraph_count": len(all_paras),
        "key_point_count": len(key_points),
    }
    return AnalysisResult(
        overview=overview,
        key_points=key_points,
        chapters=cleaned,
        full_text=full_text,
        stats=stats,
    )


def _make_overview(title: str, paras: list[str], n_chapters: int, duration: float) -> str:
    parts: list[str] = []
    if title:
        parts.append(f"本讲《{title}》")
    else:
        parts.append("本讲")
    if duration > 0:
        parts.append(f"时长约 {_fmt_time(duration)}")
    parts.append(f"自动整理为 {n_chapters} 个章节")
    for p in paras[:4]:
        if len(p) >= 20:
            snip = p[:120].rstrip("，,、 ")
            if len(p) > 120:
                snip += "…"
            parts.append(f"开篇：{snip}")
            break
    return "。".join(parts) + "。（以上为规则引擎自动整理，非人工审校）"
