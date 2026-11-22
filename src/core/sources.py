#!/usr/bin/env python3
"""Bounded, read-only source adapters for Hermes Outbound Kit.

The adapters never log in, submit forms, write to a CRM, or bypass an
access-control response (401/403/429/CAPTCHA). They ignore ambient proxies by
default; a caller may inject only an explicitly reviewed source-scoped
transport. Every command prints one JSON envelope so an upstream workflow can
distinguish a valid empty result from a blocked or broken source.
"""
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "outbound-source/v1"
STATUSES = {"ok", "empty", "blocked", "failed", "invalid_response"}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "Hermes-Outbound-Kit/0.2"
)
WP_ENDPOINT = "https://platum.kr/wp-json/wp/v2/posts"
VENTURESQUARE_WP_ENDPOINT = "https://www.venturesquare.net/wp-json/wp/v2/posts"
WANTED_ENDPOINT = "https://www.wanted.co.kr/api/chaos/search/v1/results"
WANTED_DETAIL_ENDPOINT = "https://www.wanted.co.kr/api/v4/jobs/{job_id}"
SARAMIN_ENDPOINT = "https://www.saramin.co.kr/zf_user/search/recruit"
JOBKOREA_ENDPOINT = "https://www.jobkorea.co.kr/Search/"
JUMPIT_ENDPOINT = "https://api.jumpit.co.kr/api/positions"
JUMPIT_DETAIL_ENDPOINT = "https://api.jumpit.co.kr/api/position/{job_id}"
G2B_BID_ENDPOINT = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"
G2B_ENDPOINTS = {
    "servc": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc",
    "thng": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThng",
    "cnstwk": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk",
    "frgcpt": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoFrgcpt",
}
G2B_ORDER_PLAN_ENDPOINT = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc"

# Public-source contract references (MIT, Wendy Nam, 2026), inspected at
# hermes-agent-kit commit 76e15170a2dc8b2bce270bd50e07287a14c3dd6b:
# bundle/job-search/skills/job-search/wanted-search/scripts/wanted_search.py
# bundle/job-search/skills/job-search/kr-search/scripts/kr_job_search.py

def _compile_stack_pattern(pattern: str) -> re.Pattern[str]:
    # Python \b treats Hangul as \w, so "Python과" or "MES와" misses \b; use ASCII boundaries instead.
    out = re.sub(r"\\b(?=[A-Za-z0-9(])", r"(?<![A-Za-z0-9_])", pattern)
    out = re.sub(r"\\b", r"(?![A-Za-z0-9_])", out)
    return re.compile(out, re.I)


TECH_STACK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, _compile_stack_pattern(pattern))
    for label, pattern in (
        ("Salesforce", r"\bsalesforce\b|세일즈포스"),
        ("HubSpot", r"\bhubspot\b|허브스팟"),
        ("Snowflake", r"\bsnowflake\b"),
        ("Databricks", r"\bdatabricks\b"),
        ("BigQuery", r"\bbigquery\b"),
        ("dbt", r"\bdbt\b"),
        ("Airflow", r"\bairflow\b"),
        ("Kafka", r"\bkafka\b"),
        ("Spark", r"\b(?:apache\s+)?spark\b|\bpyspark\b"),
        ("Tableau", r"\btableau\b|태블로"),
        ("PowerBI", r"\bpower\s*bi\b"),
        ("Looker", r"\blooker\b"),
        ("AWS", r"\baws\b|amazon\s+web\s+services"),
        ("GCP", r"\bgcp\b|google\s+cloud"),
        ("Azure", r"\bazure\b"),
        ("Naver Cloud", r"naver\s*cloud|네이버\s*클라우드|\bncp\b"),
        ("Kubernetes", r"\bkubernetes\b|\bk8s\b"),
        ("Docker", r"\bdocker\b"),
        ("Terraform", r"\bterraform\b"),
        ("Datadog", r"\bdatadog\b"),
        ("Cloudflare", r"\bcloudflare\b"),
        ("Okta", r"\bokta\b"),
        ("ISMS-P", r"\bisms(?:-p)?\b"),
        ("CSAP", r"\bcsap\b"),
        ("Python", r"\bpython\b"),
        ("PyTorch", r"\bpytorch\b"),
        ("TensorFlow", r"\btensorflow\b"),
        ("LLM", r"\bllm\b|\brag\b|생성형\s*ai|langchain|langgraph"),
        ("OpenCV", r"\bopencv\b|비전\s*검사|machine\s*vision|halcon|cognex"),
        ("Java", r"\bjava\b(?!script)"),
        ("Spring", r"\bspring(?:\s*boot)?\b"),
        ("TypeScript", r"\btypescript\b"),
        ("React", r"\breact(?:\.js|js)?\b"),
        ("Next.js", r"\bnext\.?js\b"),
        ("Node.js", r"\bnode\.?js\b"),
        ("Go", r"\bgolang\b"),
        ("C++", r"(?<!\w)c\+\+(?!\w)"),
        ("SQL", r"\b(?:postgre)?sql\b|\bmysql\b|\boracle\b"),
        ("SAP", r"\bsap\b"),
        ("ERP", r"\berp\b|더존|위하고|이카운트|영림원|netsuite"),
        ("MES", r"\bmes\b"),
        ("PLC", r"\bplc\b"),
        ("SCADA", r"\bscada\b"),
        ("ROS", r"\bros2?\b"),
        ("WMS", r"\bwms\b"),
        ("TMS", r"\btms\b"),
        ("SCM", r"\bscm\b"),
        ("GA4", r"\bga4\b|google\s*analytics"),
        ("Braze", r"\bbraze\b"),
        ("Amplitude", r"\bamplitude\b"),
        ("Airbridge", r"\bairbridge\b"),
        ("AppsFlyer", r"\bappsflyer\b"),
        ("Shopify", r"\bshopify\b"),
        ("Cafe24", r"\bcafe24\b|카페24"),
        ("Meta Ads", r"\bmeta\s*ads\b|메타\s*광고|페이스북\s*광고"),
        ("Google Ads", r"\bgoogle\s*ads\b|구글\s*애즈"),
        ("Greeting", r"\bgreeting\b|그리팅"),
        ("Ninehire", r"\bninehire\b|나인하이어"),
        ("Flex", r"플렉스\s*hr|\bflex\s*hr\b"),
        ("Greenhouse", r"\bgreenhouse\b"),
        ("Workday", r"\bworkday\b"),
        ("Slack", r"\bslack\b"),
        ("Notion", r"\bnotion\b"),
        ("Jira", r"\bjira\b"),
        ("Zendesk", r"\bzendesk\b"),
        ("ChannelTalk", r"채널톡|\bchannel\s*talk\b"),
    )
)


@dataclass
class SourceResult:
    status: str
    source: str
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown source status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value)
    return hashlib.sha256(raw).hexdigest()


def clean_text(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def extract_tech_stack(text: str | None, existing: list[str] | None = None) -> list[str] | None:
    """Extract recognized B2B tools and tech-stack keywords from job titles/JDs."""
    found: list[str] = []
    seen: set[str] = set()
    for item in (existing or []):
        cleaned = clean_text(item)
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            found.append(cleaned)
    blob = clean_text(text) if text else ""
    if blob:
        for label, pattern in TECH_STACK_PATTERNS:
            if label.casefold() not in seen and pattern.search(blob):
                seen.add(label.casefold())
                found.append(label)
    return found or None


def normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    # Handle Korean/G2B date formats like "2026/10/13", "2026.10.13", "20261013", "2026-10-13 09:00:00"
    m_compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:\d{4,6})?", text)
    if m_compact:
        return f"{m_compact.group(1)}-{m_compact.group(2)}-{m_compact.group(3)}"
    m_sep = re.match(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
    if m_sep and "T" not in text and "Z" not in text:
        y, mo, d = int(m_sep.group(1)), int(m_sep.group(2)), int(m_sep.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    # RFC-2822 RSS dates
    try:
        from email.utils import parsedate_to_datetime
        if "," in text and any(mon in text for mon in ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")):
            dt = parsedate_to_datetime(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.isoformat()
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def canonical_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not (k.lower().startswith("utm_") or k.lower() in {"fbclid", "gclid"})]
    query.sort()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urllib.parse.urlencode(query), ""))


def source_id_from_url(source: str, url: str, supplied: Any = None) -> str:
    if supplied is not None and str(supplied).strip():
        return re.sub(r"\s+", " ", str(supplied)).strip()[:200]
    patterns = (
        ("wanted", r"wanted\.co\.kr/wd/(\d+)"),
        ("saramin", r"[?&]rec_idx=(\d+)"),
        ("jobkorea", r"/GI_Read/(\d+)"),
        ("jumpit", r"jumpit\.co\.kr/position/(\d+)"),
        ("greeting", r"greetinghr\.com/(?:ko/)?o/(\d+)"),
        ("linkedin", r"/jobs/view/(?:[^/?]*?-)?(\d+)(?:[/?]|$)"),
    )
    lower = source.lower()
    for label, pattern in patterns:
        match = re.search(pattern, url, re.I)
        if match and (label in lower or label in url.lower()):
            return f"{label}:{match.group(1)}"
    return "url:" + sha256(url.encode("utf-8"))[:24]


def evidence(source: str, source_id: str, url: str, retrieved_at: str, raw: Any) -> dict[str, str]:
    return {
        "source": source,
        "url": url,
        "source_id": source_id,
        "retrieved_at": retrieved_at,
        "raw_sha256": sha256(raw),
    }


def _read_limited(response: Any) -> bytes:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
    encoding = ""
    if hasattr(response, "headers") and response.headers:
        encoding = str(response.headers.get("Content-Encoding") or "").lower().strip()
    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        try:
            decompressed = gzip.decompress(raw)
            if len(decompressed) > MAX_RESPONSE_BYTES:
                raise ValueError(f"decompressed response exceeded {MAX_RESPONSE_BYTES} bytes")
            return decompressed
        except OSError:
            return raw
    if encoding == "deflate":
        try:
            decompressed = zlib.decompress(raw)
            if len(decompressed) > MAX_RESPONSE_BYTES:
                raise ValueError(f"decompressed response exceeded {MAX_RESPONSE_BYTES} bytes")
            return decompressed
        except zlib.error:
            return raw
    return raw


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _default_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _fetch_raw(
    url: str,
    source: str,
    accept: str,
    timeout: int = 20,
    *,
    opener=None,
    extra_headers: dict[str, str] | None = None,
    retries: int = 1,
    backoff: float = 0.6,
) -> tuple[str, bytes | None, str | None]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, headers=headers)
    transport = opener or _default_opener()
    attempts = max(1, retries + 1)
    for attempt in range(attempts):
        try:
            with transport.open(request, timeout=timeout) as response:
                return "ok", _read_limited(response), None
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401, 403, 429):
                return "blocked", None, f"{source}: HTTP {code}; access denied or rate limited. Do not retry with a proxy."
            if code in (500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(backoff * (attempt + 1))
                continue
            return "failed", None, f"{source}: HTTP {code}; source request failed."
        except urllib.error.URLError as exc:
            if attempt + 1 < attempts:
                time.sleep(backoff * (attempt + 1))
                continue
            return "failed", None, f"{source}: network failure: {exc.reason}"
        except (TimeoutError, OSError) as exc:
            if attempt + 1 < attempts:
                time.sleep(backoff * (attempt + 1))
                continue
            return "failed", None, f"{source}: network failure: {type(exc).__name__}"
        except ValueError as exc:
            return "invalid_response", None, f"{source}: {exc}"
    return "failed", None, f"{source}: source request failed."


def fetch_json(
    url: str,
    source: str,
    timeout: int = 20,
    *,
    opener=None,
    extra_headers: dict[str, str] | None = None,
    retries: int = 1,
) -> tuple[str, Any, str | None]:
    status, raw, error = _fetch_raw(
        url, source, "application/json", timeout,
        opener=opener, extra_headers=extra_headers, retries=retries,
    )
    if status != "ok" or raw is None:
        return status, None, error
    try:
        return "ok", json.loads(raw.decode("utf-8-sig")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_response", None, f"{source}: response was not valid JSON"


def fetch_bytes(
    url: str,
    source: str,
    timeout: int = 20,
    *,
    opener=None,
    extra_headers: dict[str, str] | None = None,
    retries: int = 1,
) -> tuple[str, bytes | None, str | None]:
    """Fetch one bounded public document without redirects or access bypass."""
    return _fetch_raw(
        url, source, "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", timeout,
        opener=opener, extra_headers=extra_headers, retries=retries,
    )


def load_fixture(path: str) -> tuple[str, Any, str | None]:
    try:
        raw = Path(path).read_bytes()
        if len(raw) > MAX_RESPONSE_BYTES:
            return "invalid_response", None, f"fixture exceeded {MAX_RESPONSE_BYTES} bytes"
        return "ok", json.loads(raw.decode("utf-8-sig")), None
    except OSError as exc:
        return "failed", None, f"fixture read failed: {exc}"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_response", None, "fixture was not valid JSON"


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
# Generic Job CSV/JSON Import
# ---------------------------------------------------------------------------

ALIASES = {
    "company": ("company", "company_name", "회사", "회사명"),
    "title": ("title", "position", "job_title", "포지션", "공고명", "직무"),
    "url": ("url", "link", "링크", "공고url", "공고_url"),
    "published_at": ("published_at", "date", "posted_at", "게시일", "등록일", "발견"),
    "stack": ("stack", "skills", "tech_stack", "기술스택", "스택"),
    "source": ("source", "board", "보드"),
    "source_id": ("source_id", "posting_id", "id", "공고id"),
    "location": ("location", "근무지", "지역"),
    "description": ("description", "summary", "jd", "내용", "주요업무"),
    "experience": ("experience", "career", "경력"),
}


def _lookup(row: dict[str, Any], field_name: str) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in ALIASES[field_name]:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def normalize_stack(value: Any) -> list[str] | None:
    if value is None or value == "":
        return None
    if isinstance(value, list):
        items = [clean_text(v) for v in value]
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                items = [clean_text(v) for v in parsed] if isinstance(parsed, list) else [text]
            except json.JSONDecodeError:
                items = re.split(r"[,;|]", text)
        else:
            items = re.split(r"[,;|]", text)
    else:
        return None
    cleaned = [item.strip() for item in items if item and item.strip()]
    return list(dict.fromkeys(cleaned)) or None


def read_job_rows(path: str, format_name: str = "auto") -> tuple[str, list[Any] | None, str | None]:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return "failed", None, f"job file read failed: {exc}"
    if len(raw) > MAX_RESPONSE_BYTES:
        return "invalid_response", None, f"job file exceeded {MAX_RESPONSE_BYTES} bytes"
    fmt = format_name
    if fmt == "auto":
        fmt = "csv" if Path(path).suffix.lower() == ".csv" else "json"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "invalid_response", None, "job file must be UTF-8 or UTF-8 with BOM"
    if fmt == "csv":
        try:
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                return "invalid_response", None, "CSV has no header row"
            return "ok", list(reader), None
        except csv.Error as exc:
            return "invalid_response", None, f"CSV parse failed: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return "invalid_response", None, f"JSON parse failed at line {exc.lineno}"
    if isinstance(data, dict):
        data = data.get("records", data.get("items", data.get("postings")))
    if not isinstance(data, list):
        return "invalid_response", None, "job JSON must be a list or contain records/items/postings"
    return "ok", data, None


def normalize_job_rows(rows: Iterable[Any], retrieved_at: str, source_default: str = "user-file") -> SourceResult:
    rows = list(rows)
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    source_names: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: expected object")
            continue
        title = clean_text(_lookup(raw, "title"))
        url = canonical_url(_lookup(raw, "url"))
        if not title or not url:
            errors.append(f"row {index}: title and public http(s) URL are required")
            continue
        company = clean_text(_lookup(raw, "company")) or None
        source = clean_text(_lookup(raw, "source")) or source_default
        sid = source_id_from_url(source, url, _lookup(raw, "source_id"))
        key = f"{source.lower()}:{sid}"
        if key in seen:
            continue
        seen.add(key)
        source_names.add(source)
        description = clean_text(_lookup(raw, "description")) or None
        raw_stack = normalize_stack(_lookup(raw, "stack"))
        stack = extract_tech_stack(f"{title} {description or ''}", raw_stack)
        record = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "job_posting",
            "source": source,
            "source_id": sid,
            "company": company,
            "company_candidate": company,
            "company_confidence": "provided" if company else "unknown",
            "title": title,
            "description": description,
            "url": url,
            "published_at": normalize_date(_lookup(raw, "published_at")),
            "stack": stack,
            "location": clean_text(_lookup(raw, "location")) or None,
            "experience": clean_text(_lookup(raw, "experience")) or None,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, raw),
        }
        records.append(record)
    status = "ok" if records else ("invalid_response" if errors else "empty")
    label = source_default if not source_names else (next(iter(source_names)) if len(source_names) == 1 else "mixed-job-import")
    return SourceResult(status, label, records, errors, {
        "duplicates_removed": max(0, len(rows) - len(records) - len(errors))
    })


def import_jobs(path: str, format_name: str, retrieved_at: str) -> SourceResult:
    status, rows, error = read_job_rows(path, format_name)
    if status != "ok":
        return SourceResult(status, "job-import", errors=[error or "job import failed"])
    return normalize_job_rows(rows or [], retrieved_at)


# ---------------------------------------------------------------------------
# Wanted (Pagination + Detail JD/Skill Extraction)
# ---------------------------------------------------------------------------

def normalize_wanted(payload: Any, query: str, retrieved_at: str, limit: int = 20) -> SourceResult:
    """Normalize the public Wanted search response without job-seeker filters."""
    source = "wanted-public-search"
    if not isinstance(payload, dict) or "positions" not in payload:
        return SourceResult("invalid_response", source, errors=[
            "Wanted response must be an object with a positions field"
        ], metadata={"query": query})
    positions = payload["positions"]
    if isinstance(positions, dict):
        if isinstance(positions.get("data"), list):
            positions = positions["data"]
        elif isinstance(positions.get("list"), list):
            positions = positions["list"]
        else:
            return SourceResult("invalid_response", source, errors=[
                "Wanted positions wrapper must contain a data or list array"
            ], metadata={"query": query})
    if not isinstance(positions, list):
        return SourceResult("invalid_response", source, errors=[
            "Wanted positions must be an array"
        ], metadata={"query": query})
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(positions[:limit]):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: expected object")
            continue
        native_id = raw.get("id")
        title = clean_text(raw.get("position") or raw.get("title") or raw.get("name"))
        if native_id is None or not str(native_id).strip() or not title:
            errors.append(f"row {index}: id and title are required")
            continue
        native_id = str(native_id).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", native_id):
            errors.append(f"row {index}: invalid id")
            continue
        sid = f"wanted:{native_id}"
        if sid in seen:
            continue
        seen.add(sid)
        company_value = raw.get("company")
        company = clean_text(company_value.get("name") if isinstance(company_value, dict)
                             else raw.get("company_name") or company_value) or None
        industry = clean_text(company_value.get("industry_name")) if isinstance(company_value, dict) else ""
        address = raw.get("address")
        location = clean_text(
            (address.get("full_location") or address.get("location")) if isinstance(address, dict)
            else raw.get("location")
        ) or None
        annual_from = raw.get("annual_from")
        annual_to = raw.get("annual_to")
        experience = None
        if isinstance(annual_from, int) or isinstance(annual_to, int):
            if annual_from == 0 and (not annual_to or annual_to >= 99):
                experience = "경력 무관"
            elif annual_to and annual_to < 99:
                experience = f"경력 {annual_from or 0}~{annual_to}년"
            elif annual_from:
                experience = f"경력 {annual_from}년 이상"
        skill_tags = raw.get("skill_tags")
        raw_stack = [
            (t.get("title") if isinstance(t, dict) else str(t))
            for t in (skill_tags if isinstance(skill_tags, list) else [])
        ]
        url = f"https://www.wanted.co.kr/wd/{urllib.parse.quote(native_id, safe='')}"
        published = normalize_date(raw.get("confirm_time") or raw.get("created_at") or raw.get("due_time"))
        records.append({
            "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
            "source": source, "source_id": sid,
            "company": company, "company_candidate": company,
            "company_confidence": "public_listing" if company else "unknown",
            "title": title, "description": None,
            "url": url, "published_at": published,
            "stack": extract_tech_stack(title, raw_stack),
            "location": location,
            "experience": experience,
            "sector_candidate": industry or None,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, raw),
        })
    status = "ok" if records else ("invalid_response" if errors else "empty")
    return SourceResult(status, source, records, errors, {
        "query": query, "returned_positions": len(positions), "bounded_limit": limit,
    })


def enrich_wanted_detail(record: dict[str, Any], *, opener=None) -> dict[str, Any]:
    """Fetch public Wanted v4 job detail JSON to populate JD, skill tags, industry, and dates."""
    sid = str(record.get("source_id") or "")
    if not sid.startswith("wanted:"):
        return record
    job_id = sid.split(":", 1)[1]
    if not re.fullmatch(r"\d{1,12}", job_id):
        return record
    status, payload, _err = fetch_json(
        WANTED_DETAIL_ENDPOINT.format(job_id=job_id),
        "wanted-detail",
        timeout=12,
        opener=opener,
        extra_headers={"Referer": f"https://www.wanted.co.kr/wd/{job_id}"},
        retries=0,
    )
    if status != "ok" or not isinstance(payload, dict):
        return record
    job = payload.get("job") if isinstance(payload.get("job"), dict) else payload
    detail = job.get("detail") if isinstance(job.get("detail"), dict) else {}
    parts = []
    for label, key in (("주요업무", "main_tasks"), ("자격요건", "requirements"), ("우대사항", "preferred_points")):
        text = clean_text(detail.get(key))
        if text:
            parts.append(f"[{label}] {text[:500]}")
    if parts:
        record["description"] = " / ".join(parts)[:1800]
    tags = job.get("skill_tags")
    tag_names = [(t.get("title") if isinstance(t, dict) else str(t)) for t in (tags if isinstance(tags, list) else [])]
    record["stack"] = extract_tech_stack(
        f"{record.get('title') or ''} {record.get('description') or ''}",
        (record.get("stack") or []) + tag_names,
    )
    company_obj = job.get("company") if isinstance(job.get("company"), dict) else {}
    if not record.get("sector_candidate") and company_obj.get("industry_name"):
        record["sector_candidate"] = clean_text(company_obj["industry_name"]) or None
    address = job.get("address") if isinstance(job.get("address"), dict) else {}
    if not record.get("location") and (address.get("full_location") or address.get("location")):
        record["location"] = clean_text(address.get("full_location") or address.get("location")) or None
    if not record.get("published_at"):
        record["published_at"] = normalize_date(job.get("confirm_time") or job.get("due_time"))
    record["detail_fetched"] = True
    return record


def collect_wanted(
    query: str,
    limit: int,
    fixture: str | None,
    retrieved_at: str,
    *,
    pages: int = 1,
    fetch_details: bool = False,
    detail_limit: int = 12,
    delay: float = 0.5,
    opener=None,
) -> SourceResult:
    source = "wanted-public-search"
    if fixture:
        status, payload, error = load_fixture(fixture)
        if status != "ok":
            return SourceResult(status, source, errors=[error or "Wanted source failed"], metadata={"query": query})
        return normalize_wanted(payload, query, retrieved_at, limit)

    per_page = min(limit, 20)
    max_pages = max(1, min(pages, 5))
    all_records: list[dict[str, Any]] = []
    all_errors: list[str] = []
    seen: set[str] = set()
    pages_fetched = 0

    for page_idx in range(max_pages):
        offset = page_idx * per_page
        encoded = urllib.parse.urlencode({"query": query, "tab": "position", "limit": per_page, "offset": offset})
        status, payload, error = fetch_json(
            f"{WANTED_ENDPOINT}?{encoded}",
            source,
            timeout=15,
            opener=opener,
            extra_headers={"Referer": "https://www.wanted.co.kr/"},
        )
        if status != "ok":
            if page_idx == 0:
                return SourceResult(status, source, errors=[error or "Wanted source failed"],
                                    metadata={"query": query, "bounded_pages": page_idx + 1})
            all_errors.append(error or f"Wanted page {page_idx + 1} failed")
            break
        pages_fetched += 1
        page_res = normalize_wanted(payload, query, retrieved_at, per_page)
        all_errors.extend(page_res.errors)
        if page_res.status == "invalid_response" and page_idx == 0:
            return page_res
        added = 0
        for rec in page_res.records:
            if rec["source_id"] not in seen:
                seen.add(rec["source_id"])
                all_records.append(rec)
                added += 1
        if len(all_records) >= limit or added == 0 or len(page_res.records) < per_page:
            break
        if delay > 0:
            time.sleep(delay)

    all_records = all_records[:limit]
    details_fetched = 0
    if fetch_details and all_records:
        for rec in all_records[:detail_limit]:
            enrich_wanted_detail(rec, opener=opener)
            if rec.get("detail_fetched"):
                details_fetched += 1
            if delay > 0:
                time.sleep(min(delay, 0.4))

    final_status = "ok" if all_records else ("invalid_response" if all_errors else "empty")
    return SourceResult(final_status, source, all_records, all_errors, {
        "query": query,
        "bounded_pages": pages_fetched,
        "bounded_limit": limit,
        "details_fetched": details_fetched,
    })


# ---------------------------------------------------------------------------
# Saramin (Multi-Page + HTMLParser Card Extraction)
# ---------------------------------------------------------------------------

SARAMIN_EMPTY = re.compile(r"검색\s*결과가\s*없|채용정보가\s*없|검색된\s*공고가\s*없")


class _SaraminCardParser(HTMLParser):
    """Extract structured fields from one Saramin item_recruit HTML block."""

    def __init__(self) -> None:
        super().__init__()
        self.rec_idx: str | None = None
        self.title: str = ""
        self.company: str = ""
        self.conditions: list[str] = []
        self.sectors: list[str] = []
        self.date_text: str = ""
        self._stack: list[tuple[str, str]] = []
        self._buf: list[str] = []
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        cls = attr_map.get("class", "")
        self._stack.append((tag, cls))
        if tag == "input" and not self.rec_idx:
            val = attr_map.get("value", "")
            if re.fullmatch(r"\d{4,12}", val):
                self.rec_idx = val
        if not self.rec_idx and tag == "a":
            m = re.search(r"rec_idx=(\d{4,12})", attr_map.get("href", ""))
            if m:
                self.rec_idx = m.group(1)

        classes_above = " ".join(c for _, c in self._stack)
        if tag == "a" and "job_tit" in classes_above and not self.title:
            if attr_map.get("title"):
                self.title = attr_map["title"]
            else:
                self._capture = "title"
                self._buf = []
        elif tag == "a" and ("corp_name" in classes_above or "area_corp" in classes_above) and not self.company:
            if attr_map.get("title") and "관심기업" not in attr_map.get("title", ""):
                self.company = attr_map["title"]
            else:
                self._capture = "company"
                self._buf = []
        elif tag == "span" and "job_condition" in classes_above:
            self._capture = "condition"
            self._buf = []
        elif tag == "a" and "job_sector" in classes_above:
            self._capture = "sector"
            self._buf = []
        elif tag == "span" and ("job_date" in classes_above or "date" in cls):
            self._capture = "date"
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture:
            text = clean_text("".join(self._buf))
            if text:
                if self._capture == "title" and not self.title:
                    self.title = text
                elif self._capture == "company" and not self.company:
                    self.company = text
                elif self._capture == "condition":
                    self.conditions.append(text)
                elif self._capture == "sector":
                    self.sectors.append(text)
                elif self._capture == "date" and not self.date_text:
                    self.date_text = text
            self._capture = None
            self._buf = []
        if self._stack:
            self._stack.pop()


def _parse_saramin_date(text: str, retrieved_at: str) -> str | None:
    if not text:
        return None
    normalized = normalize_date(text)
    if normalized:
        return normalized
    m = re.search(r"(\d{1,2})[./](\d{1,2})", text)
    if m:
        ref = normalize_date(retrieved_at) or utc_now()
        year = int(ref[:4])
        mo, day = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{mo:02d}-{day:02d}"
    return None


def normalize_saramin_html(
    raw: bytes | str,
    query: str,
    retrieved_at: str,
    limit: int = 20,
) -> SourceResult:
    source = "saramin-public-search"
    try:
        page = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        return SourceResult("invalid_response", source, errors=["Saramin response was not UTF-8"],
                            metadata={"query": query})
    blocks = re.split(r'class="[^"]*\bitem_recruit\b[^"]*"', page)[1:]
    if not blocks:
        if SARAMIN_EMPTY.search(clean_text(page)):
            return SourceResult("empty", source, metadata={"query": query, "bounded_pages": 1})
        return SourceResult("invalid_response", source, errors=[
            "Saramin page had neither recognized result blocks nor an explicit empty-result marker"
        ], metadata={"query": query, "bounded_pages": 1})

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, block in enumerate(blocks):
        if len(records) >= limit:
            break
        card = _SaraminCardParser()
        try:
            card.feed(f'<div class="item_recruit">{block}')
        except Exception:
            pass
        # Regex fallback for minimal fixtures or attribute-order variations
        if not card.rec_idx:
            m = re.search(r'value="(\d+)"|rec_idx=(\d+)', block)
            card.rec_idx = (m.group(1) or m.group(2)) if m else None
        if not card.title:
            tm = re.search(r'job_tit"[^>]*>\s*<a[^>]*title="([^"]+)"', block)
            card.title = clean_text(tm.group(1)) if tm else ""
        if not card.company:
            cm = re.search(r'(?:corp_name|area_corp)"[^>]*>.*?<a[^>]*>\s*(.*?)\s*</a>', block, re.S)
            card.company = clean_text(cm.group(1)) if cm else ""

        if not card.rec_idx or not card.title:
            errors.append(f"block {index}: rec_idx and title are required")
            continue
        native_id = card.rec_idx
        sid = f"saramin:{native_id}"
        if sid in seen:
            continue
        seen.add(sid)
        title = clean_text(card.title)
        if not title:
            errors.append(f"block {index}: empty title")
            continue
        company = clean_text(card.company) or None
        location = card.conditions[0] if card.conditions else None
        experience = ", ".join(card.conditions[1:4]) if len(card.conditions) > 1 else None
        sectors = [s for s in card.sectors if s and s != "외"]
        stack = extract_tech_stack(f"{title} {' '.join(sectors)}", sectors[:8] if sectors else None)
        published = _parse_saramin_date(card.date_text, retrieved_at)
        url = f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={native_id}"
        evidence_raw = {
            "rec_idx": native_id, "title": title, "company": company,
            "location": location, "sectors": sectors, "query": query,
        }
        records.append({
            "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
            "source": source, "source_id": sid,
            "company": company, "company_candidate": company,
            "company_confidence": "public_listing" if company else "unknown",
            "title": title,
            "description": ("분야: " + ", ".join(sectors[:8])) if sectors else None,
            "url": url, "published_at": published,
            "stack": stack, "location": location,
            "experience": experience,
            "sector_candidate": sectors[0] if sectors else None,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, evidence_raw),
        })
    status = "ok" if records else "invalid_response"
    return SourceResult(status, source, records, errors, {
        "query": query, "recognized_blocks": len(blocks), "bounded_pages": 1,
        "bounded_limit": limit,
    })


def collect_saramin(
    query: str,
    limit: int,
    fixture: str | None,
    retrieved_at: str,
    *,
    pages: int = 1,
    delay: float = 0.8,
    opener=None,
) -> SourceResult:
    source = "saramin-public-search"
    if fixture:
        try:
            raw = Path(fixture).read_bytes()
            if len(raw) > MAX_RESPONSE_BYTES:
                return SourceResult("invalid_response", source, errors=[
                    f"fixture exceeded {MAX_RESPONSE_BYTES} bytes"
                ], metadata={"query": query})
            return normalize_saramin_html(raw, query, retrieved_at, limit)
        except OSError as exc:
            return SourceResult("failed", source, errors=[f"fixture read failed: {exc}"], metadata={"query": query})

    max_pages = max(1, min(pages, 5))
    all_records: list[dict[str, Any]] = []
    all_errors: list[str] = []
    seen: set[str] = set()
    pages_fetched = 0

    for page_num in range(1, max_pages + 1):
        encoded = urllib.parse.urlencode({
            "searchType": "search",
            "searchword": query,
            "recruitPage": page_num,
            "recruitSort": "relation",
            "recruitPageCount": 40,
        })
        status, raw, error = fetch_bytes(
            f"{SARAMIN_ENDPOINT}?{encoded}",
            source,
            opener=opener,
            extra_headers={"Referer": "https://www.saramin.co.kr/"},
        )
        if status != "ok" or raw is None:
            if page_num == 1:
                return SourceResult(status, source, errors=[error or "Saramin source failed"],
                                    metadata={"query": query, "bounded_pages": page_num})
            all_errors.append(error or f"Saramin page {page_num} failed")
            break
        pages_fetched += 1
        page_res = normalize_saramin_html(raw, query, retrieved_at, limit - len(all_records))
        all_errors.extend(page_res.errors)
        if page_res.status == "empty":
            break
        if page_res.status == "invalid_response":
            if page_num == 1:
                return page_res
            break
        added = 0
        for rec in page_res.records:
            if rec["source_id"] not in seen:
                seen.add(rec["source_id"])
                all_records.append(rec)
                added += 1
        if len(all_records) >= limit or added == 0:
            break
        if page_num < max_pages and delay > 0:
            time.sleep(delay)

    final_status = "ok" if all_records else ("invalid_response" if all_errors else "empty")
    return SourceResult(final_status, source, all_records[:limit], all_errors, {
        "query": query, "bounded_pages": pages_fetched, "bounded_limit": limit,
    })


# ---------------------------------------------------------------------------
# JobKorea (Next.js JSON + HTML Dual Parser, Multi-Page)
# ---------------------------------------------------------------------------

JOBKOREA_EMPTY = re.compile(r"검색\s*결과가\s*없|일치하는\s*채용정보가\s*없|찾으시는\s*채용공고가\s*없")


def _extract_jobkorea_next_data(page: str) -> list[dict[str, Any]]:
    """Try extracting structured job items from Next.js __NEXT_DATA__ if present."""
    match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S | re.I)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict) and (item.get("gNo") or item.get("giNo")) and (item.get("gTitle") or item.get("title") or item.get("giTitle")):
                    found.append(item)
                else:
                    walk(item)
        elif isinstance(node, dict):
            for val in node.values():
                walk(val)

    walk(data)
    return found


def normalize_jobkorea_html(
    raw: bytes | str,
    query: str,
    retrieved_at: str,
    limit: int = 20,
) -> SourceResult:
    source = "jobkorea-public-search"
    try:
        page = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        return SourceResult("invalid_response", source, errors=["JobKorea response was not UTF-8"],
                            metadata={"query": query})

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()

    # Strategy 1: __NEXT_DATA__ structured payload
    next_items = _extract_jobkorea_next_data(page)
    for item in next_items[:limit]:
        gi = str(item.get("gNo") or item.get("giNo") or "").strip()
        title = clean_text(item.get("gTitle") or item.get("giTitle") or item.get("title") or "")
        if not gi or not re.fullmatch(r"\d{4,12}", gi) or not title:
            continue
        sid = f"jobkorea:{gi}"
        if sid in seen:
            continue
        seen.add(sid)
        company = clean_text(item.get("cName") or item.get("corpName") or item.get("companyName") or "") or None
        location = clean_text(item.get("workPlace") or item.get("area") or item.get("location") or "") or None
        exp = clean_text(item.get("career") or item.get("experience") or "") or None
        tags = item.get("keywords") or item.get("skills") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[,/|]", tags) if t.strip()]
        url = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gi}"
        records.append({
            "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
            "source": source, "source_id": sid,
            "company": company, "company_candidate": company,
            "company_confidence": "public_listing" if company else "unknown",
            "title": title, "description": (", ".join(tags[:8]) if tags else None),
            "url": url,
            "published_at": normalize_date(item.get("regDt") or item.get("editDt") or item.get("closeDt")),
            "stack": extract_tech_stack(f"{title} {' '.join(tags)}", tags[:8] if tags else None),
            "location": location, "experience": exp,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, item),
        })

    # Strategy 2: HTML card blocks (article / list-item / dev-gi-item) or GI_Read links
    if not records:
        card_blocks = re.split(r'<article\b|class="[^"]*\blist-item\b[^"]*"|data-gno="', page)[1:]
        for block in card_blocks:
            if len(records) >= limit:
                break
            gi_match = re.search(r'(?:Recruit/GI_Read/|gno=)(\d{4,12})', block)
            if not gi_match:
                continue
            gi = gi_match.group(1)
            sid = f"jobkorea:{gi}"
            if sid in seen:
                continue
            # Title extraction
            title = ""
            for pat in (
                r'class="[^"]*(?:title|dev_view|information-title-link)[^"]*"[^>]*title="([^"]+)"',
                r'href="[^"]*GI_Read/' + gi + r'[^"]*"[^>]*title="([^"]+)"',
                r'href="[^"]*GI_Read/' + gi + r'[^"]*"[^>]*>(.*?)</a>',
            ):
                m = re.search(pat, block, re.S | re.I)
                if m:
                    candidate_title = clean_text(m.group(1))
                    if len(candidate_title) >= 2:
                        title = candidate_title
                        break
            if not title:
                continue
            # Company extraction
            company = ""
            for pat in (
                r'class="[^"]*(?:corp-name-link|name\s+dev_view|corp-name)[^"]*"[^>]*title="([^"]+)"',
                r'class="[^"]*(?:corp-name-link|name\s+dev_view|corp-name)[^"]*"[^>]*>(.*?)</a>',
                r'data-company="([^"]+)"',
            ):
                m = re.search(pat, block, re.S | re.I)
                if m:
                    company = clean_text(m.group(1))
                    if company:
                        break
            if not company:
                bracket = re.match(r"\[([^\]]{2,30})\]", title)
                if bracket:
                    company = clean_text(bracket.group(1))
            loc_match = re.search(r'class="[^"]*(?:loc|chip-information-item)[^"]*"[^>]*>(.*?)</span>', block, re.S | re.I)
            location = clean_text(loc_match.group(1)) if loc_match else None
            seen.add(sid)
            url = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gi}"
            ev_raw = {"gi": gi, "title": title, "company": company or None, "location": location, "query": query}
            records.append({
                "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
                "source": source, "source_id": sid,
                "company": company or None, "company_candidate": company or None,
                "company_confidence": "public_listing" if company else "unknown",
                "title": title, "description": None,
                "url": url, "published_at": None,
                "stack": extract_tech_stack(title),
                "location": location or None, "experience": None,
                "review_required": not bool(company),
                "evidence": evidence(source, sid, url, retrieved_at, ev_raw),
            })

    if not records:
        if JOBKOREA_EMPTY.search(clean_text(page)):
            return SourceResult("empty", source, metadata={"query": query, "bounded_pages": 1})
        return SourceResult("invalid_response", source, errors=[
            "JobKorea page had neither recognized job items nor an explicit empty-result marker"
        ], metadata={"query": query, "bounded_pages": 1})

    return SourceResult("ok", source, records, errors, {
        "query": query, "bounded_pages": 1, "bounded_limit": limit,
    })


def collect_jobkorea(
    query: str,
    limit: int,
    fixture: str | None,
    retrieved_at: str,
    *,
    pages: int = 1,
    delay: float = 0.8,
    opener=None,
) -> SourceResult:
    source = "jobkorea-public-search"
    if fixture:
        try:
            raw = Path(fixture).read_bytes()
            if len(raw) > MAX_RESPONSE_BYTES:
                return SourceResult("invalid_response", source, errors=[f"fixture exceeded {MAX_RESPONSE_BYTES} bytes"])
            return normalize_jobkorea_html(raw, query, retrieved_at, limit)
        except OSError as exc:
            return SourceResult("failed", source, errors=[f"fixture read failed: {exc}"])

    max_pages = max(1, min(pages, 5))
    all_records: list[dict[str, Any]] = []
    all_errors: list[str] = []
    seen: set[str] = set()
    pages_fetched = 0

    for page_num in range(1, max_pages + 1):
        encoded = urllib.parse.urlencode({"stext": query, "tabType": "recruit", "Page_No": page_num})
        status, raw, error = fetch_bytes(
            f"{JOBKOREA_ENDPOINT}?{encoded}",
            source,
            opener=opener,
            extra_headers={"Referer": "https://www.jobkorea.co.kr/"},
        )
        if status != "ok" or raw is None:
            if page_num == 1:
                return SourceResult(status, source, errors=[error or "JobKorea source failed"],
                                    metadata={"query": query, "bounded_pages": page_num})
            all_errors.append(error or f"JobKorea page {page_num} failed")
            break
        pages_fetched += 1
        page_res = normalize_jobkorea_html(raw, query, retrieved_at, limit - len(all_records))
        all_errors.extend(page_res.errors)
        if page_res.status == "empty":
            break
        if page_res.status == "invalid_response":
            if page_num == 1:
                return page_res
            break
        added = 0
        for rec in page_res.records:
            if rec["source_id"] not in seen:
                seen.add(rec["source_id"])
                all_records.append(rec)
                added += 1
        if len(all_records) >= limit or added == 0:
            break
        if page_num < max_pages and delay > 0:
            time.sleep(delay)

    final_status = "ok" if all_records else ("invalid_response" if all_errors else "empty")
    return SourceResult(final_status, source, all_records[:limit], all_errors, {
        "query": query, "bounded_pages": pages_fetched, "bounded_limit": limit,
    })


# ---------------------------------------------------------------------------
# Jumpit (Public JSON API with Rich Tech Stack Tags + Detail Enrichment)
# ---------------------------------------------------------------------------

def normalize_jumpit(payload: Any, query: str, retrieved_at: str, limit: int = 20) -> SourceResult:
    source = "jumpit-public-search"
    if not isinstance(payload, dict):
        return SourceResult("invalid_response", source, errors=["Jumpit response must be a JSON object"],
                            metadata={"query": query})
    result_obj = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    positions = result_obj.get("positions")
    if not isinstance(positions, list):
        return SourceResult("invalid_response", source, errors=["Jumpit response missing result.positions list"],
                            metadata={"query": query})

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(positions[:limit]):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: expected object")
            continue
        pid = raw.get("id")
        title = clean_text(raw.get("title") or "")
        if pid is None or not str(pid).strip() or not title:
            errors.append(f"row {index}: id and title are required")
            continue
        pid_str = str(pid).strip()
        sid = f"jumpit:{pid_str}"
        if sid in seen:
            continue
        seen.add(sid)
        company = clean_text(raw.get("companyName") or "") or None
        locs = raw.get("locations")
        location = clean_text(", ".join(str(x) for x in locs)) if isinstance(locs, list) and locs else (
            clean_text(locs) or None
        )
        stacks = raw.get("techStacks")
        raw_stack = [clean_text(s) for s in stacks if clean_text(s)] if isinstance(stacks, list) else []
        min_c, max_c = raw.get("minCareer"), raw.get("maxCareer")
        exp = None
        if isinstance(min_c, int) or isinstance(max_c, int):
            if min_c == 0 and (not max_c or max_c >= 99):
                exp = "신입/경력"
            elif max_c and max_c < 99:
                exp = f"경력 {min_c or 0}~{max_c}년"
            elif min_c:
                exp = f"경력 {min_c}년 이상"
        category = clean_text(raw.get("jobCategory") or "") or None
        url = f"https://www.jumpit.co.kr/position/{urllib.parse.quote(pid_str, safe='')}"
        records.append({
            "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
            "source": source, "source_id": sid,
            "company": company, "company_candidate": company,
            "company_confidence": "public_listing" if company else "unknown",
            "title": title,
            "description": f"직무분류: {category}" if category else None,
            "url": url,
            "published_at": normalize_date(raw.get("publishedAt") or raw.get("closedAt")),
            "stack": extract_tech_stack(title, raw_stack),
            "location": location, "experience": exp,
            "sector_candidate": category,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, raw),
        })

    status = "ok" if records else ("invalid_response" if errors else "empty")
    return SourceResult(status, source, records, errors, {
        "query": query, "returned_positions": len(positions), "bounded_limit": limit,
    })


def enrich_jumpit_detail(record: dict[str, Any], *, opener=None) -> dict[str, Any]:
    sid = str(record.get("source_id") or "")
    if not sid.startswith("jumpit:"):
        return record
    pid = sid.split(":", 1)[1]
    if not re.fullmatch(r"\d{1,12}", pid):
        return record
    status, payload, _err = fetch_json(
        JUMPIT_DETAIL_ENDPOINT.format(job_id=pid),
        "jumpit-detail",
        timeout=12,
        opener=opener,
        extra_headers={"Referer": f"https://www.jumpit.co.kr/position/{pid}"},
        retries=0,
    )
    if status != "ok" or not isinstance(payload, dict):
        return record
    detail = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    parts = []
    for label, key in (("주요업무", "responsibility"), ("자격요건", "qualifications"), ("우대사항", "preferredRequirements")):
        text = clean_text(detail.get(key))
        if text:
            parts.append(f"[{label}] {text[:500]}")
    if parts:
        record["description"] = " / ".join(parts)[:1800]
    tags = detail.get("techStacks")
    tag_names = [(t.get("stack") if isinstance(t, dict) else str(t)) for t in (tags if isinstance(tags, list) else [])]
    record["stack"] = extract_tech_stack(
        f"{record.get('title') or ''} {record.get('description') or ''}",
        (record.get("stack") or []) + tag_names,
    )
    record["detail_fetched"] = True
    return record


def extract_job_image_urls(html_text: str, base_url: str = "", *, limit: int = 6) -> list[str]:
    """Extract content/JD image URLs from Korean job-detail pages (e.g. Saramin/JobKorea image JDs)."""
    import web_extract
    return web_extract.extract_image_urls(html_text, base_url=base_url, limit=limit)


def enrich_image_job(
    record: dict[str, Any],
    *,
    html_text: str = "",
    home: str | Path | None = None,
    opener=None,
    max_images: int = 2,
) -> dict[str, Any]:
    """Detect image-only job descriptions and extract text via tesseract or optional Vision API."""
    import web_extract

    page_html = html_text
    job_url = str(record.get("url") or "")
    if not page_html and job_url.startswith(("http://", "https://")):
        status, raw, _err = fetch_bytes(job_url, "job-detail-image", timeout=15, opener=opener, retries=0)
        if status == "ok" and raw:
            page_html = raw.decode("utf-8", errors="ignore")
    if not page_html:
        return record

    images = extract_job_image_urls(page_html, base_url=job_url, limit=6)
    record["image_urls"] = images
    existing_desc = str(record.get("description") or "").strip()
    if not images or len(existing_desc) >= 240:
        return record

    extracted_chunks: list[str] = []
    providers: list[str] = []
    last_hint = ""
    for img_url in images[:max(1, min(max_images, 4))]:
        res = web_extract.extract_image_text(img_url, home=home, opener=opener)
        if res.get("status") == "ok" and res.get("text"):
            extracted_chunks.append(str(res["text"]))
            providers.append(str(res.get("provider") or "ocr"))
        elif res.get("hint"):
            last_hint = str(res["hint"])

    if extracted_chunks:
        merged = "\n".join(extracted_chunks)[:2400]
        record["description"] = (existing_desc + "\n[이미지 공고 OCR]\n" + merged).strip()[:2600]
        record["stack"] = extract_tech_stack(
            f"{record.get('title') or ''} {record.get('description') or ''}",
            list(record.get("stack") or []),
        )
        record["ocr_status"] = "ok"
        record["ocr_provider"] = ",".join(dict.fromkeys(providers))
        record["detail_fetched"] = True
    else:
        record["ocr_status"] = "ocr_unavailable"
        if last_hint:
            record["ocr_hint"] = last_hint
    return record


def collect_jumpit(
    query: str,
    limit: int,
    fixture: str | None,
    retrieved_at: str,
    *,
    pages: int = 1,
    fetch_details: bool = False,
    detail_limit: int = 12,
    delay: float = 0.5,
    opener=None,
) -> SourceResult:
    source = "jumpit-public-search"
    if fixture:
        status, payload, error = load_fixture(fixture)
        if status != "ok":
            return SourceResult(status, source, errors=[error or "Jumpit source failed"], metadata={"query": query})
        return normalize_jumpit(payload, query, retrieved_at, limit)

    max_pages = max(1, min(pages, 5))
    all_records: list[dict[str, Any]] = []
    all_errors: list[str] = []
    seen: set[str] = set()
    pages_fetched = 0

    for page_num in range(1, max_pages + 1):
        encoded = urllib.parse.urlencode({"keyword": query, "page": page_num, "sort": "rsp_rate"})
        status, payload, error = fetch_json(
            f"{JUMPIT_ENDPOINT}?{encoded}",
            source,
            timeout=15,
            opener=opener,
            extra_headers={"Referer": "https://www.jumpit.co.kr/"},
        )
        if status != "ok":
            if page_num == 1:
                return SourceResult(status, source, errors=[error or "Jumpit source failed"],
                                    metadata={"query": query, "bounded_pages": page_num})
            all_errors.append(error or f"Jumpit page {page_num} failed")
            break
        pages_fetched += 1
        page_res = normalize_jumpit(payload, query, retrieved_at, limit - len(all_records))
        all_errors.extend(page_res.errors)
        if page_res.status == "empty":
            break
        if page_res.status == "invalid_response":
            if page_num == 1:
                return page_res
            break
        added = 0
        for rec in page_res.records:
            if rec["source_id"] not in seen:
                seen.add(rec["source_id"])
                all_records.append(rec)
                added += 1
        if len(all_records) >= limit or added == 0:
            break
        if page_num < max_pages and delay > 0:
            time.sleep(delay)

    all_records = all_records[:limit]
    details_fetched = 0
    if fetch_details and all_records:
        for rec in all_records[:detail_limit]:
            enrich_jumpit_detail(rec, opener=opener)
            if rec.get("detail_fetched"):
                details_fetched += 1
            if delay > 0:
                time.sleep(min(delay, 0.4))

    final_status = "ok" if all_records else ("invalid_response" if all_errors else "empty")
    return SourceResult(final_status, source, all_records, all_errors, {
        "query": query, "bounded_pages": pages_fetched, "bounded_limit": limit,
        "details_fetched": details_fetched,
    })


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


# ---------------------------------------------------------------------------
# Typed Imports (Funding, Procurement, Overseas Partner)
# ---------------------------------------------------------------------------

TYPED_ALIASES = {
    "company": ("company", "company_name", "organization", "issuer", "buyer", "partner", "기관명", "수요기관", "회사명"),
    "title": ("title", "name", "notice_title", "project", "공고명", "사업명"),
    "url": ("url", "link", "notice_url", "공고url", "링크"),
    "published_at": ("published_at", "date", "posted_at", "notice_date", "게시일", "공고일"),
    "source": ("source", "portal", "registry", "출처"),
    "source_id": ("source_id", "id", "notice_id", "공고번호"),
    "location": ("location", "region", "country", "지역", "국가"),
    "description": ("description", "summary", "details", "내용", "요약"),
}


def _typed_lookup(row: dict[str, Any], field_name: str) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in TYPED_ALIASES[field_name]:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def normalize_typed_rows(
    rows: Iterable[Any],
    record_type: str,
    retrieved_at: str,
    source_default: str = "user-file",
) -> SourceResult:
    """Normalize user-provided funding, tender, or partner evidence."""
    if record_type not in {"funding_signal", "procurement", "overseas_partner"}:
        raise ValueError("unsupported typed record_type")
    rows = list(rows)
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: expected object")
            continue
        title = clean_text(_typed_lookup(raw, "title"))
        url = canonical_url(_typed_lookup(raw, "url"))
        if not title or not url:
            errors.append(f"row {index}: title and public http(s) URL are required")
            continue
        company = clean_text(_typed_lookup(raw, "company")) or None
        source = clean_text(_typed_lookup(raw, "source")) or source_default
        sid = source_id_from_url(source, url, _typed_lookup(raw, "source_id"))
        key = f"{source.casefold()}:{sid}"
        if key in seen:
            continue
        seen.add(key)
        description = clean_text(_typed_lookup(raw, "description")) or None
        records.append({
            "schema_version": SCHEMA_VERSION, "record_type": record_type,
            "source": source, "source_id": sid, "company": company,
            "company_candidate": company, "company_confidence": "provided" if company else "unknown",
            "title": title, "description": description, "url": url,
            "published_at": normalize_date(_typed_lookup(raw, "published_at")),
            "stack": extract_tech_stack(f"{title} {description or ''}"),
            "location": clean_text(_typed_lookup(raw, "location")) or None,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, raw),
        })
    status = "ok" if records else ("invalid_response" if errors else "empty")
    return SourceResult(status, f"{record_type}-import", records, errors, {
        "duplicates_removed": max(0, len(rows) - len(records) - len(errors)),
    })


def import_typed(path: str, format_name: str, record_type: str, retrieved_at: str) -> SourceResult:
    status, rows, error = read_job_rows(path, format_name)
    if status != "ok":
        return SourceResult(status, f"{record_type}-import", errors=[error or "typed import failed"])
    return normalize_typed_rows(rows or [], record_type, retrieved_at)


# ---------------------------------------------------------------------------
# Config Filtering
# ---------------------------------------------------------------------------

def load_source_config(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Read only the non-secret setup fields used by source filtering."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return None, f"config read failed: {exc}"
    if len(raw) > 1024 * 1024:
        return None, "config exceeded 1048576 bytes"
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "config must be valid UTF-8 JSON"
    if not isinstance(data, dict):
        return None, "config must be a JSON object"
    for key in ("job_keywords", "funding_keywords", "keywords", "region", "exclude_keywords", "g2b_keywords"):
        if key in data and not isinstance(data[key], str):
            return None, f"config field {key} must be a string"
    if "workflows" in data:
        workflows = data["workflows"]
        if not isinstance(workflows, list) or any(not isinstance(value, str) for value in workflows):
            return None, "config field workflows must be a string list"
        allowed = {"jobs", "funding", "tenders", "overseas"}
        if len(workflows) != len(set(workflows)) or any(value not in allowed for value in workflows):
            return None, "config field workflows contains an unknown or duplicate value"
    return data, None


def split_filter_terms(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    terms = [clean_text(term).casefold() for term in re.split(r"[,;|/\n]+", value)]
    return list(dict.fromkeys(term for term in terms if term))


def workflow_enabled(config: dict[str, Any], workflow: str) -> bool:
    """A missing workflows field is backward compatible; an explicit list is authoritative."""
    return "workflows" not in config or workflow in config["workflows"]


def disabled_workflow_result(source: str, workflow: str) -> SourceResult:
    return SourceResult("empty", source, metadata={
        "filters": {
            "configured": True,
            "workflow": workflow,
            "workflow_enabled": False,
            "input_records": 0,
            "kept_records": 0,
            "excluded_by_include_keyword": 0,
            "excluded_by_exclude_keyword": 0,
            "excluded_by_region": 0,
            "region_unknown_kept": 0,
        }
    })


def apply_config_filters(result: SourceResult, config: dict[str, Any], workflow: str) -> SourceResult:
    """Filter successful records without changing evidence or masking source failures."""
    if result.status not in ("ok", "empty"):
        return result
    specific_key = {"jobs": "job_keywords", "funding": "funding_keywords", "tenders": "g2b_keywords"}.get(workflow)
    include_terms = split_filter_terms(config.get(specific_key)) if specific_key else []
    if not include_terms:
        include_terms = split_filter_terms(config.get("keywords"))
    exclude_terms = split_filter_terms(config.get("exclude_keywords"))
    region_terms = split_filter_terms(config.get("region")) if workflow == "jobs" else []
    counts = {
        "configured": True,
        "workflow": workflow,
        "workflow_enabled": True,
        "input_records": len(result.records),
        "kept_records": 0,
        "include_keyword_count": len(include_terms),
        "exclude_keyword_count": len(exclude_terms),
        "region_term_count": len(region_terms),
        "excluded_by_include_keyword": 0,
        "excluded_by_exclude_keyword": 0,
        "excluded_by_region": 0,
        "region_unknown_kept": 0,
    }
    kept: list[dict[str, Any]] = []
    for record in result.records:
        stack = record.get("stack")
        stack_text = " ".join(str(value) for value in stack) if isinstance(stack, list) else ""
        searchable = " ".join(clean_text(record.get(key)) for key in (
            "title", "description", "company", "company_candidate", "sector_candidate", "round_candidate"
        ))
        searchable = f"{searchable} {stack_text} {clean_text(record.get('location'))}".casefold()
        if exclude_terms and any(term in searchable for term in exclude_terms):
            counts["excluded_by_exclude_keyword"] += 1
            continue
        if include_terms and not any(term in searchable for term in include_terms):
            counts["excluded_by_include_keyword"] += 1
            continue
        if region_terms:
            location = clean_text(record.get("location")).casefold()
            if not location:
                counts["region_unknown_kept"] += 1
            elif not any(term in location or location in term for term in region_terms):
                counts["excluded_by_region"] += 1
                continue
        kept.append(record)
    counts["kept_records"] = len(kept)
    metadata = dict(result.metadata)
    metadata["filters"] = counts
    return SourceResult("ok" if kept else "empty", result.source, kept, list(result.errors), metadata)


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
