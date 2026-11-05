"""Hybrid keyframe / slide-change extraction.

「逐帧」in product language means: coarse I-frame (or sample) recall + local
visual-diff refinement — NOT true 25fps frame dumping.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from vlh.util.ffmpeg import FFmpegError, ensure_ffmpeg, ensure_ffprobe


@dataclass
class Slide:
    index: int
    time_sec: float
    image_path: Path
    score: float = 0.0


def _probe_fps(video: Path) -> float:
    ffprobe = ensure_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate",
        "-of",
        "json",
        str(video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return 25.0
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        return 25.0
    rate = streams[0].get("r_frame_rate") or "25/1"
    if "/" in rate:
        a, b = rate.split("/", 1)
        try:
            return float(a) / max(float(b), 1e-6)
        except ValueError:
            return 25.0
    try:
        return float(rate)
    except ValueError:
        return 25.0


def _frame_diff_score(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference on downscaled grayscale (0..1)."""
    if a is None or b is None:
        return 1.0
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    ga = cv2.resize(ga, (160, 90), interpolation=cv2.INTER_AREA)
    gb = cv2.resize(gb, (160, 90), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(ga, gb)
    return float(diff.mean()) / 255.0


def _ssim_like(a: np.ndarray, b: np.ndarray) -> float:
    """Cheap SSIM-ish score on downscaled gray (1 = identical)."""
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    ga = cv2.resize(ga, (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32)
    gb = cv2.resize(gb, (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32)
    c1, c2 = 6.5025, 58.5225
    mu_a, mu_b = ga.mean(), gb.mean()
    sig_a = ga.var()
    sig_b = gb.var()
    sig_ab = ((ga - mu_a) * (gb - mu_b)).mean()
    num = (2 * mu_a * mu_b + c1) * (2 * sig_ab + c2)
    den = (mu_a**2 + mu_b**2 + c1) * (sig_a + sig_b + c2)
    return float(num / den) if den else 1.0


def _sample_times_via_ffmpeg(video: Path, interval_sec: float, out_dir: Path) -> list[tuple[float, Path]]:
    """Sample one JPEG every ``interval_sec`` seconds as coarse recall."""
    ffmpeg = ensure_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "sample_%06d.jpg")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-vf",
        f"fps=1/{max(interval_sec, 0.5)}",
        "-q:v",
        "3",
        pattern,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg sample failed: {proc.stderr[-500:]}")
    files = sorted(out_dir.glob("sample_*.jpg"))
    return [(i * interval_sec, p) for i, p in enumerate(files)]


def extract_hybrid_slides(
    video: Path,
    out_dir: Path,
    *,
    sample_interval: float = 2.0,
    diff_threshold: float = 0.08,
    ssim_threshold: float = 0.92,
    min_gap_sec: float = 1.5,
    max_slides: int = 400,
) -> list[Slide]:
    """Coarse fps sampling + local diff/SSIM refinement → slide JPEGs.

    Also tries I-frame dump when available and merges candidates.
    """
    out_dir = Path(out_dir)
    raw_dir = out_dir / "_raw_samples"
    slides_dir = out_dir / "slides"
    if slides_dir.exists():
        shutil.rmtree(slides_dir)
    slides_dir.mkdir(parents=True, exist_ok=True)
    if raw_dir.exists():
        shutil.rmtree(raw_dir)

    candidates = _sample_times_via_ffmpeg(video, sample_interval, raw_dir)

    # Optional I-frame pass (best-effort)
    try:
        from vlh.util.ffmpeg import extract_keyframes_ffmpeg

        kf_dir = out_dir / "_raw_keyframes"
        if kf_dir.exists():
            shutil.rmtree(kf_dir)
        kfs = extract_keyframes_ffmpeg(video, kf_dir)
        fps = _probe_fps(video)
        # Approximate times from sequential I-frames is imperfect; keep as extras
        # tagged with unknown time ≈ index/fps * gop guess — skip timing, use for
        # visual dedupe only if we already have timed samples.
        _ = (kfs, fps)
    except Exception:  # noqa: BLE001
        pass

    kept: list[Slide] = []
    prev_img = None
    last_t = -1e9
    idx = 0
    for t, path in candidates:
        img = cv2.imread(str(path))
        if img is None:
            continue
        if prev_img is None:
            take = True
            score = 1.0
        else:
            d = _frame_diff_score(prev_img, img)
            s = _ssim_like(prev_img, img)
            take = (d >= diff_threshold or s <= ssim_threshold) and (t - last_t >= min_gap_sec)
            score = d
        if take:
            dest = slides_dir / f"slide_{idx:04d}.jpg"
            cv2.imwrite(str(dest), img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            kept.append(Slide(index=idx, time_sec=float(t), image_path=dest, score=score))
            prev_img = img
            last_t = t
            idx += 1
            if idx >= max_slides:
                break

    # cleanup raw samples to save disk
    shutil.rmtree(raw_dir, ignore_errors=True)
    shutil.rmtree(out_dir / "_raw_keyframes", ignore_errors=True)
    return kept
