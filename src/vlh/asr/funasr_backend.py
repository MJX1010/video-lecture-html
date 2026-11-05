"""FunASR backend (Paraformer-zh / SenseVoice) with word/sentence timestamps."""

from __future__ import annotations

from pathlib import Path

from .base import Segment, TranscribeResult


class FunAsrBackend:
    name = "funasr"

    def __init__(self, model: str = "paraformer-zh"):
        # Import lazily so `vlh --help` works without FunASR installed.
        from funasr import AutoModel  # type: ignore

        self._model_id = model
        # paraformer-zh ships sentence timestamps via vad + punc pipeline
        if model == "sensevoice":
            self._model = AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad", punc_model="ct-punc")
        else:
            self._model = AutoModel(
                model="paraformer-zh",
                vad_model="fsmn-vad",
                punc_model="ct-punc",
                spk_model=None,
            )

    def transcribe(self, audio_or_video: Path, language: str = "zh") -> TranscribeResult:
        res = self._model.generate(input=str(audio_or_video), batch_size_s=300)
        segments: list[Segment] = []
        # FunASR return shapes vary by model; normalize common cases.
        items = res if isinstance(res, list) else [res]
        for item in items:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            # sentence_info preferred when present
            sent_info = item.get("sentence_info") or item.get("sentences") or []
            if sent_info:
                for s in sent_info:
                    st = float(s.get("start", s.get("start_time", 0)) or 0)
                    en = float(s.get("end", s.get("end_time", st)) or st)
                    # FunASR often uses ms
                    if st > 1000 or en > 1000:
                        st, en = st / 1000.0, en / 1000.0
                    tx = (s.get("text") or "").strip()
                    if tx:
                        segments.append(Segment(start=st, end=en, text=tx))
            elif text:
                ts = item.get("timestamp") or []
                if ts and isinstance(ts[0], (list, tuple)):
                    st = float(ts[0][0])
                    en = float(ts[-1][1])
                    if st > 1000 or en > 1000:
                        st, en = st / 1000.0, en / 1000.0
                    segments.append(Segment(start=st, end=en, text=text))
                else:
                    segments.append(Segment(start=0.0, end=0.0, text=text))
        return TranscribeResult(language=language, segments=segments, backend=self.name)
