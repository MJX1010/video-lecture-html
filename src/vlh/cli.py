"""Typer CLI entry: vlh process / vlh batch / vlh enrich."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from vlh import __version__
from vlh.enrich import attach_analysis, enrich_site
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
    no_analysis: bool = typer.Option(False, "--no-analysis", help="跳过内容分析整理"),
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
    if not no_analysis:
        attach_analysis(talk)
        from vlh.htmlgen.site import write_talk_page

        write_talk_page(talk, out)
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
    no_analysis: bool = typer.Option(False, "--no-analysis", help="跳过内容分析整理"),
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
            if not no_analysis:
                attach_analysis(talk)
                from vlh.htmlgen.site import write_talk_page

                write_talk_page(talk, out)
            talks.append(talk)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]failed[/red] {v.name}: {e}")

    write_site_index(SiteIndex(title=site_title, talks=talks, out_dir=out))
    console.print(f"[bold green]done[/bold green] {len(talks)} talks → {out / 'index.html'}")
    if skipped_pairs:
        console.print(f"[dim]skipped {len(skipped_pairs)} same-size duplicates[/dim]")


def enrich_cmd(
    site: Path = typer.Argument(..., exists=True, file_okay=False, help="已有站点目录（含 talks/*/meta.json）"),
    site_title: str = typer.Option("UWA Learning", "--site-title"),
    force: bool = typer.Option(True, "--force/--no-force", help="强制重算分析（默认开）"),
    limit: int = typer.Option(0, "--limit", help="只处理前 N 个讲次（0=全部）"),
) -> None:
    """从已有 meta.json 重建「完整内容分析」HTML，不重跑 ASR / 抽帧。"""
    ok, failed, errors = enrich_site(
        site, site_title=site_title, force=force, limit=limit
    )
    if failed:
        console.print(f"[yellow]failures[/yellow] {failed}")
        for e in errors[:20]:
            console.print(f"  - {e}")
        raise typer.Exit(code=1)
    console.print(f"[bold]ok[/bold] {ok} talks enriched")


app.command("enrich")(enrich_cmd)
app.command("rebuild-html")(enrich_cmd)

def ai_enrich_cmd(
    site: Path = typer.Argument(..., exists=True, file_okay=False, help="已有站点目录（含 talks/*/meta.json）"),
    site_title: str = typer.Option("UWA Learning", "--site-title"),
    model: str = typer.Option("", "--model", help="覆盖模型名，如 deepseek-chat / qwen2.5:14b"),
    base_url: str = typer.Option("", "--base-url", help="OpenAI 兼容 base URL"),
    api_key_env: str = typer.Option("", "--api-key-env", help="从该环境变量读取 API Key（不写死密钥）"),
    provider: str = typer.Option("", "--provider", help="deepseek | ollama | openai-compatible"),
    concurrency: int = typer.Option(4, "--concurrency", "-j", help="章节并发（本地建议 1）"),
    verify: bool = typer.Option(False, "--verify/--no-verify", help="章节自检二次调用"),
    limit: int = typer.Option(0, "--limit", help="只处理前 N 个讲次"),
    only: str = typer.Option("", "--only", help="只处理 slug 包含该子串的讲次（试点用）"),
    no_fallback: bool = typer.Option(False, "--no-fallback", help="AI 失败时不回退规则分析"),
) -> None:
    """AI Agent：阅读转写→分析→整理→重写精读 HTML（可缓存续跑，不重跑 ASR）。"""
    from vlh.ai_enrich import ai_enrich_site
    from vlh.llm.client import resolve_llm_config

    cfg = resolve_llm_config(
        base_url=base_url or None,
        model=model or None,
        api_key_env=api_key_env or None,
        provider=provider or None,
    )
    ok, failed, errors = ai_enrich_site(
        site,
        site_title=site_title,
        config=cfg,
        concurrency=concurrency,
        verify=verify,
        limit=limit,
        only_slug=only or None,
        fallback_rule=not no_fallback,
    )
    if failed:
        console.print(f"[yellow]failures[/yellow] {failed}")
        for e in errors[:20]:
            console.print(f"  - {e}")
        raise typer.Exit(code=1)
    console.print(f"[bold]ok[/bold] {ok} talks ai-enriched")


app.command("ai-enrich")(ai_enrich_cmd)




if __name__ == "__main__":
    app()
