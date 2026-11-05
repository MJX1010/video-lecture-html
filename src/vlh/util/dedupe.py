"""Skip same-size duplicate video files in a batch directory."""

from __future__ import annotations

from pathlib import Path


def find_duplicate_videos(
    paths: list[Path],
) -> tuple[list[Path], list[tuple[Path, Path]]]:
    """Return (unique_paths, skipped_pairs) where skipped maps dup → kept."""
    by_size: dict[int, Path] = {}
    unique: list[Path] = []
    skipped: list[tuple[Path, Path]] = []
    for p in sorted(paths, key=lambda x: (not x.name.startswith("【"), x.name)):
        try:
            size = p.stat().st_size
        except OSError:
            unique.append(p)
            continue
        if size in by_size and size > 0:
            skipped.append((p, by_size[size]))
        else:
            by_size[size] = p
            unique.append(p)
    return unique, skipped
