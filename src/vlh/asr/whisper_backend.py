"""faster-whisper fallback ASR backend."""

from __future__ import annotations

from pathlib import Path

from .base import Segment, TranscribeResult


class FasterWhisperBackend:
    name = "faster-whisper"

    def __init__(self, model_size: str = "medium"):
        from faster_whisper import WhisperModel  # type: ignore

        # Prefer CUDA when available; CPU int8 as fallback.
        device = "cpu"
        compute_type = "int8"
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                device = "cuda"
                compute_type = "float16"
        except Exception:  # noqa: BLE001
            pass
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_or_video: Path, language: str = "zh") -> TranscribeResult:
        segments_iter, info = self._model.transcribe(
            str(audio_or_video),
            language=language if language != "auto" else None,
            vad_filter=True,
        )
        segments = [
            Segment(start=float(s.start), end=float(s.end), text=(s.text or "").strip())
            for s in segments_iter
            if (s.text or "").strip()
        ]
        lang = getattr(info, "language", language) or language
        return TranscribeResult(language=str(lang), segments=segments, backend=self.name)
