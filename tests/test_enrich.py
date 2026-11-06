import json
from pathlib import Path

from typer.testing import CliRunner

from vlh.cli import app

runner = CliRunner()


def test_enrich_rebuilds_analysis_html(tmp_path: Path):
    site = tmp_path / "site"
    talk = site / "talks" / "demo-talk"
    talk.mkdir(parents=True)
    (talk / "slides").mkdir()
    meta = {
        "slug": "demo-talk",
        "title": "演示：内容分析",
        "category": "UWA 2024",
        "speaker": None,
        "duration_sec": 30,
        "asr_backend": "funasr",
        "asr_note": "test",
        "source_name": "demo.mp4",
        "video_href": None,
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "欢迎来到本讲。"},
            {"start": 2.2, "end": 5.0, "text": "核心是把转写整理成可读章节。"},
            {"start": 10.0, "end": 13.0, "text": "因此我们按幻灯片时间切分。"},
            {"start": 20.0, "end": 24.0, "text": "总结：enrich 不需要重跑 ASR。"},
        ],
        "slides": [
            {"index": 0, "time_sec": 0.0, "image": "slides/slide_0000.jpg", "ocr": ""},
            {"index": 1, "time_sec": 10.0, "image": "slides/slide_0001.jpg", "ocr": ""},
        ],
    }
    (talk / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    # placeholder images not required for HTML
    r = runner.invoke(app, ["enrich", str(site), "--site-title", "Demo Site"])
    assert r.exit_code == 0, r.stdout + str(r.exception)
    page = (talk / "page.html").read_text(encoding="utf-8")
    assert "内容概览" in page
    assert "分章精读" in page
    assert "要点" in page
    assert "原始材料" in page
    assert (talk / "analysis.json").exists()
    assert (site / "index.html").exists()
    assert "Demo Site" in (site / "index.html").read_text(encoding="utf-8")
    meta2 = json.loads((talk / "meta.json").read_text(encoding="utf-8"))
    assert meta2.get("full_text")
    assert meta2.get("analysis", {}).get("chapters")
