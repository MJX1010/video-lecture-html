from pathlib import Path

from typer.testing import CliRunner

from vlh.cli import app

runner = CliRunner()


def test_dry_run_generates_site(tmp_path: Path):
    video = tmp_path / "【UWA 2024】Demo Talk-Tester.mp4"
    video.write_bytes(b"not-a-real-video")
    out = tmp_path / "site"
    r = runner.invoke(
        app,
        ["process", str(video), "-o", str(out), "--dry-run", "--site-title", "Demo"],
    )
    assert r.exit_code == 0, r.stdout + str(r.exception)
    index = out / "index.html"
    assert index.exists()
    html = index.read_text(encoding="utf-8")
    assert "Demo" in html
    assert "Demo Talk" in html or "talks/" in html
    # talk page
    talks = list((out / "talks").glob("*/page.html"))
    assert len(talks) == 1
    page = talks[0].read_text(encoding="utf-8")
    assert "转写" in page or "ASR" in page or "dry-run" in page.lower() or "placeholder" in page.lower() or "slides-only" in page or "暂无转写" in page or "note" in page.lower()
    assert (out / "assets" / "styles.css").exists()
