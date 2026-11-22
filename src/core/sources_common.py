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


