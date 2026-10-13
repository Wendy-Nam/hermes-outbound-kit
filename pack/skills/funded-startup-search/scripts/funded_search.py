#!/usr/bin/env python3
"""funded-startup-search — 최근 투자받은 한국 스타트업을 헤드헌팅 BD 타깃으로 수집.

소스: Platum 투자 카테고리(WordPress REST API, 공개·인증불필요·합법).
투자 직후 = 대규모 채용 임박 = 헤드헌터 골든타임. 신선도가 핵심이라 최신순 수집.

출력: {회사, 라운드, 금액, 게시일, 섹터힌트, 링크}. --json / --table / 기본 목록.
구직 키트 스크래퍼와 동일 계약(정규화 리스트) — 수집기·스테이징에 그대로 물릴 수 있음.
"""
import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request

PLATUM_CAT = 7521  # "투자" 카테고리 (WP REST /categories?search=투자 로 확인)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

_ROUND = re.compile(r"(시리즈\s?[A-D]|프리\s?[A-B]|시드|브릿지|Pre-?[A-B]|Series\s?[A-D])", re.I)
_AMT = re.compile(r"(\d[\d,]*)\s*억\s*원?")
_QUOTED = re.compile(r"[‘'\"“]([^’'\"”]{2,30})[’'\"”]")

# 투자사/펀드 뉴스 제외 — 스타트업이 '받은' 게 아니라 투자사가 '조성/출자'한 기사.
_FUND_EVENT = re.compile(r"펀드\s*결성|펀드\s*조성|투자조합|모태\s*펀드|출자\s*(사업|공고)|결성|재원\s*조성")
_INVESTOR_SUFFIX = re.compile(r"(벤처스|파트너스|캐피탈|인베스트먼트|자산운용|어드바이저|프라이빗에쿼티|"
                              r"D2SF|스파크랩|프라이머|블루포인트|액셀러레이터)$")

# 섹터 힌트(대략 분류; 정밀 분류는 판정 단계 몫)
_SECTOR = [("AI", r"\bAI\b|인공지능|에이전트|LLM|딥러닝"), ("바이오/헬스", r"바이오|헬스|의료|제약|진단|치과|병원"),
           ("핀테크", r"핀테크|금융|결제|보험|대출|송금|급여"), ("커머스", r"커머스|이커머스|쇼핑|리테일|브랜드|뷰티|패션"),
           ("로보틱스", r"로보틱스|로봇|자율주행|모빌리티|드론"), ("SaaS/B2B", r"SaaS|B2B|솔루션|플랫폼|자동화|인프라")]


def _clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _company(title):
    q = _QUOTED.search(title)                       # ‘회사명’ 우선(플래텀은 회사명을 따옴표로 감쌈)
    name = q.group(1).strip() if q else re.split(r"[,·]| - |—|…", title)[0].strip()
    return name.strip(" ,·'\"‘’“”")[:30]
    # ponytail: 제목 파싱만으로 회사명 추정(따옴표 없는 설명형 제목은 노이즈), upgrade: enrich가 회사명 불일치로 원티드 매칭을 놓치면 startup-enrich 본문 1-hop에서 정확 회사명 확정


def _sector(text):
    for name, pat in _SECTOR:
        if re.search(pat, text, re.I):
            return name
    return "-"


def fetch(pages=2, per_page=20):
    out, seen = [], set()
    for pg in range(1, pages + 1):
        qs = urllib.parse.urlencode({"categories": PLATUM_CAT, "per_page": per_page,
                                     "page": pg, "_fields": "title,link,date,excerpt"})
        req = urllib.request.Request(f"https://platum.kr/wp-json/wp/v2/posts?{qs}",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            posts = json.loads(r.read().decode("utf-8-sig"))
        if not posts:
            break
        for p in posts:
            link = p.get("link", "")
            if link in seen:
                continue
            seen.add(link)
            title = _clean(p.get("title", {}).get("rendered", ""))
            excerpt = _clean(p.get("excerpt", {}).get("rendered", ""))
            blob = title + " " + excerpt
            if not re.search(r"투자\s*유치|유치|라운드|펀딩|투자를?\s*받", blob):
                continue                              # 투자 무관 기사 제외
            if _FUND_EVENT.search(title):
                continue                              # 펀드 결성·출자 뉴스 제외(스타트업 아님)
            comp = _company(title)
            if _INVESTOR_SUFFIX.search(comp):
                continue                              # 투자사/AC 자체 뉴스 제외
            amt = _AMT.search(blob)
            rnd = _ROUND.search(blob)
            out.append({
                "company": comp,
                "round": rnd.group(0).strip() if rnd else "",
                "amount": amt.group(0).replace(" ", "") if amt else "",
                "date": p.get("date", "")[:10],
                "sector": _sector(blob),
                "url": link,
            })
    return out


def main():
    ap = argparse.ArgumentParser(description="최근 투자받은 한국 스타트업 수집(Platum)")
    ap.add_argument("--pages", type=int, default=2, help="가져올 페이지 수(페이지당 20건)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    try:
        rows = fetch(pages=a.pages)
    except (OSError, ValueError) as e:              # 네트워크 차단·사이트 응답 변경
        print(f"❌ Platum 투자 기사에 접속하지 못했습니다({type(e).__name__}). "
              "인터넷 연결이나 회사 네트워크 차단 여부를 확인하고 잠시 후 다시 시도하세요. "
              "0건으로 간주하지 마세요.", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if a.table:
        print(f"{'회사':<24}{'라운드':<10}{'금액':<11}{'섹터':<11}{'게시일':<12}링크")
        for r in rows:
            print(f"{r['company'][:22]:<24}{r['round']:<10}{r['amount']:<11}{r['sector']:<11}{r['date']:<12}{r['url']}")
        print(f"\n총 {len(rows)}건 (투자사·펀드 뉴스 제외)")
        return 0
    for r in rows:
        seg = " · ".join(x for x in (r["round"], r["amount"], r["sector"]) if x)
        print(f"💰 {r['company']} — {seg}  ({r['date']})\n   {r['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
