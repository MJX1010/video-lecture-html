"""Filename parsing helpers for UWA / GeekTime style lecture titles."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


_UWA_RE = re.compile(
    r"^【(?P<cat>[^】]+)】\s*(?P<title>.+?)(?:\s*[-–—]\s*(?P<speaker>.+))?$",
    re.UNICODE,
)


@dataclass(frozen=True)
class ParsedTitle:
    category: str | None
    title: str
    speaker: str | None
    raw: str


def parse_uwa_title(filename: str) -> ParsedTitle:
    """Parse names like ``【UWA 2024】性能优化实践-张三.mp4``."""
    stem = filename.rsplit("/", 1)[-1]
    stem = stem.rsplit("\\", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    m = _UWA_RE.match(stem.strip())
    if not m:
        return ParsedTitle(category=None, title=stem.strip(), speaker=None, raw=stem)
    return ParsedTitle(
        category=m.group("cat").strip(),
        title=m.group("title").strip(),
        speaker=(m.group("speaker") or "").strip() or None,
        raw=stem,
    )


def slugify(text: str, max_len: int = 80) -> str:
    """ASCII-ish slug; keep CJK as hex escapes when needed for filesystem safety."""
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"[\s_/\\]+", "-", text)
    out: list[str] = []
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in "-."):
            out.append(ch)
        elif "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf":
            out.append(f"u{ord(ch):04x}")
        else:
            out.append("-")
    slug = re.sub(r"-{2,}", "-", "".join(out)).strip("-")
    if not slug:
        slug = "talk"
    return slug[:max_len].rstrip("-")
