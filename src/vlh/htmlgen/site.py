from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import SiteIndex, TalkPage


def _templates_dir() -> Path:
    """Resolve templates: packaged copy first, then repo templates/vlh."""
    packaged = Path(__file__).resolve().parent.parent / "templates"
    if (packaged / "talk.html").exists():
        return packaged
    here = Path(__file__).resolve()
    for c in (
        here.parents[3] / "templates" / "vlh",
        here.parents[2] / "templates" / "vlh",
    ):
        if (c / "talk.html").exists():
            return c
    raise FileNotFoundError(
        "Cannot find talk.html templates (expected under src/vlh/templates or templates/vlh)."
    )


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_templates_dir())),
        autoescape=select_autoescape(["html", "xml"]),
    )


def copy_static(out_dir: Path) -> None:
    src = _templates_dir() / "styles.css"
    dest_dir = out_dir / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dest_dir / "styles.css")


def write_talk_page(talk: TalkPage, site_root: Path) -> Path:
    talk_dir = site_root / "talks" / talk.slug
    talk_dir.mkdir(parents=True, exist_ok=True)
    env = _env()
    html = env.get_template("talk.html").render(talk=talk, root_href="../../")
    out = talk_dir / "page.html"
    out.write_text(html, encoding="utf-8")
    meta = {
        "slug": talk.slug,
        "title": talk.title,
        "category": talk.category,
        "speaker": talk.speaker,
        "duration_sec": talk.duration_sec,
        "asr_backend": talk.asr_backend,
        "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in talk.segments],
        "slides": [
            {"index": s.index, "time_sec": s.time_sec, "image": s.image_rel, "ocr": s.ocr_text}
            for s in talk.slides
        ],
    }
    (talk_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def write_site_index(index: SiteIndex) -> Path:
    copy_static(index.out_dir)
    groups: dict[str, list[TalkPage]] = {}
    for t in index.talks:
        key = t.category or "未分类"
        groups.setdefault(key, []).append(t)
    env = _env()
    html = env.get_template("index.html").render(
        site_title=index.title,
        groups=sorted(groups.items(), key=lambda kv: kv[0]),
        talks=index.talks,
        root_href="./",
    )
    out = index.out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out
