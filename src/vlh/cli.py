"""Typer CLI entry: vlh process / vlh batch."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from vlh import __version__
from vlh.htmlgen.models import SiteIndex
from vlh.htmlgen.site import write_site_index
from vlh.pipeline import process_video
from vlh.util.dedupe import find_duplicate_videos

app = typer.Typer(
    name="vlh",
    help="video-lecture-html — 中文技术演讲 mp4 → 可搜索静态 HTML 学习资料",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"video-lecture-html {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=_version_callback, is_eager=True
    ),
) -> None:
    """Convert lecture videos into searchable HTML study notes."""


@app.command("process")
def process_cmd(
    video: Path = typer.Argument(..., exists=True, readable=True, help="输入视频文件"),
    out: Path = typer.Option(..., "-o", "--out", help="输出站点目录"),
    asr: str = typer.Option("funasr", "--asr", help="funasr | whisper | auto"),
    ocr: str = typer.Option("off", "--ocr", help="on | off（默认 off）"),
    lang: str = typer.Option("zh", "--lang"),
    video_mode: str = typer.Option("link", "--video-mode", help="link | copy | none"),
    slides_only: bool = typer.Option(False, "--slides-only", help="只抽帧，不做 ASR"),
    dry_run: bool = typer.Option(False, "--dry-run", help="不跑 ffmpeg/ASR，只写占位 HTML"),
    sample_interval: float = typer.Option(2.0, "--sample-interval", help="粗召回采样间隔（秒）"),
    site_title: str = typer.Option("Lecture Notes", "--site-title"),
) -> None:
    """处理单个视频，生成 talks/<slug>/page.html 与站点 index。"""
    talk = process_video(
        video,
        out,
        asr=asr,
        ocr=ocr,
        lang=lang,
        video_mode=video_mode,
        slides_only=slides_only,
        dry_run=dry_run,
        sample_interval=sample_interval,
    )
    write_site_index(SiteIndex(title=site_title, talks=[talk], out_dir=out))
    console.print(f"[bold]index[/bold] {out / 'index.html'}")


@app.command("batch")
def batch_cmd(
    directory: Path = typer.Argument(..., exists=True, file_okay=False, help="视频目录"),
    out: Path = typer.Option(..., "-o", "--out", help="输出站点目录"),
    asr: str = typer.Option("funasr", "--asr", help="funasr | whisper | auto"),
    ocr: str = typer.Option("off", "--ocr", help="on | off"),
    lang: str = typer.Option("zh", "--lang"),
    video_mode: str = typer.Option("link", "--video-mode", help="link | copy | none"),
    slides_only: bool = typer.Option(False, "--slides-only"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    skip_dupes: bool = typer.Option(True, "--skip-dupes/--no-skip-dupes", help="跳过同大小重复文件"),
    sample_interval: float = typer.Option(2.0, "--sample-interval"),
    site_title: str = typer.Option("UWA Learning", "--site-title"),
    limit: int = typer.Option(0, "--limit", help="只处理前 N 个（0=全部）"),
) -> None:
    """批处理目录内视频；按【分类】文件名分组索引。"""
    videos = sorted(
        p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )
    if not videos:
        console.print(f"[red]no videos found under[/red] {directory}")
        raise typer.Exit(code=1)

    skipped_pairs = []
    if skip_dupes:
        videos, skipped_pairs = find_duplicate_videos(videos)
        for dup, kept in skipped_pairs:
            console.print(f"[dim]skip dup[/dim] {dup.name} (== size of {kept.name})")

    if limit > 0:
        videos = videos[:limit]

    talks = []
    for i, v in enumerate(videos, 1):
        console.rule(f"[{i}/{len(videos)}] {v.name}")
        try:
            talk = process_video(
                v,
                out,
                asr=asr,
                ocr=ocr,
                lang=lang,
                video_mode=video_mode,
                slides_only=slides_only,
                dry_run=dry_run,
                sample_interval=sample_interval,
            )
            talks.append(talk)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]failed[/red] {v.name}: {e}")

    write_site_index(SiteIndex(title=site_title, talks=talks, out_dir=out))
    console.print(f"[bold green]done[/bold green] {len(talks)} talks → {out / 'index.html'}")
    if skipped_pairs:
        console.print(f"[dim]skipped {len(skipped_pairs)} same-size duplicates[/dim]")


if __name__ == "__main__":
    app()
