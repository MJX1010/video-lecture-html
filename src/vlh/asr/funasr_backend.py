"""FunASR backend (Paraformer-zh / SenseVoice) with sentence timestamps."""

from __future__ import annotations

from pathlib import Path

from .base import Segment, TranscribeResult


def _pick_device() -> str:
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


class FunAsrBackend:
    name = "funasr"

    def __init__(self, model: str = "paraformer-zh", device: str | None = None):
        # Import lazily so `vlh --help` works without FunASR installed.
        from funasr import AutoModel  # type: ignore

        self._model_id = model
        self.device = device or _pick_device()
        kw = dict(vad_model="fsmn-vad", punc_model="ct-punc", device=self.device, disable_update=True)
        if model == "sensevoice":
            self._model = AutoModel(model="iic/SenseVoiceSmall", **kw)
        else:
            self._model = AutoModel(model="paraformer-zh", **kw)

    def transcribe(self, audio_or_video: Path, language: str = "zh") -> TranscribeResult:
        res = self._model.generate(input=str(audio_or_video), batch_size_s=300, sentence_timestamp=True)
        segments: list[Segment] = []
        items = res if isinstance(res, list) else [res]
        for item in items:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            sent_info = item.get("sentence_info") or []
            if sent_info:
                # FunASR sentence_info timestamps are always milliseconds
                for s in sent_info:
                    st = float(s.get("start", 0) or 0) / 1000.0
                    en = float(s.get("end", 0) or 0) / 1000.0
                    tx = (s.get("text") or s.get("sentence") or "").strip()
                    if tx:
                        segments.append(Segment(start=st, end=en, text=tx))
            elif text:
                ts = item.get("timestamp") or []
                if ts and isinstance(ts[0], (list, tuple)):
                    segments.append(Segment(start=ts[0][0] / 1000.0, end=ts[-1][1] / 1000.0, text=text))
                else:
                    segments.append(Segment(start=0.0, end=0.0, text=text))
        note = f"FunASR paraformer-zh + fsmn-vad + ct-punc on {self.device}"
        return TranscribeResult(language=language, segments=segments, backend=self.name, note=note)