from vlh.analysis import build_analysis


def test_build_analysis_chapters_and_paragraphs():
    segments = []
    t = 0.0
    texts = [
        "今天介绍性能优化的核心思路。",
        "首先看 CPU 瓶颈。",
        "呃",
        "因此我们采用多线程方案。",
        "注意内存分配次数。",
        "总结一下，关键是减少主线程等待。",
    ]
    for text in texts:
        segments.append({"start": t, "end": t + 2, "text": text})
        t += 2.5
    slides = [
        {"index": 0, "time_sec": 0.0, "image": "slides/a.jpg"},
        {"index": 1, "time_sec": 5.0, "image": "slides/b.jpg"},
        {"index": 2, "time_sec": 12.0, "image": "slides/c.jpg"},
    ]
    a = build_analysis(title="Demo 优化", segments=segments, slides=slides, duration_sec=20)
    assert a.chapters
    assert a.full_text
    assert "自动整理" in a.overview or "本讲" in a.overview
    assert a.key_points
    # paragraphs should merge fillers away
    joined = " ".join(p for c in a.chapters for p in c.paragraphs)
    assert "呃" not in joined or joined.count("呃") == 0


def test_enrich_cli_help():
    from typer.testing import CliRunner
    from vlh.cli import app

    r = CliRunner().invoke(app, ["enrich", "--help"])
    assert r.exit_code == 0
    assert "meta.json" in r.stdout
