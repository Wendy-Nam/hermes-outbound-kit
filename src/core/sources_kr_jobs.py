#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401
"""Korean Job Board Collectors (Wanted, Saramin, JobKorea, Jumpit) & Image JD OCR.

Isolated per-board parsers so site HTML/JSON schema changes can be updated in one small file.
"""
import csv
import html
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable
import urllib.parse

from sources_common import (
    JOBKOREA_ENDPOINT,
    JUMPIT_DETAIL_ENDPOINT,
    JUMPIT_ENDPOINT,
    MAX_RESPONSE_BYTES,
    SARAMIN_ENDPOINT,
    SCHEMA_VERSION,
    SourceResult,
    WANTED_DETAIL_ENDPOINT,
    WANTED_ENDPOINT,
    canonical_url,
    clean_text,
    evidence,
    extract_tech_stack,
    fetch_bytes,
    fetch_json,
    load_fixture,
    normalize_date,
    source_id_from_url,
    utc_now,
)

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


