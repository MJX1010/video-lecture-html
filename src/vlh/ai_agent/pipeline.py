"""Map-reduce AI analysis over lecture chapters."""

from __future__ import annotations

import hashlib
import threading
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from vlh.analysis.build import build_analysis, concatenate_full_text, merge_segments_to_paragraphs
from vlh.ai_agent.prompts import (
    PROMPT_VERSION,
    SYSTEM,
    chapter_user_prompt,
    reduce_user_prompt,
    verify_user_prompt,
)
from vlh.llm.client import LLMClient, LLMConfig

ProgressCb = Callable[[str], None]


@dataclass
class AIChapter:
    index: int
    title: str
    start: float
    end: float
    slide_index: int | None
    slide_image: str | None
    rewrite: str
    key_points: list[str] = field(default_factory=list)
    terms: list[dict[str, str]] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    source_chars: int = 0
    cache_hit: bool = False

    @property
    def anchor(self) -> str:
        return f"ch-{self.index}"

    @property
    def start_label(self) -> str:
        sec = max(0, int(self.start))
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def paragraphs(self) -> list[str]:
        parts = [p.strip() for p in (self.rewrite or "").split("\n\n")]
        return [p for p in parts if p]


@dataclass
class AIAnalysisResult:
    one_liner: str
    overview: str
    key_points: list[str]
    glossary: list[dict[str, str]]
    practice_tips: list[str]
    limitations: list[str]
    further_keywords: list[str]
    chapters: list[AIChapter]
    model: str
    provider: str
    prompt_version: str = PROMPT_VERSION
    method: str = "ai-agent"
    label: str = "AI 整理"
    status: str = "ok"
    error: str = ""
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "one_liner": self.one_liner,
            "overview": self.overview,
            "key_points": self.key_points,
            "glossary": self.glossary,
            "practice_tips": self.practice_tips,
            "limitations": self.limitations,
            "further_keywords": self.further_keywords,
            "chapters": [
                {
                    "index": c.index,
                    "title": c.title,
                    "start": c.start,
                    "end": c.end,
                    "slide_index": c.slide_index,
                    "slide_image": c.slide_image,
                    "rewrite": c.rewrite,
                    "paragraphs": c.paragraphs,
                    "key_points": c.key_points,
                    "terms": c.terms,
                    "uncertain": c.uncertain,
                    "source_chars": c.source_chars,
                    "cache_hit": c.cache_hit,
                }
                for c in self.chapters
            ],
            "model": self.model,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
            "method": self.method,
            "label": self.label,
            "status": self.status,
            "error": self.error,
            "stats": self.stats,
        }


def _hash_payload(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _chapter_transcript(segments: list[dict[str, Any]], start: float, end: float, last: bool) -> str:
    segs = []
    for s in segments:
        st = float(s.get("start") or 0)
        if last:
            if st >= start:
                segs.append(s)
        else:
            if start <= st < end:
                segs.append(s)
    paras = merge_segments_to_paragraphs(segs, max_chars=220, max_gap=2.0)
    return "\n\n".join(paras) if paras else concatenate_full_text(segs)


def _split_oversized(text: str, max_chars: int = 9000) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    paras = text.split("\n\n")
    buf: list[str] = []
    n = 0
    for p in paras:
        if n + len(p) > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf, n = [], 0
        buf.append(p)
        n += len(p) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks or [text[:max_chars]]


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"chapters": {}, "reduce": None, "meta": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"chapters": {}, "reduce": None, "meta": {}}
    if not isinstance(data, dict):
        return {"chapters": {}, "reduce": None, "meta": {}}
    data.setdefault("chapters", {})
    data.setdefault("reduce", None)
    data.setdefault("meta", {})
    return data


def _save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_terms(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            term = str(item.get("term") or item.get("name") or "").strip()
            definition = str(item.get("definition") or item.get("desc") or "").strip()
            if term:
                out.append({"term": term, "definition": definition})
        elif isinstance(item, str) and item.strip():
            out.append({"term": item.strip(), "definition": ""})
    return out


def _analyze_one_chapter(
    client: LLMClient,
    *,
    talk_title: str,
    chapter_index: int,
    chapter_count: int,
    start: float,
    end: float,
    transcript: str,
    ocr_text: str,
    slide_index: int | None,
    slide_image: str | None,
    cache: dict[str, Any],
    verify: bool,
    progress: ProgressCb | None,
) -> AIChapter:
    cache_key_payload = {
        "pv": PROMPT_VERSION,
        "model": client.config.model,
        "title": talk_title,
        "idx": chapter_index,
        "start": round(start, 2),
        "end": round(end, 2),
        "transcript": transcript,
        "ocr": ocr_text,
    }
    cache_key = _hash_payload(cache_key_payload)
    cached = (cache.get("chapters") or {}).get(cache_key)
    if isinstance(cached, dict) and cached.get("rewrite"):
        if progress:
            progress(f"chapter {chapter_index}/{chapter_count} cache-hit")
        return AIChapter(
            index=chapter_index,
            title=str(cached.get("title") or f"第 {chapter_index} 章"),
            start=start,
            end=end,
            slide_index=slide_index,
            slide_image=slide_image,
            rewrite=str(cached.get("rewrite") or ""),
            key_points=[str(x) for x in (cached.get("key_points") or []) if str(x).strip()],
            terms=_normalize_terms(cached.get("terms")),
            uncertain=[str(x) for x in (cached.get("uncertain") or []) if str(x).strip()],
            source_chars=len(transcript),
            cache_hit=True,
        )

    if progress:
        progress(f"chapter {chapter_index}/{chapter_count} LLM…")

    # If oversized, map subchunks then merge with one reduce-ish call
    pieces = _split_oversized(transcript, max_chars=9000)
    if len(pieces) == 1:
        obj = client.chat_json(
            [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": chapter_user_prompt(
                        talk_title=talk_title,
                        chapter_index=chapter_index,
                        chapter_count=chapter_count,
                        start=start,
                        end=end,
                        transcript=pieces[0],
                        ocr_text=ocr_text,
                    ),
                },
            ],
            max_tokens=3500,
        )
    else:
        sub_rewrites = []
        for si, piece in enumerate(pieces, 1):
            sub = client.chat_json(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": chapter_user_prompt(
                            talk_title=talk_title,
                            chapter_index=chapter_index,
                            chapter_count=chapter_count,
                            start=start,
                            end=end,
                            transcript=f"（子段 {si}/{len(pieces)}）\n{piece}",
                            ocr_text=ocr_text if si == 1 else "",
                        ),
                    },
                ],
                max_tokens=2800,
            )
            sub_rewrites.append(sub)
        merge_prompt = (
            f"合并同一章节的 {len(sub_rewrites)} 段分析结果为单一 JSON（字段同章节分析）。"
            f"演讲《{talk_title}》第 {chapter_index} 章。\n"
            + json.dumps(sub_rewrites, ensure_ascii=False)
        )
        obj = client.chat_json(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": merge_prompt},
            ],
            max_tokens=3500,
        )

    title = str(obj.get("title") or f"第 {chapter_index} 章").strip()
    rewrite = str(obj.get("rewrite") or "").strip()
    key_points = [str(x).strip() for x in (obj.get("key_points") or []) if str(x).strip()]
    terms = _normalize_terms(obj.get("terms"))
    uncertain = [str(x).strip() for x in (obj.get("uncertain") or []) if str(x).strip()]

    if verify and rewrite and transcript:
        try:
            v = client.chat_json(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": verify_user_prompt(
                            chapter_title=title, source=transcript, rewrite=rewrite
                        ),
                    },
                ],
                max_tokens=3500,
            )
            fixed = str(v.get("rewrite_fixed") or "").strip()
            if fixed:
                rewrite = fixed
            if isinstance(v.get("issues"), list):
                for issue in v["issues"]:
                    s = str(issue).strip()
                    if s and s not in uncertain:
                        uncertain.append(s)
        except Exception:  # noqa: BLE001
            pass

    entry = {
        "title": title,
        "rewrite": rewrite,
        "key_points": key_points,
        "terms": terms,
        "uncertain": uncertain,
    }
    cache.setdefault("chapters", {})[cache_key] = entry

    return AIChapter(
        index=chapter_index,
        title=title,
        start=start,
        end=end,
        slide_index=slide_index,
        slide_image=slide_image,
        rewrite=rewrite,
        key_points=key_points,
        terms=terms,
        uncertain=uncertain,
        source_chars=len(transcript),
        cache_hit=False,
    )


def run_ai_analysis(
    *,
    title: str,
    segments: list[dict[str, Any]],
    slides: list[dict[str, Any]],
    duration_sec: float,
    client: LLMClient,
    cache_path: Path,
    concurrency: int = 4,
    verify: bool = False,
    progress: ProgressCb | None = None,
) -> AIAnalysisResult:
    t0 = time.time()
    # Reuse rule chapterization for boundaries
    rule = build_analysis(
        title=title,
        segments=segments,
        slides=slides,
        duration_sec=duration_sec,
    )
    cache = _load_cache(cache_path)
    chapters_out: list[AIChapter] = []

    work = []
    for c in rule.chapters:
        transcript = _chapter_transcript(
            segments, c.start, c.end, last=(c.index == rule.chapters[-1].index)
        )
        ocr = ""
        if c.slide_index is not None:
            for s in slides:
                if int(s.get("index") if s.get("index") is not None else -1) == int(c.slide_index):
                    ocr = str(s.get("ocr") or "")
                    break
        work.append((c, transcript, ocr))

    # Sequential or threaded map
    results: dict[int, AIChapter] = {}

    cache_lock = threading.Lock()

    def _job_safe(item: tuple) -> AIChapter:
        c, transcript, ocr = item
        # Each job mutates cache; serialize cache writes via lock around whole chapter call
        with cache_lock:
            ch = _analyze_one_chapter(
                client,
                talk_title=title,
                chapter_index=c.index,
                chapter_count=len(rule.chapters),
                start=c.start,
                end=c.end,
                transcript=transcript,
                ocr_text=ocr,
                slide_index=c.slide_index,
                slide_image=c.slide_image,
                cache=cache,
                verify=verify,
                progress=progress,
            )
            _save_cache(cache_path, cache)
            return ch

    # NOTE: lock wraps full chapter LLM call => concurrency mainly helps when cache hits.
    # For true parallel LLM, use per-chapter temp results then merge.
    if concurrency <= 1:
        for item in work:
            ch = _job_safe(item)
            results[ch.index] = ch
    else:
        # Parallel LLM calls with post-merge into cache
        def _job_parallel(item: tuple) -> AIChapter:
            c, transcript, ocr = item
            # Use a private mini-cache shadow for this call's write, then merge
            local_cache = {"chapters": dict(cache.get("chapters") or {}), "reduce": cache.get("reduce"), "meta": {}}
            ch = _analyze_one_chapter(
                client,
                talk_title=title,
                chapter_index=c.index,
                chapter_count=len(rule.chapters),
                start=c.start,
                end=c.end,
                transcript=transcript,
                ocr_text=ocr,
                slide_index=c.slide_index,
                slide_image=c.slide_image,
                cache=local_cache,
                verify=verify,
                progress=progress,
            )
            with cache_lock:
                cache.setdefault("chapters", {}).update(local_cache.get("chapters") or {})
                _save_cache(cache_path, cache)
            return ch

        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futs = [ex.submit(_job_parallel, item) for item in work]
            for fut in as_completed(futs):
                ch = fut.result()
                results[ch.index] = ch

    chapters_out = [results[i] for i in sorted(results)]

    # Reduce
    chapter_summaries = [
        {
            "index": c.index,
            "title": c.title,
            "start": c.start,
            "end": c.end,
            "key_points": c.key_points,
            "terms": c.terms,
            "rewrite_excerpt": (c.rewrite or "")[:1200],
        }
        for c in chapters_out
    ]
    reduce_payload = {
        "pv": PROMPT_VERSION,
        "model": client.config.model,
        "title": title,
        "summaries": chapter_summaries,
    }
    reduce_key = _hash_payload(reduce_payload)
    reduce_obj = None
    cached_reduce = cache.get("reduce")
    if (
        isinstance(cached_reduce, dict)
        and cached_reduce.get("_key") == reduce_key
        and cached_reduce.get("one_liner")
    ):
        reduce_obj = cached_reduce
        if progress:
            progress("reduce cache-hit")
    else:
        if progress:
            progress("reduce LLM…")
        reduce_obj = client.chat_json(
            [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": reduce_user_prompt(
                        talk_title=title,
                        duration_sec=duration_sec,
                        chapter_summaries_json=json.dumps(chapter_summaries, ensure_ascii=False),
                    ),
                },
            ],
            max_tokens=3500,
        )
        reduce_obj["_key"] = reduce_key
        cache["reduce"] = reduce_obj
        _save_cache(cache_path, cache)

    overview = str(reduce_obj.get("overview") or "").strip()
    one_liner = str(reduce_obj.get("one_liner") or "").strip()
    key_points = [str(x).strip() for x in (reduce_obj.get("key_points") or []) if str(x).strip()]
    glossary = _normalize_terms(reduce_obj.get("glossary"))
    # merge chapter terms into glossary if missing
    seen = {g["term"].lower() for g in glossary}
    for c in chapters_out:
        for t in c.terms:
            if t["term"].lower() not in seen:
                glossary.append(t)
                seen.add(t["term"].lower())
    practice_tips = [str(x).strip() for x in (reduce_obj.get("practice_tips") or []) if str(x).strip()]
    limitations = [str(x).strip() for x in (reduce_obj.get("limitations") or []) if str(x).strip()]
    further_keywords = [
        str(x).strip() for x in (reduce_obj.get("further_keywords") or []) if str(x).strip()
    ]

    elapsed = time.time() - t0
    cache_hits = sum(1 for c in chapters_out if c.cache_hit)
    stats = {
        "chapter_count": len(chapters_out),
        "cache_hits": cache_hits,
        "elapsed_sec": round(elapsed, 2),
        "duration_sec": duration_sec,
        "segment_count": len(segments),
        "slide_count": len(slides),
        "model": client.config.model,
        "provider": client.config.provider,
        "prompt_version": PROMPT_VERSION,
        "verify": verify,
    }
    cache["meta"] = {
        "title": title,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stats": stats,
    }
    _save_cache(cache_path, cache)

    return AIAnalysisResult(
        one_liner=one_liner or title,
        overview=overview,
        key_points=key_points,
        glossary=glossary,
        practice_tips=practice_tips,
        limitations=limitations,
        further_keywords=further_keywords,
        chapters=chapters_out,
        model=client.config.model,
        provider=client.config.provider,
        stats=stats,
        label=f"AI 整理（模型：{client.config.model}）",
    )
