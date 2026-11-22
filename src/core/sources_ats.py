#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401
"""Public ATS Collectors (Greenhouse, Lever, Ashby, Greeting) & Multi-Board Deduplication."""
import html
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import urllib.parse

from sources_common import (
    ROOT,
    SCHEMA_VERSION,
    SourceResult,
    canonical_url,
    clean_text,
    evidence,
    extract_tech_stack,
    fetch_bytes,
    fetch_json,
    load_fixture,
    normalize_date,
    source_id_from_url,
    split_filter_terms,
)
from sources_kr_jobs import (
    collect_jobkorea,
    collect_jumpit,
    collect_saramin,
    collect_wanted,
)

# ---------------------------------------------------------------------------
# Public ATS (Greenhouse, Lever, Ashby, Greeting) + Batch Multi-Company Scanner
# ---------------------------------------------------------------------------

ATS_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
    "greeting": "https://{token}.career.greetinghr.com/ko/career",
}


def normalize_greeting_html(
    raw: bytes | str,
    token: str,
    company: str,
    retrieved_at: str,
    limit: int = 50,
) -> SourceResult:
    source = f"ats:greeting:{token}"
    try:
        page = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        return SourceResult("invalid_response", source, errors=["Greeting page was not UTF-8"])

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Try Next.js __NEXT_DATA__ first
    next_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S | re.I)
    if next_match:
        try:
            data = json.loads(next_match.group(1))
            found: list[dict[str, Any]] = []
            def walk(node: Any) -> None:
                if isinstance(node, list):
                    for item in node:
                        if isinstance(item, dict) and item.get("id") and (item.get("title") or item.get("name")) and (
                            "opening" in str(item).lower() or "jobPosition" in item or "employmentType" in item or "careerType" in item
                        ):
                            found.append(item)
                        else:
                            walk(item)
                elif isinstance(node, dict):
                    for v in node.values():
                        walk(v)
            walk(data)
            for item in found[:limit]:
                oid = str(item.get("id") or "").strip()
                title = clean_text(item.get("title") or item.get("name") or "")
                if not oid or not title:
                    continue
                sid = f"greeting:{token}:{oid}"
                if sid in seen:
                    continue
                seen.add(sid)
                url = f"https://{token}.career.greetinghr.com/ko/o/{oid}"
                loc = clean_text(item.get("location") or item.get("place") or "") or None
                dept = clean_text(item.get("jobPosition") or item.get("department") or "") or None
                rows.append({
                    "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
                    "source": source, "source_id": sid,
                    "company": company, "company_candidate": company,
                    "company_confidence": "provided",
                    "title": title, "description": (f"부서: {dept}" if dept else None),
                    "url": url, "published_at": normalize_date(item.get("createdAt") or item.get("openedAt")),
                    "stack": extract_tech_stack(title), "location": loc,
                    "review_required": False,
                    "evidence": evidence(source, sid, url, retrieved_at, item),
                })
        except json.JSONDecodeError:
            pass

    if not rows:
        for m in re.finditer(r'href="(/(?:ko/)?o/(\d+)[^"]*)"[^>]*>(.*?)</a>', page, re.S | re.I):
            if len(rows) >= limit:
                break
            oid = m.group(2)
            title = clean_text(m.group(3))
            if not title or len(title) < 2:
                continue
            sid = f"greeting:{token}:{oid}"
            if sid in seen:
                continue
            seen.add(sid)
            url = f"https://{token}.career.greetinghr.com/ko/o/{oid}"
            rows.append({
                "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
                "source": source, "source_id": sid,
                "company": company, "company_candidate": company,
                "company_confidence": "provided",
                "title": title, "description": None, "url": url, "published_at": None,
                "stack": extract_tech_stack(title), "location": None,
                "review_required": False,
                "evidence": evidence(source, sid, url, retrieved_at, {"id": oid, "title": title}),
            })

    if not rows:
        if re.search(r"진행\s*중인\s*채용이\s*없|채용\s*공고가\s*없", clean_text(page)):
            return SourceResult("empty", source)
        return SourceResult("empty", source, metadata={"note": "no open Greeting postings matched"})
    return SourceResult("ok", source, rows)


def normalize_ats(payload: Any, provider: str, token: str, company: str, retrieved_at: str, limit: int) -> SourceResult:
    source = f"ats:{provider}:{token}"
    if provider == "greeting":
        if isinstance(payload, (bytes, str)):
            return normalize_greeting_html(payload, token, company, retrieved_at, limit)
        return SourceResult("invalid_response", source, errors=["greeting: expected HTML response"])
    if provider in ("greenhouse", "ashby"):
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            return SourceResult("invalid_response", source, errors=[f"{provider}: expected object with jobs list"])
        jobs = payload["jobs"]
    elif provider == "lever":
        if not isinstance(payload, list):
            return SourceResult("invalid_response", source, errors=["lever: expected a JSON list"])
        jobs = payload
    else:
        return SourceResult("invalid_response", source, errors=["unsupported ATS provider"])
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, job in enumerate(jobs[:limit]):
        if not isinstance(job, dict):
            errors.append(f"row {index}: expected object")
            continue
        desc = ""
        if provider == "greenhouse":
            title = clean_text(job.get("title"))
            location = clean_text((job.get("location") or {}).get("name") if isinstance(job.get("location"), dict) else None)
            url = canonical_url(job.get("absolute_url"))
            native_id = job.get("id")
            published = job.get("updated_at")
            desc = clean_text(job.get("content"))[:1500]
        elif provider == "lever":
            title = clean_text(job.get("text"))
            location = clean_text((job.get("categories") or {}).get("location") if isinstance(job.get("categories"), dict) else None)
            url = canonical_url(job.get("hostedUrl"))
            native_id = job.get("id")
            published = job.get("createdAt")
            desc = clean_text(job.get("descriptionPlain") or job.get("description"))[:1500]
        else:
            title = clean_text(job.get("title"))
            location = clean_text(job.get("location"))
            url = canonical_url(job.get("jobUrl") or job.get("applyUrl"))
            native_id = job.get("id")
            published = job.get("publishedAt")
            desc = clean_text(job.get("descriptionPlain") or job.get("descriptionHtml"))[:1500]
        if not title or not url:
            errors.append(f"row {index}: title and public URL are required")
            continue
        sid = f"{provider}:{native_id}" if native_id is not None and str(native_id).strip() else source_id_from_url(source, url)
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "record_type": "job_posting",
            "source": source,
            "source_id": sid,
            "company": company,
            "company_candidate": company,
            "company_confidence": "provided",
            "title": title,
            "description": desc or None,
            "url": url,
            "published_at": normalize_date(published),
            "stack": extract_tech_stack(f"{title} {desc}"),
            "location": location or None,
            "review_required": False,
            "evidence": evidence(source, sid, url, retrieved_at, job),
        })
    status = "ok" if rows else ("invalid_response" if errors else "empty")
    return SourceResult(status, source, rows, errors)


def collect_ats(
    provider: str,
    token: str,
    company: str,
    limit: int,
    fixture: str | None,
    retrieved_at: str,
    *,
    opener=None,
) -> SourceResult:
    source = f"ats:{provider}:{token}"
    if provider == "greeting":
        if fixture:
            try:
                raw = Path(fixture).read_bytes()
                return normalize_greeting_html(raw, token, company, retrieved_at, limit)
            except OSError as exc:
                return SourceResult("failed", source, errors=[f"fixture read failed: {exc}"])
        safe_token = urllib.parse.quote(token, safe="")
        status, raw, error = fetch_bytes(ATS_URLS["greeting"].format(token=safe_token), source, opener=opener)
        if status != "ok" or raw is None:
            return SourceResult(status, source, errors=[error or "Greeting ATS failed"])
        return normalize_greeting_html(raw, token, company, retrieved_at, limit)

    if fixture:
        status, payload, error = load_fixture(fixture)
    else:
        safe_token = urllib.parse.quote(token, safe="")
        status, payload, error = fetch_json(ATS_URLS[provider].format(token=safe_token), source, opener=opener)
    if status != "ok":
        return SourceResult(status, source, errors=[error or "ATS source failed"])
    return normalize_ats(payload, provider, token, company, retrieved_at, limit)


def load_ats_targets(path: str | Path | None = None, home: str | Path | None = None) -> list[dict[str, str]]:
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path).expanduser().absolute())
    if home:
        candidates.append(Path(home).expanduser().absolute() / "ats-targets.json")
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        candidates.append(Path(env_home).expanduser().absolute() / "ats-targets.json")
    candidates.append(ROOT / "pack" / "skills" / "ats-search" / "data" / "ats-targets.json")
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
                if isinstance(data, list):
                    return [t for t in data if isinstance(t, dict) and t.get("ats") in ATS_URLS and t.get("token")]
            except (OSError, ValueError):
                continue
    return []


def collect_ats_batch(
    targets: list[dict[str, str]],
    retrieved_at: str,
    *,
    keyword: str = "",
    limit: int = 50,
    per_company_limit: int = 30,
    delay: float = 0.35,
    partial_ok: bool = True,
    opener=None,
) -> SourceResult:
    """Scan a list of public ATS boards (Greenhouse/Lever/Ashby/Greeting)."""
    if not targets:
        return SourceResult("empty", "ats-batch", metadata={"targets": 0})
    results: list[SourceResult] = []
    terms = split_filter_terms(keyword)
    for idx, target in enumerate(targets[:25]):
        provider = str(target.get("ats", "")).strip().lower()
        token = str(target.get("token", "")).strip()
        company = str(target.get("company") or token).strip()
        if provider not in ATS_URLS or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", token):
            continue
        res = collect_ats(provider, token, company, per_company_limit, None, retrieved_at, opener=opener)
        if res.status == "ok" and terms:
            filtered = [
                r for r in res.records
                if any(t in f"{r.get('title', '')} {r.get('description') or ''}".casefold() for t in terms)
            ]
            res = SourceResult("ok" if filtered else "empty", res.source, filtered, res.errors, res.metadata)
        results.append(res)
        if idx + 1 < len(targets) and delay > 0:
            time.sleep(delay)
    combined = combine_job_search(results, partial_ok=partial_ok, label="ats-batch")
    if len(combined.records) > limit:
        combined.records = combined.records[:limit]
    return combined


# ---------------------------------------------------------------------------
# Cross-Board Deduplication & Multi-Source Job Orchestrator
# ---------------------------------------------------------------------------

def _norm_company_key(name: str | None) -> str:
    cleaned = re.sub(r"\(주\)|주식회사|㈜|\(유\)|\binc\.?\b|\bcorp\.?\b|\bltd\.?\b|\bco\.?\b", "", (name or ""), flags=re.I)
    return re.sub(r"[^가-힣a-z0-9]", "", cleaned.lower())


def _norm_title_key(title: str | None) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", (title or "").lower())


def combine_job_search(
    results: list[SourceResult],
    *,
    partial_ok: bool = False,
    dedupe_cross_board: bool = True,
    label: str = "wanted+saramin-public-search",
) -> SourceResult:
    """Combine explicit providers with transparent status tracking and cross-board dedupe.

    When partial_ok=False (strict legacy contract), any provider failure returns a
    failure status so callers never mistake partial results for full coverage.
    When partial_ok=True, valid records from healthy providers are kept while
    failed/blocked providers are explicitly recorded in metadata.partial_failures
    and errors.
    """
    if not results:
        raise ValueError("at least one source result is required")
    provider_statuses = [
        {"source": item.source, "status": item.status, "record_count": len(item.records)}
        for item in results
    ]
    metadata: dict[str, Any] = {"sources": provider_statuses}
    errors = [message for item in results for message in item.errors]
    records: list[dict[str, Any]] = []
    seen_ids: set[tuple[str, str]] = set()
    seen_company_title: dict[tuple[str, str], dict[str, Any]] = {}
    cross_dupes = 0

    for item in results:
        for record in item.records:
            id_key = (str(record.get("source")), str(record.get("source_id")))
            if id_key in seen_ids:
                continue
            seen_ids.add(id_key)
            if dedupe_cross_board:
                ckey = _norm_company_key(record.get("company") or record.get("company_candidate"))
                tkey = _norm_title_key(record.get("title"))
                if ckey and tkey and (ckey, tkey) in seen_company_title:
                    existing = seen_company_title[(ckey, tkey)]
                    extra = existing.setdefault("also_seen_urls", [])
                    if record.get("url") and record["url"] not in extra and record["url"] != existing.get("url"):
                        extra.append(record["url"])
                    # Merge stack & description if existing lacked them
                    if record.get("stack"):
                        existing["stack"] = extract_tech_stack("", (existing.get("stack") or []) + record["stack"])
                    if not existing.get("description") and record.get("description"):
                        existing["description"] = record["description"]
                    cross_dupes += 1
                    continue
                if ckey and tkey:
                    seen_company_title[(ckey, tkey)] = record
            records.append(record)

    metadata["cross_board_duplicates_merged"] = cross_dupes
    failures = [item for item in results if item.status not in ("ok", "empty")]
    if failures:
        failure_statuses = [item.status for item in failures]
        metadata["partial_failures"] = [
            {"source": item.source, "status": item.status, "errors": item.errors}
            for item in failures
        ]
        if partial_ok and records:
            metadata["partial_mode"] = True
            return SourceResult("ok", label, records, errors, metadata)
        status = "blocked" if "blocked" in failure_statuses else (
            "invalid_response" if "invalid_response" in failure_statuses else "failed"
        )
        metadata["partial_records_not_committed"] = len(records)
        return SourceResult(status, label, records, errors, metadata)
    return SourceResult("ok" if records else "empty", label, records, errors, metadata)


def collect_jobs_multi(
    providers: list[str],
    queries: list[str],
    retrieved_at: str,
    *,
    pages: int = 2,
    limit: int = 50,
    fetch_details: bool = True,
    partial_ok: bool = True,
    ats_config: dict[str, str] | None = None,
    ats_targets: list[dict[str, str]] | None = None,
    delay: float = 0.5,
    opener=None,
) -> SourceResult:
    """Collect job postings across multiple Korean/global boards and multiple keywords."""
    clean_queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()][:5]
    results: list[SourceResult] = []
    per_query_limit = max(10, min(50, limit))

    for provider in providers:
        if provider == "ats":
            cfg = ats_config or {}
            p, b, c = cfg.get("ats_provider", ""), cfg.get("ats_board", ""), cfg.get("ats_company", "")
            if p and b and c:
                results.append(collect_ats(p, b, c, limit, None, retrieved_at, opener=opener))
            else:
                results.append(SourceResult("failed", "ats-live", errors=[
                    "ats provider에는 ats_provider, ats_board, ats_company가 필요합니다."
                ]))
        elif provider == "ats_batch":
            kw = ", ".join(clean_queries)
            results.append(collect_ats_batch(
                ats_targets or load_ats_targets(), retrieved_at,
                keyword=kw, limit=limit, delay=min(delay, 0.35), partial_ok=partial_ok, opener=opener,
            ))
        elif provider == "greeting":
            cfg = ats_config or {}
            b, c = cfg.get("ats_board", ""), cfg.get("ats_company", "")
            if b and c:
                results.append(collect_ats("greeting", b, c, limit, None, retrieved_at, opener=opener))
            else:
                # Filter ats_targets for greeting boards
                g_targets = [t for t in (ats_targets or load_ats_targets()) if t.get("ats") == "greeting"]
                results.append(collect_ats_batch(
                    g_targets, retrieved_at, keyword=", ".join(clean_queries),
                    limit=limit, partial_ok=partial_ok, opener=opener,
                ))
        elif provider in ("wanted", "saramin", "jobkorea", "jumpit"):
            if not clean_queries:
                results.append(SourceResult("failed", f"{provider}-public-search",
                                            errors=[f"{provider}: 검색어(jobs_query)가 필요합니다."]))
                continue
            for q in clean_queries:
                if provider == "wanted":
                    results.append(collect_wanted(
                        q, per_query_limit, None, retrieved_at,
                        pages=pages, fetch_details=fetch_details, delay=delay, opener=opener,
                    ))
                elif provider == "saramin":
                    results.append(collect_saramin(
                        q, per_query_limit, None, retrieved_at,
                        pages=pages, delay=delay, opener=opener,
                    ))
                elif provider == "jobkorea":
                    results.append(collect_jobkorea(
                        q, per_query_limit, None, retrieved_at,
                        pages=pages, delay=delay, opener=opener,
                    ))
                elif provider == "jumpit":
                    results.append(collect_jumpit(
                        q, per_query_limit, None, retrieved_at,
                        pages=pages, fetch_details=fetch_details, delay=delay, opener=opener,
                    ))

    if not results:
        return SourceResult("failed", "jobs-multi", errors=["선택된 채용 소스가 없습니다."])
    label = "+".join(dict.fromkeys(providers)) + "-public-search"
    combined = combine_job_search(results, partial_ok=partial_ok, dedupe_cross_board=True, label=label)
    if len(combined.records) > limit * 2:
        combined.records = combined.records[:limit * 2]
    return combined


