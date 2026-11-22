#!/usr/bin/env python3
"""distributor_finder.py — Overseas distributor / master importer / reseller prospecting pipeline.

Zero external dependencies (Python 3.11+ stdlib).
Features:
1. Extract local distributors from competitor/peer 'Where to Buy / Distributors / Partners' web pages
   (respects 401/403/429 without bypassing) and trade-show exhibitor CSV/JSON lists.
2. Dedicated 4-axis distributor scoring (Product Category Fit 35 + Target Country Coverage 25
   + Distributor/Channel Type & Portfolio 25 + Certifications/B2B Infrastructure 15) + optional Jev.
3. Native multi-language distributor outreach sequences (English, Japanese, German, Korean) —
   written natively per locale (not awkward literal translation) and linted via copy_guard.py.
4. Obsidian Vault export (vault/Distributors/Pipeline.md + Candidates/<country>-<company>.md).
"""
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import csv
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from typing import Any
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import copy_guard  # noqa: E402
import paths  # noqa: E402
import profile_presets  # noqa: E402
import sources  # noqa: E402
import web_extract  # noqa: E402

COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "US": ("united states", "usa", "u.s.a", "u.s.", "north america", "california", "new york", "texas", "미국"),
    "DE": ("germany", "deutschland", "munich", "berlin", "frankfurt", "hamburg", "독일"),
    "JP": ("japan", "tokyo", "osaka", "nagoya", "日本", "東京", "大阪", "일본"),
    "UK": ("united kingdom", "uk", "london", "england", "britain", "영국"),
    "FR": ("france", "paris", "lyon", "프랑스"),
    "NL": ("netherlands", "holland", "amsterdam", "rotterdam", "네덜란드"),
    "SG": ("singapore", "싱가포르"),
    "VN": ("vietnam", "ho chi minh", "hanoi", "베트남"),
    "TH": ("thailand", "bangkok", "태국"),
    "ID": ("indonesia", "jakarta", "인도네시아"),
    "AU": ("australia", "sydney", "melbourne", "호주"),
    "AE": ("uae", "dubai", "abu dhabi", "middle east", "두바이", "아랍에미리트"),
    "CA": ("canada", "toronto", "vancouver", "캐나다"),
    "EU": ("europe", "eu", "dach", "benelux", "nordics", "유럽"),
}

DISTRIBUTOR_ROLE_RX = re.compile(
    r"(distributor|importer|wholesale|authorized\s+dealer|master\s+distributor|reseller|"
    r"stockist|trading\s+co|agent|channel\s+partner|value[- ]added\s+reseller|var\b|"
    r"代理店|販売代理|輸入|商社|händler|vertrieb|großhandel|대리점|총판|수입상|유통사)",
    re.I,
)
CERT_INFRA_RX = re.compile(
    r"(ce\b|fda\b|pmda\b|iso\s*13485|iso\s*9001|gmp\b|rohs|ul\b|cold\s*chain|"
    r"warehouse|service\s*center|after[- ]sales|warranty|showroom|b2b\s*portal|customs|exhibitor|booth)",
    re.I,
)
ROLE_EMAIL_RX = re.compile(
    r"\b(?:info|sales|contact|hello|partner|partners|export|import|inquiry|enquiry|business|distribution)@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    re.I,
)


def _detect_country(text: str) -> str:
    low = (text or "").casefold()
    for code, aliases in COUNTRY_ALIASES.items():
        if any(a in low for a in aliases):
            return code
    return "UNKNOWN"


class _DistributorHTMLParser(HTMLParser):
    """Extract structured candidate blocks (cards, table rows, list items) with links and text."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._skip = 0
        self._in_block = 0
        self._block_tag = ""
        self._text_parts: list[str] = []
        self._links: list[str] = []
        self._headings: list[str] = []
        self._in_heading = False
        self._heading_buf: list[str] = []
        self.blocks: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "svg"):
            self._skip += 1
            return
        if self._skip:
            return
        attr = dict(attrs)
        cls = (attr.get("class") or "").lower()
        is_card = (
            t in ("tr", "li", "article")
            or (t in ("div", "section") and any(k in cls for k in ("distributor", "partner", "dealer", "exhibitor", "card", "item", "company")))
        )
        if is_card and self._in_block == 0:
            self._in_block = 1
            self._block_tag = t
            self._text_parts = []
            self._links = []
            self._headings = []
        elif self._in_block > 0 and t == self._block_tag:
            self._in_block += 1

        if self._in_block > 0:
            if t in ("h1", "h2", "h3", "h4", "strong", "b"):
                self._in_heading = True
                self._heading_buf = []
            if t == "a" and attr.get("href"):
                href = urllib.parse.urljoin(self.base_url, attr["href"].strip())
                if href.startswith(("http://", "https://")):
                    self._links.append(href)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if self._in_heading and t in ("h1", "h2", "h3", "h4", "strong", "b"):
            self._in_heading = False
            h = sources.clean_text(" ".join(self._heading_buf))
            if 2 <= len(h) <= 120:
                self._headings.append(h)
        if self._in_block > 0 and t == self._block_tag:
            self._in_block -= 1
            if self._in_block == 0:
                text = sources.clean_text(" ".join(self._text_parts))
                if 15 <= len(text) <= 2000:
                    self.blocks.append({
                        "headings": self._headings[:3],
                        "text": text,
                        "links": list(dict.fromkeys(self._links))[:5],
                    })

    def handle_data(self, data: str) -> None:
        if self._skip or self._in_block <= 0:
            return
        s = data.strip()
        if not s:
            return
        self._text_parts.append(s)
        if self._in_heading:
            self._heading_buf.append(s)


def extract_distributors_from_html(
    raw_html: bytes | str,
    source_url: str,
    *,
    target_countries: list[str] | None = None,
    competitor_brand: str = "",
) -> list[dict[str, Any]]:
    """Parse a competitor 'Where to Buy / Distributors' or exhibitor HTML page into candidate records."""
    html_text = raw_html.decode("utf-8", errors="replace") if isinstance(raw_html, bytes) else raw_html
    parser = _DistributorHTMLParser(source_url)
    parser.feed(html_text)

    source_host = (urllib.parse.urlsplit(source_url).hostname or "").lower()
    want_countries = {c.strip().upper() for c in (target_countries or []) if c.strip()}
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for blk in parser.blocks:
        text = blk["text"]
        ext_links = [
            u for u in blk["links"]
            if (urllib.parse.urlsplit(u).hostname or "").lower() != source_host
        ]
        # Require either an external company website, a role email, a country cue, or distributor keyword
        country = _detect_country(text)
        emails = ROLE_EMAIL_RX.findall(text)
        has_signal = bool(ext_links or emails or country != "UNKNOWN" or DISTRIBUTOR_ROLE_RX.search(text))
        if not has_signal:
            continue
        company = blk["headings"][0] if blk["headings"] else text.split("|")[0].split("—")[0].split("-")[0].strip()[:80]
        if not company or len(company) < 2:
            continue
        ckey = sources._norm_company_key(company)
        if not ckey or ckey in seen:
            continue
        if want_countries and country != "UNKNOWN" and country not in want_countries:
            continue
        seen.add(ckey)
        candidates.append({
            "company": company[:160],
            "company_key": ckey,
            "country": country,
            "website": ext_links[0] if ext_links else "",
            "public_contact_email": emails[0] if emails else "",
            "brands_carried": [competitor_brand] if competitor_brand else [],
            "categories": [],
            "description": text[:800],
            "source_url": source_url,
            "source_type": "distributor_page",
        })
    return candidates


def fetch_distributor_pages(
    urls: list[str],
    *,
    target_countries: list[str] | None = None,
    competitor_brand: str = "",
    render_js: bool = False,
    home: str | Path | None = None,
    opener=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch public distributor/exhibitor pages respectfully (never bypass 401/403/429)."""
    all_items: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for url in urls:
        u = url.strip()
        if not u:
            continue
        status, raw, err = sources.fetch_bytes(u, "distributor-page", timeout=20, opener=opener)
        if status != "ok" or not raw:
            errors.append(f"{u}: {status} ({err or 'fetch failed'})")
            continue
        parsed = extract_distributors_from_html(
            raw, u, target_countries=target_countries, competitor_brand=competitor_brand
        )
        if render_js or (not parsed and web_extract.looks_like_js_shell(raw)):
            rendered = web_extract.render_js_page(
                u, home=home, formats=("html", "markdown"), opener=opener
            )
            if rendered.get("status") == "ok":
                fc_html = rendered.get("html") or ""
                if not fc_html and rendered.get("markdown"):
                    lines = [f"<p>{line}</p>" for line in rendered["markdown"].splitlines() if line.strip()]
                    fc_html = "<html><body>" + "\n".join(lines) + "</body></html>"
                if fc_html:
                    parsed = extract_distributors_from_html(
                        fc_html, u, target_countries=target_countries, competitor_brand=competitor_brand
                    )
            elif rendered.get("status") in ("missing_key", "js_renderer_unavailable") and not parsed:
                errors.append(f"{u}: js_shell_detected ({rendered.get('hint') or 'Crawl4AI 또는 FIRECRAWL_API_KEY 필요'})")
        for item in parsed:
            if item["company_key"] not in seen:
                seen.add(item["company_key"])
                all_items.append(item)
    return all_items, errors


def import_distributors_file(
    path: str | Path,
    *,
    target_countries: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Import trade-show exhibitor list or overseas importer directory CSV/JSON."""
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"읽을 수 있는 파일이 아닙니다: {path}")
    if target.suffix.lower() == ".json":
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        rows = raw.get("items", raw) if isinstance(raw, dict) else raw
    else:
        with target.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))

    want_countries = {c.strip().upper() for c in (target_countries or []) if c.strip()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        company = sources.clean_text(
            row.get("company") or row.get("Company") or row.get("Exhibitor") or row.get("name") or row.get("Name") or ""
        )
        if not company:
            continue
        ckey = sources._norm_company_key(company)
        if not ckey or ckey in seen:
            continue
        raw_country = sources.clean_text(row.get("country") or row.get("Country") or row.get("Region") or "")
        country = raw_country.upper() if len(raw_country) == 2 and raw_country.isalpha() else _detect_country(
            f"{raw_country} {row.get('description') or ''} {row.get('Location') or ''}"
        )
        if want_countries and country != "UNKNOWN" and country not in want_countries:
            continue
        seen.add(ckey)
        brands = profile_presets.split_terms(row.get("brands") or row.get("Brands") or row.get("brands_carried") or "")
        cats = profile_presets.split_terms(row.get("category") or row.get("Category") or row.get("Products") or row.get("categories") or "")
        desc = sources.clean_text(row.get("description") or row.get("Description") or row.get("Notes") or "")
        booth = sources.clean_text(row.get("booth") or row.get("Booth") or "")
        if booth:
            desc = f"Exhibitor Booth {booth}. {desc}".strip()
        email_raw = sources.clean_text(row.get("email") or row.get("Email") or "")
        pub_email = email_raw if ROLE_EMAIL_RX.fullmatch(email_raw) else ""
        out.append({
            "company": company[:160],
            "company_key": ckey,
            "country": country,
            "website": sources.clean_text(row.get("website") or row.get("Website") or row.get("url") or "")[:300],
            "public_contact_email": pub_email,
            "brands_carried": brands,
            "categories": cats,
            "description": desc[:1000],
            "source_url": sources.clean_text(row.get("source_url") or str(target.name)),
            "source_type": "exhibitor_or_directory_file",
        })
    return out


# ---------------------------------------------------------------------------
# 2. Dedicated 4-Axis Distributor Scoring
# ---------------------------------------------------------------------------

def score_distributor(
    cand: dict[str, Any],
    *,
    product_keywords: list[str],
    target_countries: list[str] | None = None,
    competitor_brands: list[str] | None = None,
    required_certs: list[str] | None = None,
) -> dict[str, Any]:
    """Score an overseas distributor candidate on 4 domain-specific axes (total 100)."""
    blob = " ".join([
        cand.get("company", ""),
        cand.get("country", ""),
        " ".join(cand.get("categories") or []),
        " ".join(cand.get("brands_carried") or []),
        cand.get("description", ""),
    ])
    low = blob.casefold()

    # Axis 1: Product category alignment (0..35)
    kw_hits = [k for k in product_keywords if k.strip() and k.casefold() in low]
    cat_score = min(35, len(kw_hits) * 12) if kw_hits else 0

    # Axis 2: Target country coverage (0..25)
    wants = {c.strip().upper() for c in (target_countries or []) if c.strip()}
    country = (cand.get("country") or "UNKNOWN").upper()
    if not wants:
        country_score = 20 if country != "UNKNOWN" else 10
    elif country in wants:
        country_score = 25
    elif country == "EU" and any(c in wants for c in ("DE", "FR", "NL", "UK", "EU")):
        country_score = 20
    else:
        country_score = 0

    # Axis 3: Distributor/Importer model & brand portfolio (0..25)
    role_matches = DISTRIBUTOR_ROLE_RX.findall(blob)
    role_score = 18 if role_matches else 6
    comp_carried = [
        b for b in (competitor_brands or [])
        if b.strip() and b.casefold() in low
    ]
    if comp_carried:
        role_score = min(25, role_score + 7)  # Proven buyer of same category (note exclusivity risk!)
    elif cand.get("brands_carried"):
        role_score = min(25, role_score + 5)

    # Axis 4: Certifications / B2B distribution infrastructure (0..15)
    cert_hits = CERT_INFRA_RX.findall(blob)
    req_hits = [c for c in (required_certs or []) if c.strip() and c.casefold() in low]
    infra_score = min(15, len(set(x.lower() for x in cert_hits)) * 5 + len(req_hits) * 5)

    total = cat_score + country_score + role_score + infra_score
    tier = "최우선 대리점(A)" if total >= 70 else ("유망 대리점(B)" if total >= 45 else "추가 확인(C)")

    notes: list[str] = []
    if kw_hits:
        notes.append(f"품목 일치({', '.join(kw_hits[:3])})")
    if comp_carried:
        notes.append(f"경쟁/유사 브랜드 취급({', '.join(comp_carried[:2])}) — 독점 계약 여부 확인 필요")
    if cert_hits:
        notes.append(f"유통/인증 단서({', '.join(list(dict.fromkeys(cert_hits))[:3])})")

    return {
        "total": total,
        "tier": tier,
        "breakdown": {
            "category_fit": cat_score,
            "country_fit": country_score,
            "channel_portfolio": role_score,
            "cert_infra": infra_score,
        },
        "matched_keywords": kw_hits[:6],
        "competitor_brands_detected": comp_carried,
        "notes": notes or ["기본 후보 — 웹사이트 취급 품목 수동 확인 권장"],
    }


END_USER_SIZE_RX = re.compile(
    r"(enterprise|public|listed|fortune|global|series\s*[a-d]|factory|plant|hospital|clinic|"
    r"headquarters|employees|\b[1-9][0-9]{2,}\s*(?:employees|staff|people))",
    re.I,
)
END_USER_TIMING_RX = re.compile(
    r"(hiring|careers|open\s+roles|expansion|new\s+plant|new\s+facility|raised|series\s*[a-d]|"
    r"exhibitor|booth|launching|migration|digital\s+transformation|automation|compliance|soc2|gdpr|iso)",
    re.I,
)


def score_end_user(
    cand: dict[str, Any],
    *,
    product_keywords: list[str],
    target_countries: list[str] | None = None,
    competitor_brands: list[str] | None = None,
    required_certs: list[str] | None = None,
) -> dict[str, Any]:
    """Score an overseas direct B2B end-user company on 4 axes (total 100)."""
    blob = " ".join([
        cand.get("company", ""),
        cand.get("country", ""),
        " ".join(cand.get("categories") or []),
        " ".join(cand.get("brands_carried") or []),
        cand.get("description", ""),
    ])
    low = blob.casefold()

    # Axis 1: Industry / use-case fit (0..35)
    kw_hits = [k for k in product_keywords if k.strip() and k.casefold() in low]
    usecase_score = min(35, len(kw_hits) * 12) if kw_hits else 0

    # Axis 2: Target country coverage (0..20)
    wants = {c.strip().upper() for c in (target_countries or []) if c.strip()}
    country = (cand.get("country") or "UNKNOWN").upper()
    if not wants:
        country_score = 16 if country != "UNKNOWN" else 8
    elif country in wants:
        country_score = 20
    elif country == "EU" and any(c in wants for c in ("DE", "FR", "NL", "UK", "EU")):
        country_score = 16
    else:
        country_score = 0

    # Axis 3: End-user scale & tech/operations readiness (0..30)
    stacks = sources.extract_tech_stack(blob) or []
    size_hits = END_USER_SIZE_RX.findall(blob)
    is_pure_reseller = bool(DISTRIBUTOR_ROLE_RX.search(blob)) and not bool(size_hits)
    readiness = min(15, len(stacks) * 5) + (15 if size_hits else 6)
    if is_pure_reseller:
        readiness = max(0, readiness - 10)

    # Axis 4: Buying/timing signals & compliance cues (0..15)
    timing_hits = END_USER_TIMING_RX.findall(blob)
    req_hits = [c for c in (required_certs or []) if c.strip() and c.casefold() in low]
    comp_hits = [b for b in (competitor_brands or []) if b.strip() and b.casefold() in low]
    timing_score = min(15, len(set(x.lower() for x in timing_hits)) * 5 + len(req_hits) * 5 + len(comp_hits) * 5)

    total = usecase_score + country_score + readiness + timing_score
    tier = "최우선 엔드유저(A)" if total >= 70 else ("유망 엔드유저(B)" if total >= 45 else "추가 확인(C)")

    notes: list[str] = []
    if kw_hits:
        notes.append(f"도메인 일치({', '.join(kw_hits[:3])})")
    if stacks:
        notes.append(f"감지 스택/도구({', '.join(stacks[:4])})")
    if comp_hits:
        notes.append(f"경쟁 제품 사용 단서({', '.join(comp_hits[:2])}) — 교체/보완 포인트 확인")
    if is_pure_reseller:
        notes.append("유통사/대리점 성향 강함 — 엔드유저 직접 영업 대상인지 확인 필요")

    return {
        "total": total,
        "tier": tier,
        "breakdown": {
            "usecase_fit": usecase_score,
            "country_fit": country_score,
            "scale_tech_readiness": readiness,
            "timing_signal": timing_score,
        },
        "matched_keywords": kw_hits[:6],
        "detected_stack": stacks[:8],
        "competitor_brands_detected": comp_hits,
        "notes": notes or ["기본 후보 — 의사결정자(VP/Head/Director) LinkedIn 소싱 권장"],
    }


# ---------------------------------------------------------------------------
# 3. Native Multi-Language Outreach Sequences (Distributor & Direct B2B End-User)
# ---------------------------------------------------------------------------

def _default_locale_for_country(country: str) -> str:
    c = (country or "").upper()
    if c == "JP":
        return "ja"
    if c == "DE":
        return "de"
    if c == "KR":
        return "ko"
    return "en"


def draft_end_user_sequence(
    cand: dict[str, Any],
    profile: dict[str, Any],
    *,
    locale: str = "auto",
) -> dict[str, Any]:
    """Generate native (non-translated) 2-touch direct B2B end-user outreach copy + buyer checklist."""
    lang = _default_locale_for_country(cand.get("country", "")) if locale == "auto" else locale.lower()
    company = cand.get("company") or "Team"
    country = cand.get("country") or "your region"
    product = (profile.get("product") or "our B2B solution").strip()
    val = (profile.get("value_proposition") or "").strip()
    proof = (profile.get("proof_points") or "").strip()
    s_name = (profile.get("sender_name") or "[Name]").strip()
    s_comp = (profile.get("sender_company") or "[Company]").strip()
    s_contact = (profile.get("sender_contact") or "").strip()
    sign = " · ".join(x for x in (s_name, s_comp, s_contact) if x)
    cats_hint = ", ".join((cand.get("categories") or [])[:2])

    if lang == "ja":
        subj = f"{company}様 {cats_hint or '業務運用'}に関する短い確認"
        obs = f"{company}様の{cats_hint or '事業・製品'}に関する公開情報を拝見し、短くご連絡いたしました。"
        touch1 = (
            f"{company} ご担当者様\n\n"
            f"初めてご連絡いたします。{s_comp}の{s_name}と申します。\n"
            f"{obs}\n"
            f"弊社は{product}を提供しており、{val or '現場の運用負荷と手作業を減らす支援を行っています'}。\n\n"
            f"今期の優先課題でなければそのままお読み流しください。\n"
            f"もし参考になりそうでしたら、導入事例と仕様をまとめた1ページ資料を先にお送りしてもよろしいでしょうか。\n\n"
            f"よろしくお願いいたします。\n{sign}"
        )
        touch2 = (
            f"{company} ご担当者様\n\n"
            f"先日のメールに1点だけ補足いたします。{proof or '既存環境に合わせた小規模な検証（PoC）手順も1ページにまとめております。'}\n"
            f"もし本件のご担当部署が別でしたら、お名前のみご教示いただけますと幸いです。\n\n"
            f"よろしくお願いいたします。\n{sign}"
        )
    elif lang == "de":
        subj = f"{company} / kurze Frage zu {cats_hint or 'Betrieb & Prozess'}"
        obs = f"Ich habe Ihre öffentlichen Informationen zu {cats_hint or company} gesehen und wollte mich kurz melden."
        touch1 = (
            f"Guten Tag,\n\n"
            f"{obs}\n"
            f"Wir bei {s_comp} entwickeln {product} — {val or 'um manuelle Arbeitsschritte im laufenden Betrieb zu reduzieren'}.\n\n"
            f"Falls das Thema dieses Quartal keine Priorität hat, ignorieren Sie diese Nachricht gern. "
            f"Andernfalls sende ich Ihnen gern vorab eine 1-seitige Übersicht mit relevanten Praxisbeispielen.\n\n"
            f"Freundliche Grüße\n{sign}"
        )
        touch2 = (
            f"Guten Tag,\n\n"
            f"kurzer Nachtrag: {proof or 'technische Spezifikationen und Sicherheitsnachweise liegen als 1-Pager vor.'}\n"
            f"Sollte jemand anderes im Team dafür zuständig sein, freue ich mich über einen kurzen Hinweis.\n\n"
            f"Freundliche Grüße\n{sign}"
        )
    elif lang == "ko":
        subj = f"{company} {cats_hint or '현업 운영'} 관련 짧은 확인"
        obs = f"{company}의 {cats_hint or '공개 자료'}를 보고 짧게 연락드립니다."
        touch1 = (
            f"{company} 담당자님, 안녕하세요. {s_comp} {s_name}입니다.\n\n"
            f"{obs}\n"
            f"저희는 {product}를 만들고 있고, {val or '비슷한 팀의 반복 운영 공수를 줄이는 일을 돕고 있습니다'}.\n\n"
            f"지금 보시는 과제가 아니면 편하게 패스하셔도 되고, 참고만 필요하시면 짧은 1장 요약 보내드릴까요?\n\n"
            f"감사합니다.\n{sign}"
        )
        touch2 = (
            f"{company} 담당자님, 지난 메일에 한 줄만 덧붙입니다.\n"
            f"{proof or '기존 환경 기준 적용 체크리스트 1장만 부담 없이 보내드릴 수 있습니다.'}\n"
            f"혹시 이 영역 담당자분이 따로 계시면 안내 부탁드립니다.\n\n감사합니다.\n{sign}"
        )
    else:
        subj = f"{company} / quick question on {cats_hint or 'operations'}".lower()
        obs = f"Came across {company}'s work in {cats_hint or country} and wanted to send a quick note."
        touch1 = (
            f"Hi {company} team,\n\n"
            f"{obs}\n"
            f"We build {product} — {val or 'helping similar teams cut manual operational overhead'}.\n\n"
            f"If this isn't on your radar this quarter, totally fine to skip — otherwise happy to send a short 1-page overview.\n\n"
            f"Best,\n{sign}"
        )
        touch2 = (
            f"Hi {company} team,\n\n"
            f"Adding one quick detail: {proof or 'we have a 1-page spec and security/compliance summary ready to share.'}\n"
            f"If someone else at {company} owns this area, I'd appreciate a quick pointer.\n\n"
            f"Best,\n{sign}"
        )

    qa1 = copy_guard.lint_copy(touch1, subject=subj, language=lang if lang in ("ko", "en", "ja") else "en", channel="email", touch_number=1)
    return {
        "locale": lang,
        "subject": subj,
        "touch_1": touch1,
        "touch_2": touch2,
        "qa_touch_1": qa1,
        "partner_checklist": [
            "현장 실무 오너 및 최종 의사결정자(VP/Head/Director/Plant Manager) LinkedIn 확인",
            "현재 사용 중인 기존 솔루션/장비 및 연동·보안·규제 요건(SOC2/GDPR/ISO/FDA 등)",
            "초기 PoC/파일럿 범위와 예산 집행 분기 확인",
        ],
    }


def draft_distributor_sequence(
    cand: dict[str, Any],
    profile: dict[str, Any],
    *,
    locale: str = "auto",
) -> dict[str, Any]:
    """Generate native (non-translated) 2-touch distributor outreach copy + checklist."""
    lang = _default_locale_for_country(cand.get("country", "")) if locale == "auto" else locale.lower()
    company = cand.get("company") or "Partner"
    country = cand.get("country") or "your market"
    product = (profile.get("product") or "our product line").strip()
    val = (profile.get("value_proposition") or "").strip()
    proof = (profile.get("proof_points") or "").strip()
    s_name = (profile.get("sender_name") or "[Name]").strip()
    s_comp = (profile.get("sender_company") or "[Company]").strip()
    s_contact = (profile.get("sender_contact") or "").strip()
    sign = " · ".join(x for x in (s_name, s_comp, s_contact) if x)
    brands_hint = ", ".join((cand.get("brands_carried") or [])[:2])
    cats_hint = ", ".join((cand.get("categories") or [])[:2])

    if lang == "ja":
        subj = f"{company}様 取扱製品・日本代理店のご相談"
        obs = f"御社が{brands_hint or cats_hint or '関連分野'}を取り扱われているのを拝見し、ご連絡いたしました。"
        touch1 = (
            f"{company} ご担当者様\n\n"
            f"初めてご連絡いたします。{s_comp}の{s_name}と申します。\n"
            f"{obs}\n"
            f"弊社は韓国にて{product}を製造・供給しており、{val or '日本市場向けのパートナー様を探しております'}。\n\n"
            f"今期の新規ライン追加のご予定がなければそのままお読み流しください。\n"
            f"ご関心があれば、製品仕様書と認証・MOQ概要（1ページ）を先にお送りしてもよろしいでしょうか。\n\n"
            f"よろしくお願いいたします。\n{sign}"
        )
        touch2 = (
            f"{company} ご担当者様\n\n"
            f"先日のメールに1点だけ補足いたします。{proof or 'サンプル出荷および日本語仕様書のご提供が可能です。'}\n"
            f"もし輸入・仕入れのご担当部署が別でしたら、窓口のみご教示いただけますと幸いです。\n\n"
            f"よろしくお願いいたします。\n{sign}"
        )
    elif lang == "de":
        subj = f"Vertriebspartnerschaft / {s_comp} ({country})"
        obs = f"Ich habe gesehen, dass {company} im Bereich {brands_hint or cats_hint or 'dieser Kategorie'} aktiv ist."
        touch1 = (
            f"Guten Tag,\n\n"
            f"{obs}\n"
            f"Wir bei {s_comp} entwickeln {product} und suchen einen verlässlichen B2B-Vertriebspartner für {country}.\n\n"
            f"Falls Sie aktuell keine neuen Linien aufnehmen, ignorieren Sie diese Nachricht gern. "
            f"Andernfalls sende ich Ihnen gern vorab ein 1-seitiges Datenblatt (Zertifizierungen, MOQ, Konditionen).\n\n"
            f"Freundliche Grüße\n{sign}"
        )
        touch2 = (
            f"Guten Tag,\n\n"
            f"kurzer Nachtrag: {proof or 'Muster und technische Unterlagen sind kurzfristig verfügbar.'}\n"
            f"Sollte jemand anderes im Einkauf zuständig sein, freue ich mich über einen kurzen Hinweis.\n\n"
            f"Freundliche Grüße\n{sign}"
        )
    elif lang == "ko":
        subj = f"{company} {country} 현지 유통·대리점 확인"
        obs = f"{company}에서 {brands_hint or cats_hint or '관련 품목'}을 유통하시는 내용을 보고 짧게 연락드립니다."
        touch1 = (
            f"{company} 담당자님, 안녕하세요. {s_comp} {s_name}입니다.\n\n"
            f"{obs}\n"
            f"저희는 {product}를 공급하고 있으며, {country} 지역 파트너를 찾고 있습니다.\n\n"
            f"지금 신규 라인을 보고 계시지 않으면 패스하셔도 되고, 스펙·인증·MOQ 1장 요약만 먼저 보내드릴까요?\n\n"
            f"감사합니다.\n{sign}"
        )
        touch2 = (
            f"{company} 담당자님, 지난 메일에 한 줄만 덧붙입니다.\n"
            f"{proof or '테스트 샘플과 파트너 단가표를 바로 공유드릴 수 있습니다.'}\n"
            f"혹시 소싱 담당자분이 따로 계시면 안내 부탁드립니다.\n\n감사합니다.\n{sign}"
        )
    else:
        subj = f"{company} / {country} distribution inquiry".lower()
        obs = (
            f"Saw that {company} carries {brands_hint} in {country}."
            if brands_hint
            else f"Saw {company}'s catalog in {cats_hint or 'this category'} for {country}."
        )
        touch1 = (
            f"Hi {company} team,\n\n"
            f"{obs}\n"
            f"We manufacture {product} in Korea and are looking for a local distributor in {country}.\n\n"
            f"If you're not adding new lines this quarter, no worries at all — otherwise happy to send a 1-page spec, certification, and MOQ sheet.\n\n"
            f"Best,\n{sign}"
        )
        touch2 = (
            f"Hi {company} team,\n\n"
            f"Quick note on my earlier email: {proof or 'samples and partner margin tiers are ready to share.'}\n"
            f"If someone else handles new product sourcing at {company}, I'd appreciate a quick pointer.\n\n"
            f"Best,\n{sign}"
        )

    qa1 = copy_guard.lint_copy(touch1, subject=subj, language=lang if lang in ("ko", "en", "ja") else "en", channel="email", touch_number=1)
    return {
        "locale": lang,
        "subject": subj,
        "touch_1": touch1,
        "touch_2": touch2,
        "qa_touch_1": qa1,
        "partner_checklist": [
            "취급 카테고리 중복 및 기존 경쟁 브랜드 독점 조항(Exclusivity) 여부",
            "목표 국가 필수 인허가/인증(CE/FDA/PMDA/KC 등) 수입자 명의 보유 여부",
            "초기 MOQ, 파트너 마진 구조, A/S·현지 재고 대응 가능 여부",
        ],
    }


def export_distributors_to_vault(items: list[dict[str, Any]], vault_dir: str | Path, *, mode: str = "end_user") -> dict[str, Any]:
    vroot = Path(vault_dir).expanduser().absolute()
    folder_name = "Overseas-B2B" if mode == "end_user" else "Distributors"
    d_dir = vroot / folder_name
    c_dir = d_dir / "Candidates"
    c_dir.mkdir(parents=True, exist_ok=True)

    rows_md: list[str] = []
    for item in items:
        cand = item["candidate"]
        sc = item["score"]
        seq = item["outreach"]
        slug = re.sub(r'[\\/:*?"<>|\s]+', "-", f"{cand['country']}-{cand['company']}").strip("-")[:70]
        note_path = c_dir / f"{slug}.md"
        bd = sc["breakdown"]
        bd_summary = (
            f"도메인 {bd['usecase_fit']}/35 · 국가 {bd['country_fit']}/20 · 규모/스택 {bd['scale_tech_readiness']}/30 · 타이밍 {bd['timing_signal']}/15"
            if mode == "end_user"
            else f"품목 {bd['category_fit']}/35 · 국가 {bd['country_fit']}/25 · 유통/포트폴리오 {bd['channel_portfolio']}/25 · 인증/인프라 {bd['cert_infra']}/15"
        )
        checklist_title = "엔드유저 도입 확인 체크리스트" if mode == "end_user" else "대리점 파트너 확인 체크리스트"
        md = (
            f"---\n"
            f'company: "{cand["company"]}"\n'
            f'country: "{cand["country"]}"\n'
            f'mode: "{mode}"\n'
            f'tier: "{sc["tier"]}"\n'
            f'score: {sc["total"]}\n'
            f'locale: "{seq["locale"]}"\n'
            f'status: "발굴"\n'
            f"automatic_send: false\n"
            f"---\n\n"
            f"# {cand['company']} ({cand['country']})\n\n"
            f"- **영업 유형**: `{'해외 B2B 엔드유저 직접 영업' if mode == 'end_user' else '해외 대리점·총판 개척'}`\n"
            f"- **웹사이트**: {cand['website'] or '미확인'}\n"
            f"- **공개 대표 메일**: {cand['public_contact_email'] or '미확인'}\n"
            f"- **출처**: {cand['source_url']}\n"
            f"- **적합 점수**: **{sc['total']}점** ({sc['tier']}) — {bd_summary}\n"
            f"- **분석 메모**: {'; '.join(sc['notes'])}\n\n"
            f"## 1차 제안 초안 (`{seq['locale']}` · QA {seq['qa_touch_1']['score']}점)\n"
            f"**Subject**: `{seq['subject']}`\n\n"
            f"```text\n{seq['touch_1']}\n```\n\n"
            f"## 2차 팔로업 (Day +5)\n"
            f"```text\n{seq['touch_2']}\n```\n\n"
            f"## {checklist_title}\n"
            + "\n".join(f"- [ ] {x}" for x in seq["partner_checklist"])
            + "\n"
        )
        note_path.write_text(md, encoding="utf-8")
        rows_md.append(
            f"| [[{folder_name}/Candidates/{slug}\\|{cand['company']}]] | {cand['country']} | {sc['tier']} ({sc['total']}) | "
            f"`{seq['locale']}` | {cand['website'] or '—'} |"
        )

    title_md = (
        "# Overseas Direct B2B End-User Pipeline" if mode == "end_user"
        else "# Overseas Distributors & Importers Pipeline"
    )
    pipeline_md = (
        f"{title_md}\n\n"
        "> 자동 발송 없음 — 후보별 근거와 의사결정자를 확인한 뒤 발송하세요.\n\n"
        "| 타깃 기업 | 국가 | 등급(점수) | 초안 언어 | 웹사이트 |\n"
        "|---|---|---|---|---|\n"
        + ("\n".join(rows_md) if rows_md else "| (후보 없음) | — | — | — | — |")
        + "\n"
    )
    pipe_path = d_dir / "Pipeline.md"
    pipe_path.write_text(pipeline_md, encoding="utf-8")
    return {"pipeline": str(pipe_path), "candidates_written": len(items)}


def build_linkedin_handoff(items: list[dict[str, Any]], config: dict[str, Any], *, top: int = 20) -> dict[str, Any]:
    """Generate a LinkedIn ICP + Apify People handoff payload for the top discovered overseas accounts."""
    import linkedin_outbound
    companies = [item["candidate"]["company"] for item in items[:top] if item["candidate"].get("company")]
    icp = linkedin_outbound.build_linkedin_icp(config, companies=companies)
    return {
        "target_companies": companies,
        "xray": linkedin_outbound.generate_xray_queries(icp),
        "apify_people_input": linkedin_outbound.build_apify_actor_inputs(icp)["people_actor_input"],
    }


def run_distributor_pipeline(
    config: dict[str, Any],
    *,
    mode: str = "end_user",
    distributor_urls: list[str] | None = None,
    exhibitors_file: str | Path | None = None,
    target_countries: list[str] | None = None,
    competitor_brands: list[str] | None = None,
    required_certs: list[str] | None = None,
    locale: str = "auto",
    home: str | Path | None = None,
    vault: str | Path | None = None,
    opener=None,
) -> dict[str, Any]:
    if mode not in ("end_user", "distributor"):
        raise ValueError(f"mode는 'end_user' 또는 'distributor'여야 합니다: {mode!r}")

    candidates: list[dict[str, Any]] = []
    errors: list[str] = []

    if distributor_urls:
        fetched, errs = fetch_distributor_pages(
            distributor_urls,
            target_countries=target_countries,
            competitor_brand=(competitor_brands or [""])[0],
            opener=opener,
        )
        candidates.extend(fetched)
        errors.extend(errs)
    if exhibitors_file:
        candidates.extend(import_distributors_file(exhibitors_file, target_countries=target_countries))

    dnc_keys = {sources._norm_company_key(x) for x in (config.get("do_not_contact") or []) if isinstance(x, str)}
    if home:
        dnc_f = Path(home).expanduser().absolute() / "do-not-contact.txt"
        if dnc_f.is_file():
            for line in dnc_f.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    dnc_keys.add(sources._norm_company_key(s))

    prod_kw = profile_presets.split_terms(config.get("keywords")) + profile_presets.split_terms(config.get("product"))
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    skipped_dnc: list[str] = []
    for cand in candidates:
        if cand["company_key"] in seen:
            continue
        seen.add(cand["company_key"])
        if cand["company_key"] in dnc_keys:
            skipped_dnc.append(cand["company"])
            continue
        if mode == "end_user":
            sc = score_end_user(
                cand,
                product_keywords=prod_kw,
                target_countries=target_countries,
                competitor_brands=competitor_brands,
                required_certs=required_certs,
            )
            seq = draft_end_user_sequence(cand, config, locale=locale)
        else:
            sc = score_distributor(
                cand,
                product_keywords=prod_kw,
                target_countries=target_countries,
                competitor_brands=competitor_brands,
                required_certs=required_certs,
            )
            seq = draft_distributor_sequence(cand, config, locale=locale)
        items.append({"candidate": cand, "score": sc, "outreach": seq})

    items.sort(key=lambda x: x["score"]["total"], reverse=True)
    vault_out = export_distributors_to_vault(items, vault, mode=mode) if vault else None
    li_handoff = build_linkedin_handoff(items, config) if items else None

    return {
        "schema_version": "hermes_overseas_outbound/v1",
        "mode": mode,
        "candidates_count": len(items),
        "skipped_dnc": skipped_dnc,
        "errors": errors,
        "items": items,
        "linkedin_handoff": li_handoff,
        "vault": vault_out,
        "automatic_send": False,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="해외 B2B 엔드유저 직접 영업 & 대리점·총판 발굴 및 현지어 제안 생성기")
    ap.add_argument("--mode", default="end_user", choices=("end_user", "distributor"),
                    help="end_user(해외 최종 도입 기업 직접 영업, 기본값) 또는 distributor(해외 대리점·총판·수입상)")
    ap.add_argument("--config", default=str(ROOT / "setup.json"))
    ap.add_argument("--distributor-url", "--target-url", dest="distributor_url", action="append", default=[],
                    help="전시회 참가사 / 업종 디렉터리 / 경쟁사 고객사·Distributors 공개 URL")
    ap.add_argument("--exhibitors-file", "--file", dest="exhibitors_file",
                    help="해외 기업·전시회 참가사·수입상 CSV 또는 JSON")
    ap.add_argument("--country", action="append", default=[], help="목표 국가 코드 (예: US, DE, JP, SG, VN)")
    ap.add_argument("--competitor-brand", action="append", default=[], help="경쟁/유사 브랜드명")
    ap.add_argument("--cert", action="append", default=[], help="우대 인증/인프라 (예: CE, FDA, SOC2, ISO13485)")
    ap.add_argument("--locale", default="auto", choices=("auto", "en", "ja", "de", "ko"))
    ap.add_argument("--home")
    ap.add_argument("--vault")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not (args.distributor_url or args.exhibitors_file):
        ap.error("--target-url(--distributor-url) 또는 --file(--exhibitors-file) 중 하나 이상을 지정하세요.")

    cfg: dict[str, Any] = {}
    cfg_p = Path(args.config).expanduser()
    if cfg_p.is_file():
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))

    try:
        res = run_distributor_pipeline(
            cfg,
            mode=args.mode,
            distributor_urls=args.distributor_url,
            exhibitors_file=args.exhibitors_file,
            target_countries=args.country,
            competitor_brands=args.competitor_brand,
            required_certs=args.cert,
            locale=args.locale,
            home=paths.normalize_home(args.home),
            vault=args.vault,
        )
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            label = "해외 B2B 엔드유저" if args.mode == "end_user" else "해외 대리점"
            print(f"{label} 발굴 완료: {res['candidates_count']}건 (DNC 제외 {len(res['skipped_dnc'])}건)")
            if res["vault"]:
                print(f"Obsidian 파이프라인: {res['vault']['pipeline']}")
            for item in res["items"][:5]:
                c, sc, seq = item["candidate"], item["score"], item["outreach"]
                print(f"\n[{sc['tier']} {sc['total']}점] {c['company']} ({c['country']}) · lang={seq['locale']}")
                print(f"  Subject: {seq['subject']}")
                print(f"  Notes: {'; '.join(sc['notes'])}")
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
