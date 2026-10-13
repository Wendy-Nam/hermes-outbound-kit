#!/usr/bin/env python3
"""수집한 신호 레코드를 account_score.py 입력(JSONL, 회사당 1줄)으로 바꾼다.

받는 입력(stdin JSON 리스트, 섞여 있어도 된다):
  - funding_search.py --json        {company, round, amount, sector, date, url}
  - hiring_enrich.py --json         위 필드 + {open_roles, roles}
  - wanted/kr/ats 검색 --json        {company, title, url, (date), ...}

원칙: 확인된 것만 옮긴다. 모르는 값은 키를 넣지 않는다(account_score가 분모에서 뺀다).
  - 원티드 공고 0건은 "채용 안 함"이 아니라 "원티드에서 못 찾음"이라 신호로 쓰지 않는다.
  - 투자 기사는 업종(sector)·규모(round/amount)만 알려준다. 수익모델·기술스택은 리서치 몫.

사용:
  funding_search.py --json | hiring_enrich.py --json | signals_to_accounts.py \
    | account_score.py --jsonl --json-out
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date


def _days_ago(value):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return max(0, (date.today() - date(*map(int, m.groups()))).days)
    except ValueError:
        return None


def _key(name):
    return re.sub(r"[^가-힣a-z0-9]", "", (name or "").lower())


def convert(rows):
    accounts = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        company = (r.get("company") or "").strip()
        if not company or company == "-":
            continue                                    # 회사 미확인 레코드는 계정으로 만들지 않는다
        acc = accounts.setdefault(_key(company), {
            "company": company, "fit": {}, "urgency": {}, "evidence": {},
            "signals": {"roles": [], "funding": "", "sources": []}})
        url = r.get("url") or ""
        if url and url not in acc["signals"]["sources"]:
            acc["signals"]["sources"].append(url)

        # 투자 기사 레코드
        if r.get("round") or r.get("amount"):
            funding = " ".join(x for x in (r.get("round"), r.get("amount")) if x).strip()
            acc["urgency"]["funding"] = {"text": f"{funding} 투자 유치", "days_ago": _days_ago(r.get("date"))}
            acc["signals"]["funding"] = funding
            acc["fit"].setdefault("size", funding)
            if url:
                acc["evidence"]["funding"] = url
        sector = r.get("sector")
        if sector and sector != "-":
            acc["fit"].setdefault("industry", sector)

        # 채용 신호: 보강 결과의 roles 또는 채용 보드의 공고 제목
        roles = list(r.get("roles") or [])
        if not roles and r.get("title") and not (r.get("round") or r.get("amount")):
            roles = [r["title"]]
            if url:
                acc["evidence"].setdefault("hiring", url)
        for role in roles:
            if role and role not in acc["signals"]["roles"]:
                acc["signals"]["roles"].append(role)
        if r.get("open_roles"):
            acc["signals"]["open_roles"] = r["open_roles"]

    out = []
    for acc in accounts.values():
        roles = acc["signals"]["roles"]
        if roles:
            acc["urgency"]["hiring"] = {"text": ", ".join(roles[:10])}
        if not acc["evidence"]:
            acc.pop("evidence")
        out.append(acc)
    return out


def main():
    ap = argparse.ArgumentParser(description="신호 레코드 → account_score.py 입력(JSONL)")
    ap.add_argument("--in", dest="src", help="JSON 파일(없으면 stdin)")
    a = ap.parse_args()
    raw = open(a.src, encoding="utf-8").read() if a.src else sys.stdin.read()
    try:
        rows = json.loads(raw)
    except ValueError:
        sys.exit("❌ 입력이 JSON 리스트가 아닙니다. 수집 스크립트를 --json 으로 실행해 파이프하세요.")
    if isinstance(rows, dict):
        rows = [rows]
    for acc in convert(rows):
        print(json.dumps(acc, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
