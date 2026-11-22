#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""공개 ATS 직접 조회 (Greenhouse/Lever/Ashby/Greeting 공개 API·페이지, 인증 불필요).

Usage:
    python3 ats_search.py --keyword sales --limit 40
    python3 ats_search.py --keyword "business development" --json
    python3 ats_search.py --company coupang --keyword 영업 --all-locations
targets: $HERMES_HOME/ats-targets.json (우선) 또는 <skill dir>/data/ats-targets.json
"""
import argparse
import gzip
import html
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
MAX_BYTES = 5 * 1024 * 1024
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36", "Accept-Encoding": "gzip"}
DEFAULT_TARGETS = Path(__file__).resolve().parent.parent / "data" / "ats-targets.json"
_SENIOR = re.compile(
    r"(?i)(senior|\bsr\.?\b|staff|principal|\blead\b|director|head\s+of|\bvp\b|chief|高[级級]|"
    r"리더|리더급|strategic|시니어|수석|책임|총괄|팀장|실장|본부장|팀리드|파트장|그룹장|\bintern(ship)?\b|인턴|체험형)"
)
KR_HINTS = ("korea", "seoul", "서울", "한국", "대한민국", "gyeonggi", "경기", "부산", "busan", "incheon", "판교", "pangyo")


def is_senior(title):
    return bool(_SENIOR.search(title or ""))


def _get_raw(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        raw = r.read(MAX_BYTES)
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw


def get(url):
    return json.loads(_get_raw(url).decode("utf-8-sig"))


def greenhouse(token):
    js = get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs").get("jobs", [])
    return [dict(title=j.get("title", ""), location=(j.get("location") or {}).get("name", ""),
                 url=j.get("absolute_url", ""), id=str(j.get("id", "")), date=str(j.get("updated_at") or "")[:10]) for j in js]


def lever(token):
    js = get(f"https://api.lever.co/v0/postings/{token}?mode=json")
    return [dict(title=j.get("text", ""), location=(j.get("categories") or {}).get("location", ""),
                 url=j.get("hostedUrl", ""), id=j.get("id", ""), date="") for j in js if isinstance(j, dict)]


def ashby(token):
    js = get(f"https://api.ashbyhq.com/posting-api/job-board/{token}").get("jobs", [])
    return [dict(title=j.get("title", ""), location=j.get("location", ""),
                 url=j.get("jobUrl") or j.get("applyUrl", ""), id=j.get("id", ""), date=str(j.get("publishedAt") or "")[:10]) for j in js]


def greeting(token):
    page = _get_raw(f"https://{token}.career.greetinghr.com/ko/career").decode("utf-8", "ignore")
    out, seen = [], set()
    for m in re.finditer(r'href="(/(?:ko/)?o/(\d+)[^"]*)"[^>]*>(.*?)</a>', page, re.S | re.I):
        oid = m.group(2)
        title = html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))
        title = re.sub(r"\s+", " ", title).strip()
        if not title or oid in seen:
            continue
        seen.add(oid)
        out.append(dict(title=title, location="대한민국", url=f"https://{token}.career.greetinghr.com/ko/o/{oid}", id=oid, date=""))
    return out


FETCH = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "greeting": greeting}


def resolve_targets_path(explicit=None):
    if explicit:
        return Path(explicit).expanduser().absolute()
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        candidate = Path(env_home).expanduser().absolute() / "ats-targets.json"
        if candidate.is_file():
            return candidate
    return DEFAULT_TARGETS


def load_targets(company=None, targets_path=None):
    path = resolve_targets_path(targets_path)
    try:
        tg = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        print(f"경고: {path} 없음. 대상 회사를 추가하세요.", file=sys.stderr)
        return []
    return [t for t in tg if not company or t.get("token") == company or t.get("company", "").lower() == company.lower()]


_FAILURES = []


def scan(company, keyword, korea_only, limit, junior_only=False, targets_path=None):
    out = []
    terms = [k.strip().lower() for k in re.split(r"[,;/|]+", keyword or "") if k.strip()]
    for t in load_targets(company, targets_path):
        fn = FETCH.get(t.get("ats"))
        if not fn:
            continue
        try:
            jobs = fn(t["token"])
        except Exception as e:
            print(f"경고: {t.get('company')} ({t.get('ats')}) 조회 실패 — {type(e).__name__}", file=sys.stderr)
            _FAILURES.append(t.get("company", t["token"]))
            continue
        for j in jobs:
            loc = (j.get("location") or "").lower()
            if korea_only and t.get("ats") != "greeting" and not any(h in loc for h in KR_HINTS):
                continue
            if terms and not any(term in j.get("title", "").lower() for term in terms):
                continue
            if junior_only and is_senior(j.get("title", "")):
                continue
            j["company"] = t.get("company", t["token"])
            j["ats"] = t.get("ats")
            out.append(j)
        time.sleep(0.35)
    return out[:limit]


def to_rows(jobs):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return [f"| {j['company']} | {j['title']} | ats | | 발견 | {today} | {j['url']} |" for j in jobs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--targets", default="", help="사용자 정의 ats-targets.json 경로")
    ap.add_argument("--all-locations", action="store_true")
    ap.add_argument("--junior-only", action="store_true", help="시니어·리더 제목 제외(구직용). 영업 신호 탐색은 기본값(전체 직급)")
    ap.add_argument("--all-levels", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    jobs = scan(a.company or None, a.keyword, not a.all_locations, a.limit, junior_only=a.junior_only, targets_path=a.targets or None)
    if not jobs and _FAILURES:
        print("❌ 조회 실패로 결과를 확인하지 못했습니다(0건이 아님): " + ", ".join(_FAILURES)
              + ". 인터넷 연결·사이트 차단 여부를 확인하고 잠시 후 다시 시도하세요.", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        return 0
    if a.table:
        print("| 회사 | 포지션 | 보드 | 적합도 | 상태 | 갱신일 | 공고링크 |\n|---|---|---|---|---|---|---|")
        print("\n".join(to_rows(jobs)))
        return 0
    print(f'# 공개 ATS "{a.keyword or "전체"}" — {len(jobs)}건\n')
    for j in jobs:
        print(f"- **{j['title']}** · {j['company']} · {j['location']}\n  {j['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
