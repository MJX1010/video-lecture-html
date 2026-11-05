"""Optional PaddleOCR on slide images."""

from __future__ import annotations

from pathlib import Path

from vlh.frames.hybrid import Slide


def maybe_ocr_slides(slides: list[Slide], enabled: bool = False) -> dict[int, str]:
    if not enabled or not slides:
        return {}
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "OCR requested but paddleocr is not installed. "
            "pip install paddlepaddle paddleocr\n"
            f"Import error: {e}"
        ) from e

    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    out: dict[int, str] = {}
    for s in slides:
        result = ocr.ocr(str(s.image_path), cls=True)
        lines: list[str] = []
        if result:
            for block in result:
                if not block:
                    continue
                for line in block:
                    try:
                        txt = line[1][0]
                    except Exception:  # noqa: BLE001
                        continue
                    if txt:
                        lines.append(str(txt))
        out[s.index] = "\n".join(lines)
    return out
