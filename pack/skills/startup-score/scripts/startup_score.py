#!/usr/bin/env python3
"""startup-score — 보강된 투자 스타트업을 BD 우선순위로 랭크.

입력: startup_enrich.py --json (stdin).
우선도 = 라운드규모 + 채용볼륨×1.5 + 신선도 + 섹터적합.
  - 채용볼륨(열린 포지션)에 최대 가중 — 실제로 뽑는 회사가 최고의 BD 타깃.
  - 신선도 — 투자 직후일수록 경쟁 리크루터 미접촉, 선점 여지 큼.

출력: 점수 내림차순 랭크 테이블 / --json. 구직 키트 우선도 공식(가중합)과 동일 철학.
"""
import argparse
import json
import re
import sys
from datetime import date

W_ROLES = 1.5   # 채용볼륨 가중(핵심 신호)


def _amt_score(rec):
    m = re.search(r"([\d,]+)\s*억", rec.get("amount", ""))
    if m:
        v = int(m.group(1).replace(",", ""))          # 억 단위
        return 5 if v >= 1000 else 4 if v >= 200 else 3 if v >= 50 else 2 if v >= 10 else 1
    rn = re.sub(r"\s", "", rec.get("round", ""))       # 금액 없으면 라운드 단계로
    if "시리즈C" in rn or "SeriesC" in rn:
        return 4.5
    if "시리즈B" in rn or "SeriesB" in rn:
        return 4
    if "시리즈A" in rn or "SeriesA" in rn:
        return 3
    if "프리" in rn or "Pre" in rn:
        return 2
    if "시드" in rn or "브릿지" in rn:
        return 1.5
    return 1


def _roles_score(rec):
    n = rec.get("open_roles")
    if n is None:
        return 0.5                                     # 미확인
    return 0 if n == 0 else 1 if n <= 2 else 2 if n <= 5 else 3 if n <= 10 else 4


def _recency_score(rec):
    try:
        y, m, d = map(int, rec.get("date", "").split("-"))
        days = (date.today() - date(y, m, d)).days
    except Exception:
        return 1
    return 3 if days <= 7 else 2 if days <= 14 else 1 if days <= 30 else 0.5


def score(rec, sectors):
    sec_bonus = 1 if sectors and rec.get("sector", "") in sectors else 0
    s = _amt_score(rec) + _roles_score(rec) * W_ROLES + _recency_score(rec) + sec_bonus
    rec["score"] = round(s, 1)
    return rec


def main():
    ap = argparse.ArgumentParser(description="투자 스타트업 BD 우선순위 랭크")
    ap.add_argument("--sectors", default="", help="선호 섹터 콤마구분(적합 시 +1). 예: AI,로보틱스")
    ap.add_argument("--top", type=int, default=0, help="상위 N만(0=전부)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sectors = {s.strip() for s in a.sectors.split(",") if s.strip()}
    try:
        rows = json.load(sys.stdin)
    except Exception:
        sys.exit("stdin에 startup_enrich.py --json 출력을 파이프하세요")
    ranked = sorted((score(r, sectors) for r in rows), key=lambda r: r["score"], reverse=True)
    if a.top:
        ranked = ranked[:a.top]
    if a.json:
        print(json.dumps(ranked, ensure_ascii=False, indent=2))
        return 0
    print(f"{'#':<3}{'점수':<6}{'회사':<20}{'라운드':<9}{'금액':<10}{'공고':<5}{'섹터':<9}게시일")
    for i, r in enumerate(ranked, 1):
        opn = r.get("open_roles")
        opn = "?" if opn is None else str(opn)
        print(f"{i:<3}{r['score']:<6}{r['company'][:18]:<20}{r.get('round',''):<9}"
              f"{r.get('amount',''):<10}{opn:<5}{r.get('sector',''):<9}{r.get('date','')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
