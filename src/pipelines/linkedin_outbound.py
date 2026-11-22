#!/usr/bin/env python3
"""linkedin_outbound.py — ICP definition -> Apify LinkedIn Company & Decision-Maker sourcing -> warming & DM sequence.

Zero external dependencies (Python 3.11+ stdlib).
Never bypasses logins/cookies or auto-sends messages.
Supports:
1. Structured LinkedIn ICP definition & Boolean X-Ray query generation
2. Managed Apify Actor execution (official REST API with APIFY_TOKEN, item/budget caps, and user ack)
   for LinkedIn Company search + Decision-Maker (People) sourcing, plus offline Apify JSON / Sales Nav CSV import
3. Company-to-contact matching, ICP fit scoring, and DNC filtering
4. GTMOS linkedin-warm 3-7 day warming plans (view -> like -> 1-line comment) + strict <=300-char connection notes
   + 1st-degree DM + follow-up sequences validated by copy_guard.py
5. Obsidian Vault export (vault/LinkedIn/Queue.md + vault/LinkedIn/Contacts/<company>-<name>.md)
"""
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import csv
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import copy_guard  # noqa: E402
import paths  # noqa: E402
import profile_presets  # noqa: E402
import sources  # noqa: E402

APIFY_API_BASE = "https://api.apify.com/v2"
USER_AGENT = "hermes-outbound-kit/0.2 (+https://github.com/Wendy-Nam/hermes-outbound-kit)"

DEFAULT_SENIORITY_ROLES = [
    "VP", "Head of", "Director", "Lead", "Manager", "CTO", "CISO", "CFO", "COO", "CEO",
    "팀장", "실장", "본부장", "대표", "이사", "리드",
]


def resolve_apify_token(home: str | Path | None = None) -> str:
    """Read APIFY_TOKEN from process env or $HERMES_HOME/.env (never from setup.json)."""
    val = os.environ.get("APIFY_TOKEN", "").strip()
    if val:
        return val
    candidates = []
    if home:
        candidates.append(Path(home).expanduser().absolute() / ".env")
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        candidates.append(Path(env_home).expanduser().absolute() / ".env")
    for env_file in candidates:
        if not env_file.is_file() or env_file.is_symlink():
            continue
        try:
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                if k.strip() == "APIFY_TOKEN":
                    cleaned = v.strip().strip('"').strip("'")
                    if cleaned:
                        return cleaned
        except OSError:
            continue
    return ""


# ---------------------------------------------------------------------------
# 1. ICP Definition & LinkedIn X-Ray / Apify Input Builder
# ---------------------------------------------------------------------------

def build_linkedin_icp(
    config: dict[str, Any] | None = None,
    *,
    roles: list[str] | None = None,
    industries: list[str] | None = None,
    locations: list[str] | None = None,
    companies: list[str] | None = None,
    keywords: list[str] | None = None,
    exclude_titles: list[str] | None = None,
    min_employees: int = 20,
    max_employees: int = 2000,
) -> dict[str, Any]:
    """Compile a clean LinkedIn ICP spec from setup.json or CLI flags."""
    cfg = config or {}
    sp = cfg.get("scoring_profile") if isinstance(cfg.get("scoring_profile"), dict) else {}

    role_list = roles or profile_presets.split_terms(cfg.get("job_keywords")) or ["Head of Data", "VP Engineering", "CTO"]
    ind_list = industries or (sp.get("industry_tiers") or {}).get("high") or profile_presets.split_terms(cfg.get("keywords")) or ["SaaS", "AI"]
    loc_list = locations or profile_presets.split_terms(cfg.get("region")) or ["South Korea", "Seoul"]
    kw_list = keywords or profile_presets.split_terms(cfg.get("keywords"))[:8]
    excl_list = exclude_titles or profile_presets.split_terms(cfg.get("exclude_keywords")) or ["Intern", "인턴", "Student", "Freelance"]
    comp_list = [c.strip() for c in (companies or []) if c and c.strip()]

    return {
        "schema_version": "hermes_linkedin_icp/v1",
        "roles": role_list[:12],
        "industries": ind_list[:10],
        "locations": loc_list[:8],
        "target_companies": comp_list[:50],
        "keywords": kw_list[:10],
        "exclude_titles": excl_list[:10],
        "employee_range": {"min": int(min_employees), "max": int(max_employees)},
        "product": (cfg.get("product") or "").strip(),
        "customer": (cfg.get("customer") or "").strip(),
    }


def _bool_or(terms: list[str], limit: int = 6) -> str:
    cleaned = [f'"{t}"' if " " in t else t for t in terms[:limit] if t.strip()]
    return "(" + " OR ".join(cleaned) + ")" if cleaned else ""


def generate_xray_queries(icp: dict[str, Any]) -> dict[str, Any]:
    """Generate Boolean X-Ray search strings (Google/Bing) and Sales Navigator filter guidance."""
    role_q = _bool_or(icp.get("roles") or [], 6)
    ind_q = _bool_or(icp.get("industries") or [], 5)
    loc_q = _bool_or(icp.get("locations") or [], 4)
    comp_q = _bool_or(icp.get("target_companies") or [], 6)
    excl_q = " ".join(f'-"{x}"' if " " in x else f"-{x}" for x in (icp.get("exclude_titles") or [])[:5])

    company_parts = ["site:linkedin.com/company", ind_q, loc_q]
    people_parts = ["site:linkedin.com/in", role_q, comp_q or ind_q, loc_q, excl_q]

    company_query = " ".join(p for p in company_parts if p).strip()
    people_query = " ".join(p for p in people_parts if p).strip()

    per_company_queries = [
        {
            "company": comp,
            "people_xray": " ".join(
                p for p in ("site:linkedin.com/in", f'"{comp}"', role_q, excl_q) if p
            ),
        }
        for comp in (icp.get("target_companies") or [])[:15]
    ]

    return {
        "company_xray": company_query,
        "people_xray": people_query,
        "per_company_people_xray": per_company_queries,
        "sales_navigator_filters": {
            "job_titles": icp.get("roles") or [],
            "industries": icp.get("industries") or [],
            "geography": icp.get("locations") or [],
            "company_headcount": f"{icp['employee_range']['min']}~{icp['employee_range']['max']}",
            "exclude_titles": icp.get("exclude_titles") or [],
        },
    }


def build_apify_actor_inputs(
    icp: dict[str, Any],
    *,
    max_companies: int = 25,
    max_people: int = 50,
    company_urls: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build standard input payloads for Apify LinkedIn Company & People Actors."""
    queries = generate_xray_queries(icp)
    emp = icp.get("employee_range") or {"min": 20, "max": 2000}
    company_input = {
        "searchQueries": [queries["company_xray"]],
        "keywords": icp.get("industries") or icp.get("keywords") or [],
        "locations": icp.get("locations") or [],
        "minEmployees": emp.get("min", 20),
        "maxEmployees": emp.get("max", 2000),
        "maxItems": max(1, min(200, int(max_companies))),
    }
    people_input: dict[str, Any] = {
        "searchQueries": [queries["people_xray"]],
        "jobTitles": icp.get("roles") or [],
        "locations": icp.get("locations") or [],
        "excludeTitles": icp.get("exclude_titles") or [],
        "maxItems": max(1, min(200, int(max_people))),
    }
    if company_urls:
        people_input["companyUrls"] = company_urls[:50]
    elif icp.get("target_companies"):
        people_input["companies"] = icp["target_companies"][:50]
    return {"company_actor_input": company_input, "people_actor_input": people_input}


# ---------------------------------------------------------------------------
# 2. Managed Apify Actor Runner (Official REST API, Budget/Limit Guarded)
# ---------------------------------------------------------------------------

def _normalize_actor_id(actor_id: str) -> str:
    cleaned = (actor_id or "").strip().strip("/")
    if not cleaned or not re.fullmatch(r"[A-Za-z0-9._-]+(?:/|~)[A-Za-z0-9._-]+", cleaned):
        raise ValueError(
            f"Apify Actor ID 형식이 올바르지 않습니다: {actor_id!r} (예: owner/actor-name 또는 owner~actor-name)"
        )
    return cleaned.replace("/", "~", 1)


def run_apify_actor(
    actor_id: str,
    actor_input: dict[str, Any],
    *,
    token: str,
    max_items: int = 50,
    timeout: int = 120,
    opener=None,
) -> list[dict[str, Any]]:
    """Execute a user-approved Apify Actor via official run-sync-get-dataset-items endpoint."""
    if not token:
        raise ValueError("APIFY_TOKEN이 없습니다. $HERMES_HOME/.env에 APIFY_TOKEN을 설정하세요.")
    norm_id = _normalize_actor_id(actor_id)
    cap = max(1, min(200, int(max_items)))
    query = urllib.parse.urlencode({"clean": "true", "limit": cap, "format": "json"})
    url = f"{APIFY_API_BASE}/acts/{urllib.parse.quote(norm_id, safe='~')}/run-sync-get-dataset-items?{query}"
    body = json.dumps(actor_input, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    client = opener or urllib.request.build_opener()
    try:
        with client.open(req, timeout=timeout) as resp:
            raw = resp.read(16 * 1024 * 1024).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError(f"Apify 인증 실패(HTTP {exc.code}): APIFY_TOKEN 권한을 확인하세요.") from None
        if exc.code == 402:
            raise ValueError("Apify 크레딧/예산 한도 초과(HTTP 402).") from None
        raise ValueError(f"Apify Actor 실행 실패(HTTP {exc.code}).") from None
    except urllib.error.URLError as exc:
        raise ValueError(f"Apify 네트워크 연결 실패: {exc.reason}") from None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Apify 응답 JSON 파싱 실패: {exc.msg}") from None
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list):
        raise ValueError("Apify dataset 응답이 배열 형식이 아닙니다.")
    return [item for item in data if isinstance(item, dict)][:cap]


# ---------------------------------------------------------------------------
# 3. Normalizers (Apify Company/People JSON & Sales Navigator CSV)
# ---------------------------------------------------------------------------

def _pick(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return sources.clean_text(v)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


def normalize_apify_companies(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize heterogeneous Apify LinkedIn Company Actor outputs."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = _pick(raw, "companyName", "name", "company", "organizationName", "title")
        if not name:
            continue
        key = sources._norm_company_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        emp = raw.get("employeeCount") or raw.get("staffCount") or raw.get("employees") or raw.get("companySize") or ""
        desc = _pick(raw, "description", "tagline", "about", "summary")
        ind = _pick(raw, "industry", "industryName", "sector")
        if isinstance(raw.get("industries"), list):
            ind = ", ".join(str(x) for x in raw["industries"] if x) or ind
        out.append({
            "company": name[:200],
            "company_key": key,
            "industry": ind[:200],
            "employees": str(emp)[:60],
            "location": _pick(raw, "location", "headquarter", "hqLocation", "country", "city")[:200],
            "website": _pick(raw, "website", "websiteUrl", "companyWebsite", "url")[:300],
            "linkedin_url": _pick(raw, "linkedinUrl", "companyUrl", "profileUrl", "url")[:300],
            "description": desc[:1000],
            "stack": sources.extract_tech_stack(f"{desc} {ind}") or [],
            "source": "apify-linkedin-company",
        })
    return out


def normalize_linkedin_contacts(
    items: list[dict[str, Any]],
    *,
    companies_index: dict[str, dict[str, Any]] | None = None,
    source_name: str = "apify-linkedin-people",
) -> list[dict[str, Any]]:
    """Normalize Apify LinkedIn People items or Sales Navigator CSV rows into unified contact records."""
    c_idx = companies_index or {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        first = _pick(raw, "firstName", "first_name", "First Name")
        last = _pick(raw, "lastName", "last_name", "Last Name")
        full = _pick(raw, "fullName", "full_name", "Full Name", "name", "Name") or f"{first} {last}".strip()
        company = _pick(raw, "companyName", "company", "Company", "Company Name", "currentCompany", "organization")
        title = _pick(raw, "jobTitle", "title", "Title", "Position", "headline", "Headline", "role")
        li_url = _pick(raw, "linkedinUrl", "profileUrl", "LinkedIn URL", "Profile URL", "url", "publicIdentifier")
        if li_url and not li_url.startswith("http") and "/" not in li_url:
            li_url = f"https://www.linkedin.com/in/{li_url}"
        if not (full or company):
            continue
        dedupe_key = (li_url.casefold() if li_url else f"{sources._norm_company_key(company)}|{full.casefold()}")
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        ckey = sources._norm_company_key(company)
        comp_meta = c_idx.get(ckey, {})
        recent_post = _pick(raw, "recentPost", "recent_post", "Recent Post", "lastPost", "activity", "Activity")
        if not recent_post and isinstance(raw.get("posts"), list) and raw["posts"]:
            p0 = raw["posts"][0]
            recent_post = sources.clean_text(p0.get("text") or p0.get("title") or "") if isinstance(p0, dict) else str(p0)

        out.append({
            "name": full[:120] or "담당자",
            "title": title[:200],
            "company": (company or comp_meta.get("company") or "미확인")[:200],
            "company_key": ckey,
            "industry": _pick(raw, "industry", "Industry") or comp_meta.get("industry", ""),
            "employees": _pick(raw, "employees", "Company Size") or comp_meta.get("employees", ""),
            "location": _pick(raw, "location", "Location", "Geography") or comp_meta.get("location", ""),
            "linkedin_url": li_url[:300],
            "company_website": _pick(raw, "website", "Company Website") or comp_meta.get("website", ""),
            "recent_post": recent_post[:400],
            "activity_active": bool(recent_post) or str(raw.get("active") or raw.get("Active") or "").lower() in ("true", "1", "yes"),
            "mutual_connections": _pick(raw, "mutualConnections", "Mutual Connections", "mutual")[:80],
            "source": source_name,
        })
    return out


def load_linkedin_file(path: str | Path, *, companies_index: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Load Sales Navigator CSV or Apify JSON dataset export."""
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"읽을 수 있는 일반 파일이 아닙니다: {path}")
    if target.suffix.lower() == ".json":
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        rows = raw.get("items", raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise ValueError("JSON 입력은 연락처 배열이어야 합니다.")
        return normalize_linkedin_contacts(rows, companies_index=companies_index, source_name="linkedin-json-import")
    with target.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return normalize_linkedin_contacts(rows, companies_index=companies_index, source_name="sales-nav-csv-import")


# ---------------------------------------------------------------------------
# 4. ICP Contact Scoring + GTMOS Warming & Multi-Touch LinkedIn Sequence
# ---------------------------------------------------------------------------

def score_linkedin_contact(contact: dict[str, Any], icp: dict[str, Any]) -> dict[str, Any]:
    """Score a LinkedIn decision-maker against ICP (0..100) + exclude-title guard."""
    title_low = (contact.get("title") or "").casefold()
    blob = " ".join(str(contact.get(k) or "") for k in ("company", "title", "industry", "location", "recent_post")).casefold()

    for excl in icp.get("exclude_titles") or []:
        if excl.strip() and excl.casefold() in title_low:
            return {"score": 0, "tier": "제외", "reasons": [f"제외 직함 일치({excl})"]}

    score = 0
    reasons: list[str] = []

    role_hits = [r for r in (icp.get("roles") or []) if r.strip() and r.casefold() in title_low]
    if role_hits:
        score += 45
        reasons.append(f"타깃 직함 일치({', '.join(role_hits[:2])})")
    elif any(s.casefold() in title_low for s in DEFAULT_SENIORITY_ROLES):
        score += 22
        reasons.append("의사결정/리드급 직함")

    ind_hits = [i for i in (icp.get("industries") or []) if i.strip() and i.casefold() in blob]
    if ind_hits:
        score += 25
        reasons.append(f"업종/키워드 일치({', '.join(ind_hits[:2])})")

    loc_hits = [l for l in (icp.get("locations") or []) if l.strip() and l.casefold() in blob]
    if loc_hits:
        score += 15
        reasons.append(f"지역 일치({loc_hits[0]})")

    if contact.get("activity_active"):
        score += 15
        reasons.append("최근 LinkedIn 활동 확인(워밍업 가능)")

    score = min(100, score)
    tier = "최우선(A)" if score >= 70 else ("우선(B)" if score >= 45 else "보류(C)")
    return {"score": score, "tier": tier, "reasons": reasons or ["기본 후보"]}


def build_linkedin_plan(
    contact: dict[str, Any],
    profile: dict[str, Any],
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Create GTMOS linkedin-warm plan + <=300-char connection request + 1st-degree DM + follow-up."""
    lang = (language or profile.get("draft_language") or "ko").lower()
    name = contact.get("name") or "담당자"
    company = contact.get("company") or "팀"
    title = contact.get("title") or ""
    post = (contact.get("recent_post") or "").strip()
    active = bool(contact.get("activity_active"))

    product = (profile.get("product") or "[제품 한 줄]").strip()
    val = (profile.get("value_proposition") or "").strip()
    s_name = (profile.get("sender_name") or "[이름]").strip()
    s_comp = (profile.get("sender_company") or "[회사]").strip()

    if active:
        warming = [
            {"day": 0, "action": "프로필 조회", "note": "LinkedIn 프로필 확인 (최근 포스트·업무 맥락 체크)"},
            {"day": 2, "action": "최근 글 반응(좋아요)", "note": f"최근 글 확인: {post[:80] or '최신 포스트 1건'}"},
            {"day": 4, "action": "사실 기반 1줄 댓글(직접 작성)", "note": "영업 언급 금지 — 상대 글의 구체적 포인트 1가지만 공감/질문"},
            {"day": 6, "action": "연결 요청 발송 (300자 이내)", "note": "아래 연결 요청 초안 확인 후 발송"},
        ]
    else:
        warming = [
            {"day": 0, "action": "워밍업 생략 → 바로 연결 요청", "note": "최근 활동이 적어 연결 요청으로 바로 진입"},
        ]

    if lang == "en":
        obs = f"Saw your post on {post[:45]}." if post else f"Saw your work leading {title[:35] or 'the team'} at {company}."
        connect_note = f"Hi {name}, {obs} I'm {s_name} at {s_comp} ({product[:55]}). Would be glad to connect here."
        if len(connect_note) > 295:
            connect_note = connect_note[:292].rstrip() + "..."
        dm_1 = (
            f"Thanks for connecting, {name}.\n\n"
            f"{obs}\n"
            f"We build {product} — {val or 'helping similar teams cut manual overhead'}.\n\n"
            f"No pitch if timing isn't right; happy to send a 1-page note if helpful."
        )
        dm_2 = (
            f"Hi {name}, quick follow-up — if someone else at {company} handles this, happy to reach out to them instead. "
            f"Otherwise no worries at all."
        )
    else:
        obs = f"최근 올리신 「{post[:35]}」 글 잘 보았습니다." if post else f"{company}에서 {title[:24] or '관련 업무'} 맡고 계신 프로필 보고 인사드립니다."
        connect_note = f"{name}님 안녕하세요, {s_comp} {s_name}입니다. {obs} 같은 분야라 1촌 인사드리고 싶습니다."
        if len(connect_note) > 295:
            connect_note = connect_note[:292].rstrip() + "..."
        val_ko = val if val else f"{product}로 관련 실무를 돕고 있습니다"
        if not val_ko.endswith((".", "다", "요", "?")):
            val_ko += "."
        dm_1 = (
            f"{name}님, 1촌 수락 감사합니다. {s_comp} {s_name}입니다.\n\n"
            f"{obs}\n"
            f"저희는 {product}를 만들고 있고, {val_ko}\n\n"
            f"지금 보시는 시기가 아니면 편하게 넘어가셔도 되고, 참고만 필요하시면 짧은 자료 1장 보내드릴까요?"
        )
        dm_2 = (
            f"{name}님, 바쁘실 텐데 한 줄만 확인드립니다.\n"
            f"혹시 {company}에서 이 영역은 다른 분이 맡고 계실까요? 지금 우선순위가 아니시면 답장 안 주셔도 괜찮습니다."
        )

    qa_connect = copy_guard.lint_copy(connect_note, language=lang, channel="linkedin_connect")
    qa_dm1 = copy_guard.lint_copy(dm_1, language=lang, channel="linkedin")
    return {
        "warming_required": active,
        "warming_steps": warming,
        "connect_note": connect_note,
        "connect_chars": len(connect_note),
        "connect_qa": qa_connect,
        "dm_touch_1": dm_1,
        "dm_1_qa": qa_dm1,
        "dm_touch_2": dm_2,
        "connector_hint": "manual_review_or_crispy_mcp_optional",
        "automatic_send": False,
    }


def _safe_slug(text: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', " ", (text or "").strip())
    return re.sub(r"\s+", "-", cleaned)[:60] or "contact"


def export_linkedin_to_vault(
    results: list[dict[str, Any]],
    icp: dict[str, Any],
    xray: dict[str, Any],
    vault_dir: str | Path,
) -> dict[str, Any]:
    """Write Obsidian LinkedIn Queue.md and per-contact warming/DM notes."""
    vroot = Path(vault_dir).expanduser().absolute()
    li_dir = vroot / "LinkedIn"
    contacts_dir = li_dir / "Contacts"
    contacts_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    rows_md: list[str] = []
    for item in results:
        c = item["contact"]
        sc = item["score"]
        pl = item["plan"]
        slug = _safe_slug(f"{c['company']}-{c['name']}")
        note_path = contacts_dir / f"{slug}.md"
        warm_lines = "\n".join(
            f"- [ ] Day +{w['day']} · **{w['action']}**: {w['note']}"
            for w in pl["warming_steps"]
        )
        md = (
            f"---\n"
            f'name: "{c["name"]}"\n'
            f'company: "{c["company"]}"\n'
            f'title: "{c["title"]}"\n'
            f'tier: "{sc["tier"]}"\n'
            f'score: {sc["score"]}\n'
            f'warming: {"yes" if pl["warming_required"] else "skip"}\n'
            f'status: "대기"\n'
            f"automatic_send: false\n"
            f"---\n\n"
            f"# {c['name']} · {c['company']}\n\n"
            f"- **직함**: {c['title'] or '미확인'}\n"
            f"- **업종/지역**: {c['industry'] or '미확인'} · {c['location'] or '미확인'}\n"
            f"- **LinkedIn**: {c['linkedin_url'] or '미확인'}\n"
            f"- **ICP 점수**: {sc['score']}점 ({sc['tier']}) — {', '.join(sc['reasons'])}\n\n"
            f"## 1. 워밍업 체크리스트\n{warm_lines}\n\n"
            f"## 2. 연결 요청 메모 ({pl['connect_chars']}/300자 · QA {pl['connect_qa']['score']}점)\n"
            f"```text\n{pl['connect_note']}\n```\n\n"
            f"## 3. 1촌 수락 후 DM (QA {pl['dm_1_qa']['score']}점)\n"
            f"```text\n{pl['dm_touch_1']}\n```\n\n"
            f"## 4. 팔로업 DM (Day +5)\n"
            f"```text\n{pl['dm_touch_2']}\n```\n\n"
            f"---\n[발송 전 내 말로 바꿀 1줄 메모]\n- 상대 최근 글·프로필에서 직접 확인한 사실 1줄을 넣어 발송하세요.\n"
        )
        note_path.write_text(md, encoding="utf-8")
        written.append(str(note_path))
        rows_md.append(
            f"| [[LinkedIn/Contacts/{slug}\\|{c['name']}]] | {c['company']} | {c['title'][:30]} | "
            f"{sc['tier']} ({sc['score']}) | {'워밍업 3~6일' if pl['warming_required'] else '바로 연결요청'} |"
        )

    queue_md = (
        "# LinkedIn Outbound Queue\n\n"
        "> 자동 발송 없음 — 사람 검토 후 직접 발송하거나 승인된 외부 커넥터(Crispy 등)로 실행하세요.\n\n"
        "## Boolean X-Ray 검색 쿼리\n"
        f"- **타깃 회사 X-Ray**: `{xray['company_xray']}`\n"
        f"- **담당자 X-Ray**: `{xray['people_xray']}`\n\n"
        "## 대상자 큐\n"
        "| 담당자 | 회사 | 직함 | ICP 등급 | 전략 |\n"
        "|---|---|---|---|---|\n"
        + ("\n".join(rows_md) if rows_md else "| (후보 없음) | — | — | — | — |")
        + "\n"
    )
    queue_path = li_dir / "Queue.md"
    queue_path.write_text(queue_md, encoding="utf-8")
    return {"queue": str(queue_path), "notes_written": len(written)}


def run_linkedin_pipeline(
    config: dict[str, Any],
    *,
    home: str | Path | None = None,
    vault: str | Path | None = None,
    contacts_file: str | Path | None = None,
    companies_file: str | Path | None = None,
    apify_company_actor: str = "",
    apify_people_actor: str = "",
    max_companies: int = 20,
    max_people: int = 40,
    language: str | None = None,
    opener=None,
) -> dict[str, Any]:
    """Run ICP -> (Apify Company & People OR file import) -> Score/DNC -> Warming/DM -> Vault."""
    icp = build_linkedin_icp(config)
    xray = generate_xray_queries(icp)
    apify_inputs = build_apify_actor_inputs(icp, max_companies=max_companies, max_people=max_people)

    companies: list[dict[str, Any]] = []
    contacts: list[dict[str, Any]] = []
    source_log: list[str] = []

    if companies_file:
        raw_c = json.loads(Path(companies_file).expanduser().read_text(encoding="utf-8-sig"))
        companies = normalize_apify_companies(raw_c.get("items", raw_c) if isinstance(raw_c, dict) else raw_c)
        source_log.append(f"companies_file:{len(companies)}")

    if apify_company_actor or apify_people_actor:
        token = resolve_apify_token(home)
        if not token:
            raise ValueError("Apify 실행에는 APIFY_TOKEN이 필요합니다($HERMES_HOME/.env에 설정).")
        if apify_company_actor:
            raw_co = run_apify_actor(
                apify_company_actor,
                apify_inputs["company_actor_input"],
                token=token,
                max_items=max_companies,
                opener=opener,
            )
            companies = normalize_apify_companies(raw_co)
            source_log.append(f"apify_company:{apify_company_actor}:{len(companies)}")
        c_urls = [c["linkedin_url"] for c in companies if c.get("linkedin_url")]
        c_names = [c["company"] for c in companies if c.get("company")]
        if c_names:
            icp["target_companies"] = list(dict.fromkeys([*icp["target_companies"], *c_names]))[:50]
            apify_inputs = build_apify_actor_inputs(icp, max_companies=max_companies, max_people=max_people, company_urls=c_urls)
        if apify_people_actor:
            raw_pe = run_apify_actor(
                apify_people_actor,
                apify_inputs["people_actor_input"],
                token=token,
                max_items=max_people,
                opener=opener,
            )
            c_idx = {c["company_key"]: c for c in companies}
            contacts.extend(normalize_linkedin_contacts(raw_pe, companies_index=c_idx))
            source_log.append(f"apify_people:{apify_people_actor}:{len(raw_pe)}")

    c_idx = {c["company_key"]: c for c in companies}
    if contacts_file:
        imported = load_linkedin_file(contacts_file, companies_index=c_idx)
        contacts.extend(imported)
        source_log.append(f"contacts_file:{len(imported)}")

    # DNC filter (config + $HERMES_HOME/do-not-contact.txt)
    dnc_keys = {sources._norm_company_key(x) for x in (config.get("do_not_contact") or []) if isinstance(x, str)}
    if home:
        dnc_file = Path(home).expanduser().absolute() / "do-not-contact.txt"
        if dnc_file.is_file():
            for line in dnc_file.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    dnc_keys.add(sources._norm_company_key(s))

    kept: list[dict[str, Any]] = []
    skipped_dnc: list[str] = []
    for contact in contacts:
        if contact["company_key"] and contact["company_key"] in dnc_keys:
            skipped_dnc.append(contact["company"])
            continue
        sc = score_linkedin_contact(contact, icp)
        if sc["tier"] == "제외":
            continue
        plan = build_linkedin_plan(contact, config, language=language)
        kept.append({"contact": contact, "score": sc, "plan": plan})

    kept.sort(key=lambda item: item["score"]["score"], reverse=True)
    vault_out = export_linkedin_to_vault(kept, icp, xray, vault) if vault else None

    return {
        "schema_version": "hermes_linkedin_outbound/v1",
        "icp": icp,
        "xray": xray,
        "apify_inputs": apify_inputs,
        "sources_used": source_log,
        "companies_count": len(companies),
        "contacts_count": len(kept),
        "skipped_dnc": skipped_dnc,
        "items": kept,
        "vault": vault_out,
        "automatic_send": False,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LinkedIn ICP 정의 -> Apify 회사·담당자 소싱 -> 워밍업·DM 시퀀스")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_xray = sub.add_parser("xray", help="setup.json 기반 LinkedIn Boolean X-Ray 쿼리 & Apify 입력 JSON 생성")
    p_xray.add_argument("--config", default=str(ROOT / "setup.json"))
    p_xray.add_argument("--company", action="append", default=[])
    p_xray.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run", help="Apify Actor 또는 Sales Nav CSV/JSON으로 LinkedIn 소싱 + 워밍업/DM 생성")
    p_run.add_argument("--config", default=str(ROOT / "setup.json"))
    p_run.add_argument("--home")
    p_run.add_argument("--vault")
    p_run.add_argument("--contacts-file", help="Sales Navigator CSV 또는 Apify People JSON 파일")
    p_run.add_argument("--companies-file", help="Apify Company JSON 파일 (선택)")
    p_run.add_argument("--apify-company-actor", default="", help="Apify LinkedIn Company Actor ID (예: owner/actor)")
    p_run.add_argument("--apify-people-actor", default="", help="Apify LinkedIn People Actor ID (예: owner/actor)")
    p_run.add_argument("--max-companies", type=int, default=20)
    p_run.add_argument("--max-people", type=int, default=40)
    p_run.add_argument("--language", choices=("ko", "en"))
    p_run.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    cfg: dict[str, Any] = {}
    cfg_p = Path(args.config).expanduser()
    if cfg_p.is_file():
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))

    try:
        if args.cmd == "xray":
            icp = build_linkedin_icp(cfg, companies=args.company)
            xray = generate_xray_queries(icp)
            apify_inputs = build_apify_actor_inputs(icp)
            out = {"icp": icp, "xray": xray, "apify_inputs": apify_inputs}
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0

        home = paths.normalize_home(args.home)
        res = run_linkedin_pipeline(
            cfg,
            home=home,
            vault=args.vault,
            contacts_file=args.contacts_file,
            companies_file=args.companies_file,
            apify_company_actor=args.apify_company_actor,
            apify_people_actor=args.apify_people_actor,
            max_companies=args.max_companies,
            max_people=args.max_people,
            language=args.language,
        )
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"LinkedIn 파이프라인 완료: 회사 {res['companies_count']}건 · 담당자 {res['contacts_count']}건 (DNC 제외 {len(res['skipped_dnc'])}건)")
            if res["vault"]:
                print(f"Obsidian 큐: {res['vault']['queue']}")
            for item in res["items"][:5]:
                c, sc, pl = item["contact"], item["score"], item["plan"]
                print(f"\n[{sc['tier']} {sc['score']}점] {c['name']} ({c['title']}) @ {c['company']}")
                print(f"  연결요청({pl['connect_chars']}/300자): {pl['connect_note']}")
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
