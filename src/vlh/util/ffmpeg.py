"""Thin ffmpeg / ffprobe wrappers."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def ensure_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegError(
            "ffmpeg not found on PATH. Install ffmpeg and retry "
            "(Windows: https://ffmpeg.org/download.html or `winget install ffmpeg`)."
        )
    return path


def ensure_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise FFmpegError("ffprobe not found on PATH (usually ships with ffmpeg).")
    return path


def probe_duration(video: Path) -> float:
    ffprobe = ensure_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {proc.stderr.strip()}")
    data = json.loads(proc.stdout or "{}")
    return float(data.get("format", {}).get("duration") or 0.0)


def extract_audio_wav(video: Path, wav_out: Path, sample_rate: int = 16000) -> Path:
    ffmpeg = ensure_ffmpeg()
    wav_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "wav",
        str(wav_out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg audio extract failed: {proc.stderr[-500:]}")
    return wav_out


def extract_keyframes_ffmpeg(video: Path, out_dir: Path, pattern: str = "kf_%06d.jpg") -> list[Path]:
    """Coarse keyframe recall via ffmpeg select=eq(pict_type\\,I)."""
    ffmpeg = ensure_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tpl = str(out_dir / pattern)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-vf",
        r"select=eq(pict_type\,I)",
        "-vsync",
        "vfr",
        "-q:v",
        "2",
        out_tpl,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg keyframe extract failed: {proc.stderr[-500:]}")
    return sorted(out_dir.glob("kf_*.jpg"))
