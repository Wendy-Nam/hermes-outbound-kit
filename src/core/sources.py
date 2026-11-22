#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401
"""Public, read-only source adapters and CLI entry point for Hermes Outbound.

Modularized into dedicated adapter files for maintainability:
- sources_common.py  : HTTP/gzip transport, date/stack/URL normalizers, config filters
- sources_kr_jobs.py : Wanted, Saramin, JobKorea, Jumpit & image JD OCR
- sources_ats.py     : Greenhouse, Lever, Ashby, Greeting & multi-board deduplication
- sources_signals.py : Platum/VentureSquare funding, G2B public tenders, Overseas RSS/ATS
"""
import argparse
import json
from typing import Any

from sources_common import (  # noqa: F401
    G2B_BID_ENDPOINT,
    G2B_ENDPOINTS,
    G2B_ORDER_PLAN_ENDPOINT,
    JOBKOREA_ENDPOINT,
    JUMPIT_DETAIL_ENDPOINT,
    JUMPIT_ENDPOINT,
    MAX_RESPONSE_BYTES,
    ROOT,
    SARAMIN_ENDPOINT,
    SCHEMA_VERSION,
    STATUSES,
    SourceResult,
    TECH_STACK_PATTERNS,
    TYPED_ALIASES,
    USER_AGENT,
    VENTURESQUARE_WP_ENDPOINT,
    WANTED_DETAIL_ENDPOINT,
    WANTED_ENDPOINT,
    WP_ENDPOINT,
    _NoRedirect,
    _compile_stack_pattern,
    _default_opener,
    _fetch_raw,
    _read_limited,
    _typed_lookup,
    apply_config_filters,
    canonical_json,
    canonical_url,
    clean_text,
    disabled_workflow_result,
    evidence,
    extract_tech_stack,
    fetch_bytes,
    fetch_json,
    import_typed,
    load_fixture,
    load_source_config,
    normalize_date,
    normalize_typed_rows,
    sha256,
    source_id_from_url,
    split_filter_terms,
    utc_now,
    workflow_enabled,
)
from sources_kr_jobs import (  # noqa: F401
    ALIASES,
    JOBKOREA_EMPTY,
    SARAMIN_EMPTY,
    _SaraminCardParser,
    _extract_jobkorea_next_data,
    _lookup,
    _parse_saramin_date,
    collect_jobkorea,
    collect_jumpit,
    collect_saramin,
    collect_wanted,
    enrich_image_job,
    enrich_jumpit_detail,
    enrich_wanted_detail,
    extract_job_image_urls,
    import_jobs,
    normalize_job_rows,
    normalize_jobkorea_html,
    normalize_jumpit,
    normalize_saramin_html,
    normalize_stack,
    normalize_wanted,
    read_job_rows,
)
from sources_ats import (  # noqa: F401
    ATS_URLS,
    _norm_company_key,
    _norm_title_key,
    collect_ats,
    collect_ats_batch,
    collect_jobs_multi,
    combine_job_search,
    load_ats_targets,
    normalize_ats,
    normalize_greeting_html,
)
from sources_signals import (  # noqa: F401
    AMOUNT,
    FUNDING_EVENT,
    FUND_EVENT,
    GENERIC_COMPANY,
    INVESTOR_SUFFIX,
    QUOTED_COMPANY,
    ROUND,
    SECTORS,
    _read_env_key,
    collect_funding,
    collect_overseas_signals,
    collect_tenders_g2b,
    enrich_funding_with_hiring,
    funding_company_candidate,
    funding_sector,
    normalize_funding_posts,
    normalize_g2b_items,
    normalize_rss_xml,
)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Read-only outbound funding, job, tender, and partner source adapters")
    sub = ap.add_subparsers(dest="command", required=True)

    funding = sub.add_parser("funding", help="collect bounded public WordPress funding candidates")
    funding.add_argument("--pages", type=int, default=1)
    funding.add_argument("--per-page", type=int, default=10)
    funding.add_argument("--include-venturesquare", action="store_true")
    funding.add_argument("--enrich-hiring", action="store_true")
    funding.add_argument("--fixture")
    funding.add_argument("--as-of")
    funding.add_argument("--config", help="setup.json; applies workflow, keyword, exclusion filters")

    jobs = sub.add_parser("jobs-import", help="normalize a user-provided CSV or JSON job export")
    jobs.add_argument("path")
    jobs.add_argument("--format", choices=("auto", "csv", "json"), default="auto")
    jobs.add_argument("--as-of")
    jobs.add_argument("--config", help="setup.json; applies workflow, keyword, region, exclusion filters")

    ats = sub.add_parser("ats", help="read one public Greenhouse, Lever, Ashby, or Greeting board")
    ats.add_argument("--provider", choices=tuple(ATS_URLS), required=True)
    ats.add_argument("--token", required=True, help="public board slug, not a credential")
    ats.add_argument("--company", required=True)
    ats.add_argument("--limit", type=int, default=50)
    ats.add_argument("--fixture")
    ats.add_argument("--as-of")
    ats.add_argument("--config")

    ats_batch = sub.add_parser("ats-batch", help="scan multiple public ATS boards from ats-targets.json")
    ats_batch.add_argument("--targets", help="path to ats-targets.json")
    ats_batch.add_argument("--keyword", default="")
    ats_batch.add_argument("--limit", type=int, default=50)
    ats_batch.add_argument("--as-of")
    ats_batch.add_argument("--config")

    for board_name, desc in (
        ("wanted", "read bounded public Wanted keyword search (with optional pagination & JD details)"),
        ("saramin", "read bounded public Saramin keyword search pages"),
        ("jobkorea", "read bounded public JobKorea keyword search pages"),
        ("jumpit", "read bounded public Jumpit JSON API search (with tech stacks & optional JD details)"),
    ):
        b = sub.add_parser(board_name, help=desc)
        b.add_argument("query")
        b.add_argument("--limit", type=int, default=20)
        b.add_argument("--pages", type=int, default=1)
        if board_name in ("wanted", "jumpit"):
            b.add_argument("--details", action="store_true", help="fetch job detail JD & skill tags")
        b.add_argument("--fixture")
        b.add_argument("--as-of")
        b.add_argument("--config")

    multi = sub.add_parser("jobs-multi", help="search across multiple job boards with deduplication")
    multi.add_argument("query", help="comma-separated search queries")
    multi.add_argument("--providers", default="wanted,saramin,jumpit", help="comma-separated providers")
    multi.add_argument("--pages", type=int, default=2)
    multi.add_argument("--limit", type=int, default=40)
    multi.add_argument("--details", action="store_true")
    multi.add_argument("--strict", action="store_true", help="fail entire run if any single board fails")
    multi.add_argument("--as-of")
    multi.add_argument("--config")

    tenders = sub.add_parser("tenders", help="query official G2B public bid notices (requires DATA_GO_KR_API_KEY in .env)")
    tenders.add_argument("--query", default="")
    tenders.add_argument("--type", dest="tender_type", choices=("all", "servc", "thng", "cnstwk", "frgcpt"), default="servc")
    tenders.add_argument("--days", type=int, default=14)
    tenders.add_argument("--limit", type=int, default=30)
    tenders.add_argument("--home")
    tenders.add_argument("--fixture")
    tenders.add_argument("--as-of")
    tenders.add_argument("--config")

    overseas = sub.add_parser("overseas", help="collect overseas partner/expansion signals from RSS feeds and/or global ATS")
    overseas.add_argument("--rss", default="", help="comma-separated public RSS/Atom URLs")
    overseas.add_argument("--keyword", default="Korea, APAC, Partner, Sales")
    overseas.add_argument("--limit", type=int, default=30)
    overseas.add_argument("--as-of")
    overseas.add_argument("--config")

    typed = sub.add_parser("typed-import", help="normalize a funding, tender, or overseas partner CSV/JSON export")
    typed.add_argument("path")
    typed.add_argument("--type", choices=("funding_signal", "procurement", "overseas_partner"), required=True)
    typed.add_argument("--format", choices=("auto", "csv", "json"), default="auto")
    typed.add_argument("--as-of")
    typed.add_argument("--config")
    return ap


def exit_code(status: str) -> int:
    return {"ok": 0, "empty": 0, "blocked": 2, "failed": 3, "invalid_response": 4}[status]


def main(argv: list[str] | None = None) -> int:
    ap = parser()
    args = ap.parse_args(argv)
    retrieved_at = args.as_of or utc_now()
    if normalize_date(retrieved_at) is None:
        ap.error("--as-of must be an ISO-8601 date or datetime")
    config: dict[str, Any] | None = None
    if args.config:
        config, config_error = load_source_config(args.config)
        if config_error:
            source = ("platum-wordpress" if args.command == "funding" else
                      f"ats:{args.provider}:{args.token}" if args.command == "ats" else "job-import")
            result = SourceResult("invalid_response", source, errors=[config_error])
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return exit_code(result.status)
    workflow = (
        "funding" if args.command == "funding" else
        "tenders" if args.command == "tenders" else
        "overseas" if args.command == "overseas" else
        {"funding_signal": "funding", "procurement": "tenders",
         "overseas_partner": "overseas"}.get(args.type) if args.command == "typed-import" else "jobs"
    )
    if config is not None and not workflow_enabled(config, workflow):
        source = ("platum-wordpress" if workflow == "funding" else
                  f"ats:{args.provider}:{args.token}" if args.command == "ats" else args.command)
        result = disabled_workflow_result(source, workflow)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return exit_code(result.status)

    if args.command == "funding":
        if not 1 <= args.pages <= 5 or not 1 <= args.per_page <= 20:
            ap.error("funding bounds: --pages 1..5, --per-page 1..20")
        result = collect_funding(
            args.pages, args.per_page, args.fixture, retrieved_at,
            include_venturesquare=args.include_venturesquare,
            enrich_hiring=args.enrich_hiring,
        )
    elif args.command == "jobs-import":
        result = import_jobs(args.path, args.format, retrieved_at)
    elif args.command == "ats":
        if not 1 <= args.limit <= 100:
            ap.error("ATS bound: --limit 1..100")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", args.token):
            ap.error("ATS token must be a public board slug")
        if not args.company.strip():
            ap.error("ATS --company must not be empty")
        result = collect_ats(args.provider, args.token, args.company.strip(), args.limit, args.fixture, retrieved_at)
    elif args.command == "ats-batch":
        targets = load_ats_targets(args.targets)
        result = collect_ats_batch(targets, retrieved_at, keyword=args.keyword, limit=args.limit)
    elif args.command in ("wanted", "saramin", "jobkorea", "jumpit"):
        if not 1 <= args.limit <= 100:
            ap.error(f"{args.command} bound: --limit 1..100")
        if not 1 <= args.pages <= 5:
            ap.error(f"{args.command} bound: --pages 1..5")
        if any(ord(char) < 32 for char in args.query):
            ap.error(f"{args.command} query must be 1..200 printable characters")
        query = clean_text(args.query)
        if not query or len(query) > 200:
            ap.error(f"{args.command} query must be 1..200 printable characters")
        if args.command == "wanted":
            result = collect_wanted(query, args.limit, args.fixture, retrieved_at, pages=args.pages, fetch_details=args.details)
        elif args.command == "saramin":
            result = collect_saramin(query, args.limit, args.fixture, retrieved_at, pages=args.pages)
        elif args.command == "jobkorea":
            result = collect_jobkorea(query, args.limit, args.fixture, retrieved_at, pages=args.pages)
        else:
            result = collect_jumpit(query, args.limit, args.fixture, retrieved_at, pages=args.pages, fetch_details=args.details)
    elif args.command == "jobs-multi":
        providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
        queries = [q.strip() for q in args.query.split(",") if q.strip()]
        result = collect_jobs_multi(
            providers, queries, retrieved_at,
            pages=args.pages, limit=args.limit,
            fetch_details=args.details, partial_ok=not args.strict,
        )
    elif args.command == "tenders":
        result = collect_tenders_g2b(
            args.query, retrieved_at, tender_type=args.tender_type,
            days=args.days, limit=args.limit, fixture=args.fixture, home=args.home,
        )
    elif args.command == "overseas":
        rss_list = [u.strip() for u in args.rss.split(",") if u.strip()]
        result = collect_overseas_signals(retrieved_at, rss_urls=rss_list, keyword=args.keyword, limit=args.limit)
    else:
        result = import_typed(args.path, args.format, args.type, retrieved_at)

    if config is not None:
        result = apply_config_filters(result, config, workflow)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return exit_code(result.status)


if __name__ == "__main__":
    raise SystemExit(main())
