from pathlib import Path

from vlh.util.dedupe import find_duplicate_videos


def test_dedupe_same_size(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    c = tmp_path / "c.mp4"
    a.write_bytes(b"12345")
    b.write_bytes(b"12345")
    c.write_bytes(b"different-size-payload")
    unique, skipped = find_duplicate_videos([a, b, c])
    assert len(unique) == 2
    assert len(skipped) == 1
    assert skipped[0][0].name == "b.mp4"
