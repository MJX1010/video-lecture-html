"""ASR backend protocol and factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class TranscribeResult:
    language: str
    segments: list[Segment] = field(default_factory=list)
    backend: str = "none"
    note: str = ""

    @property
    def full_text(self) -> str:
        return "".join(s.text for s in self.segments).strip()


class AsrBackend(Protocol):
    name: str

    def transcribe(self, audio_or_video: Path, language: str = "zh") -> TranscribeResult: ...


class PlaceholderBackend:
    """Used by --slides-only / --dry-run or when no ASR package is installed."""

    name = "placeholder"

    def __init__(self, reason: str = "ASR skipped"):
        self.reason = reason

    def transcribe(self, audio_or_video: Path, language: str = "zh") -> TranscribeResult:
        return TranscribeResult(
            language=language,
            segments=[],
            backend=self.name,
            note=self.reason,
        )


def get_backend(prefer: str = "funasr", allow_missing: bool = False) -> AsrBackend:
    prefer = (prefer or "funasr").lower()
    errors: list[str] = []

    if prefer in ("funasr", "auto"):
        try:
            from .funasr_backend import FunAsrBackend

            return FunAsrBackend()
        except Exception as e:  # noqa: BLE001 — soft optional dep
            errors.append(f"funasr: {e}")
            if prefer == "funasr" and not allow_missing:
                # still try whisper as soft fallback message path
                pass

    if prefer in ("whisper", "faster-whisper", "auto") or errors:
        try:
            from .whisper_backend import FasterWhisperBackend

            return FasterWhisperBackend()
        except Exception as e:  # noqa: BLE001
            errors.append(f"faster-whisper: {e}")

    if allow_missing:
        reason = "No ASR backend available. " + (" | ".join(errors) if errors else "Install funasr or faster-whisper.")
        return PlaceholderBackend(reason=reason)

    raise RuntimeError(
        "No ASR backend available. Install one of:\n"
        "  pip install funasr modelscope torch\n"
        "  pip install faster-whisper\n"
        "Or pass --slides-only / --dry-run to generate HTML without transcript.\n"
        + "\n".join(errors)
    )
