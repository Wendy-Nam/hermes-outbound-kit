#!/usr/bin/env python3
"""hiring-signal-enrich — 계정 후보 목록에 원티드 채용 신호를 붙인다.

입력: funding_search.py --json 등 {company, ...} 리스트(stdin).
보강: 원티드 회사명 질의 → 공고 수·직무목록.

설계 원칙(키트 공통): **스크래퍼는 구조화 데이터만.** 대표·정확 회사명·투자금액 판별처럼
지저분한 한국어 산문에서 뽑는 건 regex가 아니라 **Hermes LLM(기사 본문 판독)의 몫**이다.
그래서 이 스크립트는 기계적으로 확실한 것(원티드 공고 수)만 붙이고, 나머지는 판정 단계에 넘긴다.

회사당 요청 1건, --limit·딜레이로 정중하게. 실패는 폴트오픈(open_roles=None, 수집 안 죽임).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

# VPS(호스팅어 데이터센터 IP)는 원티드가 403 차단 → HERMES_SCRAPER_PROXY 있으면 경유
# (구직 키트와 동일 노브). 일반 IP(로컬)에선 미설정으로 직접. http/https 둘 다 태운다.
_PROXY = os.environ.get("HERMES_SCRAPER_PROXY", "").strip()
_OPENER = (urllib.request.build_opener(urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY}))
           if _PROXY else urllib.request.build_opener())


def _norm(s):
    return re.sub(r"[^가-힣a-z0-9]", "", (s or "").lower())


def wanted_roles(company):
    """원티드 회사명 질의 → 그 회사 공고만 필터해 개수·직무. 실패는 open_roles=None."""
    try:
        q = urllib.parse.urlencode({"query": company, "tab": "position", "limit": 20})
        req = urllib.request.Request(
            f"https://www.wanted.co.kr/api/chaos/search/v1/results?{q}", headers={"User-Agent": UA})
        with _OPENER.open(req, timeout=20) as r:
            d = json.loads(r.read())
    except Exception:
        return {"open_roles": None, "roles": []}

    # 응답 구조: {companies, positions, careers, ...}. 공고는 positions.data,
    # 각 항목에 company:{id,name}·position(직무명). 회사명 일치하는 것만 센다.
    positions = (d.get("positions") or {}).get("data", []) if isinstance(d, dict) else []
    key = _norm(company)
    roles = []
    for p in positions:
        cname = (p.get("company") or {}).get("name", "")
        if key and key in _norm(cname):          # 그 회사 공고만(제목 키워드 매치 배제)
            roles.append(p.get("position") or "")
    return {"open_roles": len(roles), "roles": roles[:10]}


def enrich(rec, delay=1.0):
    w = wanted_roles(rec.get("company", ""))
    rec["open_roles"] = w["open_roles"]   # None=원티드 미확인, 0=원티드에 없음(시드단계 흔함), N=채용중
    rec["roles"] = w["roles"]
    time.sleep(delay)
    return rec


def main():
    ap = argparse.ArgumentParser(description="계정 후보 목록에 원티드 채용현황 보강")
    ap.add_argument("--limit", type=int, default=8, help="보강할 회사 수(요청 절약)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()
    try:
        rows = json.load(sys.stdin)
    except Exception:
        sys.exit("stdin에 funding_search.py --json 출력을 파이프하세요")
    out = [enrich(r, a.delay) for r in rows[:a.limit]]
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"{'회사':<22}{'라운드':<9}{'금액':<10}{'원티드공고':<9}주요 직무")
    for r in out:
        opn = r.get("open_roles")
        opn = "?" if opn is None else str(opn)
        roles = ", ".join(r.get("roles", [])[:3])
        print(f"{r['company'][:20]:<22}{r.get('round',''):<9}{r.get('amount',''):<10}{opn:<9}{roles}")
    print("\n원티드공고: ?=미확인 · 0=원티드 미등록(시드단계 흔함) · N=채용중(긴급도 신호 후보)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
