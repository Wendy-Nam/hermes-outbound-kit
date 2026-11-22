#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""원티드(wanted.co.kr) 채용공고 검색 — 공개 API, 인증 불필요.

Usage:
    python3 wanted_search.py "백엔드" [--limit 20] [--pages 2] [--details] [--json]
    python3 wanted_search.py "데이터 엔지니어" --limit 10 --details

출력: 공고 목록 (제목 · 회사 · 지역 · 경력 · 기술스택 · 링크). --json 시 구조화 JSON.
링크는 https://www.wanted.co.kr/wd/<id>.
"""
import argparse
import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

SEARCH = "https://www.wanted.co.kr/api/chaos/search/v1/results"
DETAIL = "https://www.wanted.co.kr/api/v4/jobs/{job_id}"
MAX_BYTES = 5 * 1024 * 1024
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
KST = timezone(timedelta(hours=9))
_SENIOR = re.compile(
    r"(?i)(senior|\bsr\.?\b|staff|principal|\blead\b|director|head\s+of|\bvp\b|chief|高[级級]|"
    r"리더|리더급|strategic|시니어|수석|책임|총괄|팀장|실장|본부장|팀리드|파트장|그룹장|\bintern(ship)?\b|인턴|체험형)"
)


def is_senior(title):
    return bool(_SENIOR.search(title or ""))


def _get_json(url: str, referer: str = "https://www.wanted.co.kr/") -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Accept-Encoding": "gzip",
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read(MAX_BYTES)
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8-sig"))


def fetch(query: str, limit: int, pages: int = 1, delay: float = 0.5) -> list[dict]:
    per_page = min(limit, 20)
    out, seen = [], set()
    for page_idx in range(max(1, min(pages, 5))):
        qs = urllib.parse.urlencode({"query": query, "tab": "position", "limit": per_page, "offset": page_idx * per_page})
        data = _get_json(f"{SEARCH}?{qs}")
        positions = data.get("positions")
        if isinstance(positions, dict):
            positions = positions.get("data") or positions.get("list") or []
        if not isinstance(positions, list) or not positions:
            break
        added = 0
        for p in positions:
            pid = p.get("id") if isinstance(p, dict) else None
            if pid and pid not in seen:
                seen.add(pid)
                out.append(p)
                added += 1
        if len(out) >= limit or added == 0 or len(positions) < per_page:
            break
        if delay > 0:
            time.sleep(delay)
    return out[:limit]


def enrich_detail(job: dict) -> dict:
    pid = job.get("id")
    if not pid:
        return job
    try:
        data = _get_json(DETAIL.format(job_id=pid), referer=f"https://www.wanted.co.kr/wd/{pid}")
    except Exception:
        return job
    detail_job = data.get("job") if isinstance(data.get("job"), dict) else data
    detail = detail_job.get("detail") if isinstance(detail_job.get("detail"), dict) else {}
    parts = []
    for label, key in (("주요업무", "main_tasks"), ("자격요건", "requirements"), ("우대사항", "preferred_points")):
        text = re.sub(r"\s+", " ", str(detail.get(key) or "")).strip()
        if text:
            parts.append(f"[{label}] {text[:400]}")
    if parts:
        job["description"] = " / ".join(parts)[:1500]
    tags = detail_job.get("skill_tags") or []
    skills = [t.get("title") if isinstance(t, dict) else str(t) for t in tags if t]
    if skills:
        job["stack"] = list(dict.fromkeys((job.get("stack") or []) + skills))
    comp = detail_job.get("company") if isinstance(detail_job.get("company"), dict) else {}
    if comp.get("industry_name"):
        job["industry"] = comp["industry_name"]
    return job


def norm(p: dict) -> dict:
    pid = p.get("id")
    comp = p.get("company") or {}
    addr = p.get("address") or {}
    tags = p.get("skill_tags") or []
    skills = [t.get("title") if isinstance(t, dict) else str(t) for t in tags if t]
    af, at = p.get("annual_from"), p.get("annual_to")
    exp = f"경력 {af or 0}~{at}년" if isinstance(at, int) and at < 99 else (f"경력 {af}년+" if isinstance(af, int) and af > 0 else "")
    return {
        "id": pid,
        "title": p.get("position") or p.get("title") or p.get("name") or "",
        "company": comp.get("name") if isinstance(comp, dict) else (p.get("company_name") or ""),
        "industry": comp.get("industry_name", "") if isinstance(comp, dict) else "",
        "reward": p.get("reward_total") or (p.get("reward") or {}).get("total") if isinstance(p.get("reward"), dict) else p.get("reward"),
        "location": (addr.get("full_location") or addr.get("location")) if isinstance(addr, dict) else p.get("location"),
        "experience": exp,
        "stack": skills,
        "url": f"https://www.wanted.co.kr/wd/{pid}" if pid else "",
    }


def to_rows(jobs: list[dict]) -> list[str]:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return [f"| {j['company']} | {j['title']} | wanted |  | 발견 | {today} | {j['url']} |" for j in jobs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--pages", type=int, default=1, help="수집 페이지 수 (1~5)")
    ap.add_argument("--details", action="store_true", help="공고 상세 JD·기술스택 추가 수집 (상위 12건)")
    ap.add_argument("--junior-only", action="store_true", help="시니어·리더 제목 제외(구직용). 영업 신호 탐색은 기본값(전체 직급)")
    ap.add_argument("--all-levels", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    try:
        raw = fetch(a.query, a.limit, pages=a.pages)
    except Exception as e:
        print(f"에러: 원티드 조회 실패 — {e}", file=sys.stderr)
        return 1
    jobs = [norm(p) for p in raw if isinstance(p, dict)]
    if a.junior_only:
        jobs = [j for j in jobs if not is_senior(j["title"])]
    if a.details:
        for job in jobs[:12]:
            enrich_detail(job)
            time.sleep(0.35)
    if a.json:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        return 0
    if a.table:
        print("| 회사 | 포지션 | 보드 | 적합도 | 상태 | 갱신일 | 공고링크 |")
        print("|---|---|---|---|---|---|---|")
        print("\n".join(to_rows(jobs)))
        return 0
    if not jobs:
        print(f'"{a.query}" 검색 결과 없음.')
        return 0
    print(f'# 원티드 "{a.query}" 검색 — {len(jobs)}건\n')
    for j in jobs:
        line = f"- **{j['title']}** · {j['company']}"
        if j.get("location"):
            line += f" · {j['location']}"
        if j.get("experience"):
            line += f" · {j['experience']}"
        if j.get("stack"):
            line += f" · [{', '.join(j['stack'][:6])}]"
        line += f"\n  {j['url']}"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
