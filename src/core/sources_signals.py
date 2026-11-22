#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401
"""Funding News (Platum/VentureSquare), G2B Public Tenders, and Overseas RSS/ATS Signal Collectors."""
import html
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import urllib.parse
import xml.etree.ElementTree as ET

from sources_common import (
    G2B_ENDPOINTS,
    SCHEMA_VERSION,
    SourceResult,
    VENTURESQUARE_WP_ENDPOINT,
    WP_ENDPOINT,
    canonical_url,
    clean_text,
    evidence,
    extract_tech_stack,
    fetch_bytes,
    fetch_json,
    load_fixture,
    normalize_date,
    source_id_from_url,
)
from sources_ats import collect_ats_batch, combine_job_search
from sources_kr_jobs import normalize_wanted

# ---------------------------------------------------------------------------
# Funding Signals (Platum + VentureSquare WordPress APIs + Hiring Enrichment)
# ---------------------------------------------------------------------------

FUND_EVENT = re.compile(
    r"펀드\s*(?:결성|조성)|투자\s*조합|모태\s*펀드|출자\s*(?:사업|공고)|재원\s*조성|fund\s*(?:formation|launch)",
    re.I,
)
FUNDING_EVENT = re.compile(
    r"투자\s*유치|투자를?\s*받|펀딩\s*(?:유치|완료)|(?:pre[- ]?|series\s*)[a-d]\s*(?:투자|라운드)|시리즈\s*[a-d]\s*(?:투자|라운드)",
    re.I,
)
ROUND = re.compile(r"(?:시리즈\s*[A-D]|프리\s*[A-B]|시드|브릿지|Pre[- ]?[A-B]|Series\s*[A-D])", re.I)
AMOUNT = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:억|조)\s*원?", re.I)
QUOTED_COMPANY = re.compile(r"[‘'\"“]([^’'\"”]{2,40})[’'\"”]")
GENERIC_COMPANY = re.compile(r"(?:스타트업|기업|플랫폼|서비스|솔루션|업체|개발사)$")
INVESTOR_SUFFIX = re.compile(
    r"(?:벤처스|파트너스|캐피탈|인베스트먼트|자산운용|프라이빗에쿼티|액셀러레이터|스파크랩|프라이머|블루포인트)$",
    re.I,
)
SECTORS = (
    ("AI", re.compile(r"\bAI\b|인공지능|에이전트|\bLLM\b|딥러닝", re.I)),
    ("health", re.compile(r"바이오|헬스|의료|제약|진단|병원", re.I)),
    ("fintech", re.compile(r"핀테크|금융|결제|보험|대출|송금|회계|재무", re.I)),
    ("commerce", re.compile(r"커머스|이커머스|리테일|브랜드|뷰티|패션|식품|F&B", re.I)),
    ("robotics", re.compile(r"로보틱스|로봇|자율주행|모빌리티|드론|스마트팩토리|제조", re.I)),
    ("logistics", re.compile(r"물류|SCM|풀필먼트|수출|무역|포워딩", re.I)),
    ("HR", re.compile(r"\bHR\b|채용|인사|교육|에듀테크|복지", re.I)),
    ("B2B/SaaS", re.compile(r"\bSaaS\b|\bB2B\b|솔루션|자동화|인프라|클라우드|보안", re.I)),
)


def funding_company_candidate(title: str) -> tuple[str | None, str]:
    cleaned = re.sub(r"^(?:\[[^\]]{1,20}\]\s*)+", "", title).strip()
    quoted = QUOTED_COMPANY.search(cleaned)
    if quoted:
        return clean_text(quoted.group(1))[:80] or None, "medium"
    prefix = re.split(r"[,·]|\s[-—]\s|…", cleaned, maxsplit=1)[0].strip(" ,·'\"‘’“”")
    prefix = re.sub(r"^(?:단독|종합|인터뷰|투자)\s*[:：-]?\s*", "", prefix)
    # Strip trailing particle if title is "OOO, 50억 투자 유치" or "OOO이 50억 투자 유치"
    prefix = re.sub(r"\s+(?:시리즈|프리|시드|브릿지|\d+억).*$", "", prefix).strip()
    if not prefix or len(prefix) > 80 or GENERIC_COMPANY.search(prefix):
        return prefix[:80] or None, "low" if prefix else "unknown"
    return prefix, "low"


def funding_sector(text: str) -> str | None:
    for name, pattern in SECTORS:
        if pattern.search(text):
            return name
    return None


def normalize_funding_posts(
    payload: Any,
    retrieved_at: str,
    source: str = "platum-wordpress",
    limit: int = 20,
) -> SourceResult:
    if not isinstance(payload, list):
        return SourceResult("invalid_response", source, errors=["WordPress response must be a JSON list"])
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    excluded = 0
    seen: set[str] = set()
    for index, post in enumerate(payload[:limit]):
        if not isinstance(post, dict):
            errors.append(f"row {index}: expected object")
            continue
        title = clean_text((post.get("title") or {}).get("rendered") if isinstance(post.get("title"), dict) else post.get("title"))
        excerpt = clean_text((post.get("excerpt") or {}).get("rendered") if isinstance(post.get("excerpt"), dict) else post.get("excerpt"))
        blob = f"{title} {excerpt}".strip()
        if not title:
            continue
        if FUND_EVENT.search(blob):
            excluded += 1
            continue
        if not FUNDING_EVENT.search(blob):
            continue
        url = canonical_url(post.get("link"))
        if not url:
            errors.append(f"row {index}: missing valid public URL")
            continue
        candidate, confidence = funding_company_candidate(title)
        if candidate and INVESTOR_SUFFIX.search(candidate):
            confidence = "low"
        native = post.get("id")
        sid = f"wp:{native}" if native is not None and str(native).strip() else source_id_from_url(source, url)
        dedupe_key = f"{source}:{sid}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        amounts = list(dict.fromkeys(x.replace(" ", "") for x in AMOUNT.findall(blob)))
        rounds = list(dict.fromkeys(clean_text(x) for x in ROUND.findall(blob)))
        record = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "funding_signal",
            "source": source,
            "source_id": sid,
            "company": candidate if confidence == "medium" else None,
            "company_candidate": candidate,
            "company_confidence": confidence,
            "title": title,
            "description": excerpt[:1200] or None,
            "url": url,
            "published_at": normalize_date(post.get("date")),
            "stack": extract_tech_stack(blob),
            "round_candidate": rounds[0] if len(rounds) == 1 else None,
            "amount_candidate": amounts[0] if len(amounts) == 1 else None,
            "amount_candidates": amounts,
            "sector_candidate": funding_sector(blob),
            "review_required": confidence != "medium" or len(amounts) != 1,
            "evidence": evidence(source, sid, url, retrieved_at, post),
        }
        records.append(record)
    status = "ok" if records else ("invalid_response" if errors else "empty")
    return SourceResult(status, source, records, errors, {"excluded_fund_events": excluded})


def collect_funding(
    pages: int,
    per_page: int,
    fixture: str | None,
    retrieved_at: str,
    *,
    include_venturesquare: bool = False,
    enrich_hiring: bool = False,
    enrich_limit: int = 8,
    opener=None,
) -> SourceResult:
    source = "platum-wordpress"
    if fixture:
        status, payload, error = load_fixture(fixture)
        if status != "ok":
            return SourceResult(status, source, errors=[error or "fixture failed"])
        return normalize_funding_posts(payload, retrieved_at, source, per_page * pages)
    all_posts: list[Any] = []
    for page in range(1, pages + 1):
        query = urllib.parse.urlencode({
            "categories": 7521,
            "per_page": per_page,
            "page": page,
            "_fields": "id,title,link,date,excerpt",
        })
        status, payload, error = fetch_json(f"{WP_ENDPOINT}?{query}", source, opener=opener)
        if status != "ok":
            return SourceResult(status, source, errors=[error or "funding source failed"], metadata={"page": page})
        if not isinstance(payload, list):
            return SourceResult("invalid_response", source, errors=[f"page {page}: expected a JSON list"])
        if not payload:
            break
        all_posts.extend(payload)
        if page < pages:
            time.sleep(0.4)
    result = normalize_funding_posts(all_posts, retrieved_at, source, pages * per_page)

    if include_venturesquare:
        vs_query = urllib.parse.urlencode({
            "search": "투자 유치",
            "per_page": min(per_page, 15),
            "page": 1,
            "_fields": "id,title,link,date,excerpt",
        })
        vs_status, vs_payload, vs_err = fetch_json(
            f"{VENTURESQUARE_WP_ENDPOINT}?{vs_query}", "venturesquare-wordpress", opener=opener
        )
        if vs_status == "ok" and isinstance(vs_payload, list):
            vs_res = normalize_funding_posts(vs_payload, retrieved_at, "venturesquare-wordpress", per_page)
            if vs_res.records:
                result = combine_job_search([result, vs_res], partial_ok=True, label="funding-multi")
        elif vs_err:
            result.errors.append(vs_err)

    if enrich_hiring and result.status == "ok" and result.records:
        result = enrich_funding_with_hiring(result, retrieved_at, limit=enrich_limit, opener=opener)
    return result


def enrich_funding_with_hiring(
    result: SourceResult,
    retrieved_at: str,
    *,
    limit: int = 8,
    delay: float = 0.5,
    opener=None,
) -> SourceResult:
    """Best-effort hiring enrichment for funding candidates using Wanted public search."""
    if result.status != "ok":
        return result
    enriched_count = 0
    for rec in result.records[:limit]:
        name = rec.get("company") or rec.get("company_candidate")
        if not name:
            continue
        wanted = collect_wanted(name, 10, None, retrieved_at, pages=1, fetch_details=False, opener=opener)
        if wanted.status == "ok":
            key = _norm_company_key(name)
            matched_roles = [
                r["title"] for r in wanted.records
                if key and r.get("company") and key in _norm_company_key(r["company"])
            ]
            if matched_roles:
                rec["hiring_roles"] = matched_roles[:10]
                rec["open_roles"] = len(matched_roles)
                enriched_count += 1
        if delay > 0:
            time.sleep(delay)
    metadata = dict(result.metadata)
    metadata["hiring_enriched_count"] = enriched_count
    return SourceResult(result.status, result.source, result.records, result.errors, metadata)



# ---------------------------------------------------------------------------
# Live Public Procurement (G2B 나라장터 OpenAPI, user-supplied DATA_GO_KR_API_KEY)
# ---------------------------------------------------------------------------

def _read_env_key(key_name: str, home: str | Path | None = None) -> str:
    val = os.environ.get(key_name, "").strip()
    if val:
        return val
    candidates: list[Path] = []
    if home:
        candidates.append(Path(home).expanduser().absolute() / ".env")
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        candidates.append(Path(env_home).expanduser().absolute() / ".env")
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or "=" not in stripped:
                        continue
                    k, v = stripped.split("=", 1)
                    if k.strip() == key_name:
                        return v.strip().strip("'\"")
            except OSError:
                continue
    return ""


def normalize_g2b_items(
    payload: Any,
    retrieved_at: str,
    *,
    kind: str = "bid_notice",
    limit: int = 50,
) -> SourceResult:
    source = f"g2b-{kind}"
    if not isinstance(payload, dict):
        return SourceResult("invalid_response", source, errors=["G2B response must be a JSON object"])
    body = (payload.get("response") or {}).get("body") if isinstance(payload.get("response"), dict) else payload
    if not isinstance(body, dict):
        return SourceResult("invalid_response", source, errors=["G2B response missing response.body"])
    items = body.get("items")
    if isinstance(items, dict) and "item" in items:
        items = items["item"]
    if items is None or items == "":
        return SourceResult("empty", source, metadata={"kind": kind})
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return SourceResult("invalid_response", source, errors=["G2B body.items must be a list"])

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items[:limit]:
        if not isinstance(raw, dict):
            continue
        title = clean_text(raw.get("bidNtceNm") or raw.get("bizNm") or raw.get("prdctClsfcNoNm") or "")
        agency = clean_text(raw.get("dminsttNm") or raw.get("ntceInsttNm") or raw.get("orderInsttNm") or "") or None
        notice_no = clean_text(str(raw.get("bidNtceNo") or raw.get("orderPlanUntyNo") or ""))
        notice_ord = clean_text(str(raw.get("bidNtceOrd") or "00"))
        if not title:
            continue
        raw_url = raw.get("bidNtceDtlUrl") or raw.get("bidNtceUrl") or ""
        url = canonical_url(raw_url)
        if not url:
            if notice_no:
                url = f"https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={urllib.parse.quote(notice_no)}&bidPbancOrd={urllib.parse.quote(notice_ord)}"
            else:
                url = "https://www.g2b.go.kr/"
        sid = f"g2b:{kind}:{notice_no}-{notice_ord}" if notice_no else source_id_from_url(source, url)
        if sid in seen:
            continue
        seen.add(sid)
        budget = clean_text(str(raw.get("presmptPrce") or raw.get("asignBdgtAmt") or raw.get("sumOrderAmt") or ""))
        deadline = clean_text(str(raw.get("bidClseDt") or raw.get("orderMnth") or ""))
        desc_parts = [f"구분: {'입찰공고' if kind == 'bid_notice' else '발주계획(사전계획, 본공고 아님)'}"]
        if budget and budget != "0":
            desc_parts.append(f"예산/추정가: {budget}원")
        if deadline:
            desc_parts.append(f"마감/시기: {deadline}")
        description = " · ".join(desc_parts)
        records.append({
            "schema_version": SCHEMA_VERSION,
            "record_type": "procurement",
            "procurement_kind": kind,
            "source": source,
            "source_id": sid,
            "company": agency,
            "company_candidate": agency,
            "company_confidence": "official_notice" if agency else "unknown",
            "title": title,
            "description": description,
            "url": url,
            "published_at": normalize_date(raw.get("bidNtceDt") or raw.get("rgstDt") or raw.get("nticeDt")),
            "stack": extract_tech_stack(title),
            "location": clean_text(raw.get("prtcptLmtRgnNm") or "") or "대한민국",
            "review_required": True,
            "evidence": evidence(source, sid, url, retrieved_at, raw),
        })
    return SourceResult("ok" if records else "empty", source, records, metadata={"kind": kind})


def collect_tenders_g2b(
    query: str,
    retrieved_at: str,
    *,
    tender_type: str = "servc",
    days: int = 14,
    limit: int = 30,
    fixture: str | None = None,
    home: str | Path | None = None,
    opener=None,
) -> SourceResult:
    source = "g2b-bid_notice"
    if fixture:
        status, payload, err = load_fixture(fixture)
        if status != "ok":
            return SourceResult(status, source, errors=[err or "G2B fixture failed"])
        return normalize_g2b_items(payload, retrieved_at, kind="bid_notice", limit=limit)

    api_key = _read_env_key("DATA_GO_KR_API_KEY", home)
    if not api_key:
        return SourceResult("failed", source, errors=[
            "나라장터(G2B) 실시간 조회에는 공공데이터포털 API 키(DATA_GO_KR_API_KEY)가 $HERMES_HOME/.env에 필요합니다. "
            "키가 없다면 나라장터 CSV/JSON export를 --source-mode file로 사용하세요."
        ])

    end_dt = datetime.now(timezone.utc) + timedelta(hours=9)
    start_dt = end_dt - timedelta(days=max(1, min(days, 30)))
    types = list(G2B_ENDPOINTS) if tender_type == "all" else [tender_type if tender_type in G2B_ENDPOINTS else "servc"]
    results: list[SourceResult] = []
    for ttype in types:
        params = {
            "serviceKey": api_key,
            "type": "json",
            "inqryDiv": "1",
            "inqryBgnDt": start_dt.strftime("%Y%m%d0000"),
            "inqryEndDt": end_dt.strftime("%Y%m%d2359"),
            "numOfRows": str(min(limit, 50)),
            "pageNo": "1",
        }
        if query.strip():
            params["bidNtceNm"] = query.strip()
        encoded = urllib.parse.urlencode(params)
        status, payload, err = fetch_json(f"{G2B_ENDPOINTS[ttype]}?{encoded}", f"g2b-{ttype}", opener=opener)
        if status != "ok":
            # Never expose serviceKey in error messages
            safe_err = re.sub(r"serviceKey=[^&\s]+", "serviceKey=<redacted>", err or "G2B API failed")
            results.append(SourceResult(status, f"g2b-{ttype}", errors=[safe_err]))
            continue
        results.append(normalize_g2b_items(payload, retrieved_at, kind="bid_notice", limit=limit))
    return combine_job_search(results, partial_ok=True, label="g2b-public-tenders")


# ---------------------------------------------------------------------------
# Live Overseas Partner / Expansion Signals (RSS/Atom + Global ATS Expansion)
# ---------------------------------------------------------------------------

def normalize_rss_xml(
    raw: bytes | str,
    feed_url: str,
    retrieved_at: str,
    *,
    record_type: str = "overseas_partner",
    limit: int = 30,
) -> SourceResult:
    source = f"rss:{urllib.parse.urlsplit(feed_url).netloc or 'feed'}"
    try:
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        return SourceResult("invalid_response", source, errors=["RSS feed was not UTF-8"])
    if re.search(r"<!(?:DOCTYPE|ENTITY)\b", text, re.I):
        return SourceResult("invalid_response", source, errors=["RSS XML with DOCTYPE/ENTITY declarations is rejected for safety"])
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return SourceResult("invalid_response", source, errors=[f"RSS XML parse failed: {exc}"])

    items = root.findall(".//item")
    is_atom = False
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry") or root.findall(".//entry")
        is_atom = True

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items[:limit]:
        if is_atom:
            ns = "{http://www.w3.org/2005/Atom}"
            title = clean_text((item.findtext(f"{ns}title") or item.findtext("title") or ""))
            link_el = item.find(f"{ns}link") or item.find("link")
            raw_link = (link_el.attrib.get("href") or link_el.text or "") if link_el is not None else ""
            summary = clean_text(item.findtext(f"{ns}summary") or item.findtext(f"{ns}content") or item.findtext("summary") or "")
            pub = item.findtext(f"{ns}updated") or item.findtext(f"{ns}published") or item.findtext("updated")
        else:
            title = clean_text(item.findtext("title") or "")
            raw_link = item.findtext("link") or ""
            summary = clean_text(item.findtext("description") or "")
            pub = item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")
        url = canonical_url(raw_link)
        if not title or not url:
            continue
        sid = source_id_from_url(source, url)
        if sid in seen:
            continue
        seen.add(sid)
        candidate, conf = funding_company_candidate(title)
        records.append({
            "schema_version": SCHEMA_VERSION,
            "record_type": record_type,
            "source": source,
            "source_id": sid,
            "company": candidate if conf == "medium" else None,
            "company_candidate": candidate,
            "company_confidence": conf,
            "title": title,
            "description": summary[:1200] or None,
            "url": url,
            "published_at": normalize_date(pub),
            "stack": extract_tech_stack(f"{title} {summary}"),
            "location": None,
            "review_required": True,
            "evidence": evidence(source, sid, url, retrieved_at, {"title": title, "url": url, "pub": pub}),
        })
    return SourceResult("ok" if records else "empty", source, records, metadata={"feed_url": feed_url})


def collect_overseas_signals(
    retrieved_at: str,
    *,
    rss_urls: list[str] | None = None,
    ats_targets: list[dict[str, str]] | None = None,
    keyword: str = "Korea, APAC, Partner, Distribution, Sales",
    limit: int = 30,
    opener=None,
) -> SourceResult:
    """Collect live overseas partner/expansion signals from public RSS feeds and/or global ATS boards."""
    results: list[SourceResult] = []
    clean_urls = [u for u in (rss_urls or []) if canonical_url(u)]
    for url in clean_urls[:5]:
        status, raw, err = fetch_bytes(url, f"rss:{urllib.parse.urlsplit(url).netloc}", opener=opener)
        if status != "ok" or raw is None:
            results.append(SourceResult(status, f"rss:{url}", errors=[err or "RSS fetch failed"]))
        else:
            results.append(normalize_rss_xml(raw, url, retrieved_at, record_type="overseas_partner", limit=limit))

    targets = ats_targets if ats_targets is not None else load_ats_targets()
    if targets:
        ats_res = collect_ats_batch(targets, retrieved_at, keyword=keyword, limit=limit, partial_ok=True, opener=opener)
        # Re-tag matching global expansion postings as overseas_partner signals
        for rec in ats_res.records:
            rec["record_type"] = "overseas_partner"
        results.append(ats_res)

    if not results:
        return SourceResult("failed", "overseas-live", errors=[
            "overseas_partner 실시간 조회에는 공개 RSS URL(overseas_rss_urls) 또는 ATS 타깃 목록이 필요합니다."
        ])
    return combine_job_search(results, partial_ok=True, label="overseas-partner-live")


