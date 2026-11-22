#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""사람인·잡코리아·점핏 채용공고 검색 (공개 웹/API, 인증 불필요).

Usage:
    python3 kr_job_search.py "백엔드" --board saramin --limit 20 --pages 2
    python3 kr_job_search.py "생산기술" --board jobkorea --limit 15
    python3 kr_job_search.py "데이터 엔지니어" --board jumpit --limit 20 --json
    python3 kr_job_search.py "해외영업" --board all --limit 30 --json
"""
import argparse
import gzip
import html as _html
from html.parser import HTMLParser
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
MAX_BYTES = 5 * 1024 * 1024
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
_SENIOR = re.compile(
    r"(?i)(senior|\bsr\.?\b|staff|principal|\blead\b|director|head\s+of|\bvp\b|chief|高[级級]|"
    r"리더|리더급|strategic|시니어|수석|책임|총괄|팀장|실장|본부장|팀리드|파트장|그룹장|\bintern(ship)?\b|인턴|체험형)"
)


def is_senior(title):
    return bool(_SENIOR.search(title or ""))


def _get(url, accept="text/html,application/xhtml+xml", referer=None):
    headers = {"User-Agent": UA, "Accept": accept, "Accept-Language": "ko-KR,ko;q=0.9", "Accept-Encoding": "gzip"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(MAX_BYTES)
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "ignore")


def _clean(s):
    return _html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"\s+", " ", s or ""))).strip()


_FAILURES = []


class _SaraminCard(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rid = ""
        self.title = ""
        self.company = ""
        self.conditions = []
        self.sectors = []
        self.date = ""
        self._stack = []
        self._cap = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        amap = {k.lower(): (v or "") for k, v in attrs}
        cls = amap.get("class", "")
        self._stack.append((tag, cls))
        if tag == "input" and not self.rid and re.fullmatch(r"\d{4,12}", amap.get("value", "")):
            self.rid = amap["value"]
        if tag == "a" and not self.rid:
            m = re.search(r"rec_idx=(\d{4,12})", amap.get("href", ""))
            if m:
                self.rid = m.group(1)
        above = " ".join(c for _, c in self._stack)
        if tag == "a" and "job_tit" in above and not self.title:
            if amap.get("title"):
                self.title = amap["title"]
            else:
                self._cap, self._buf = "title", []
        elif tag == "a" and ("corp_name" in above or "area_corp" in above) and not self.company:
            if amap.get("title") and "관심기업" not in amap.get("title", ""):
                self.company = amap["title"]
            else:
                self._cap, self._buf = "company", []
        elif tag == "span" and "job_condition" in above:
            self._cap, self._buf = "cond", []
        elif tag == "a" and "job_sector" in above:
            self._cap, self._buf = "sector", []
        elif tag == "span" and ("job_date" in above or "date" in cls):
            self._cap, self._buf = "date", []

    def handle_data(self, data):
        if self._cap:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if self._cap:
            txt = _clean("".join(self._buf))
            if txt:
                if self._cap == "title" and not self.title:
                    self.title = txt
                elif self._cap == "company" and not self.company:
                    self.company = txt
                elif self._cap == "cond":
                    self.conditions.append(txt)
                elif self._cap == "sector":
                    self.sectors.append(txt)
                elif self._cap == "date" and not self.date:
                    self.date = txt
            self._cap, self._buf = None, []
        if self._stack:
            self._stack.pop()


def saramin(kw, limit, pages=2):
    out, seen = [], set()
    for page in range(1, max(1, min(pages, 5)) + 1):
        url = (
            "https://www.saramin.co.kr/zf_user/search/recruit?searchType=search&searchword="
            + urllib.parse.quote(kw) + f"&recruitPage={page}&recruitPageCount=40"
        )
        try:
            h = _get(url, referer="https://www.saramin.co.kr/")
        except Exception as e:
            print(f"경고: 사람인 page{page} 실패 ({e})", file=sys.stderr)
            _FAILURES.append("사람인")
            break
        blocks = re.split(r'class="[^"]*\bitem_recruit\b[^"]*"', h)[1:]
        if not blocks:
            break
        for b in blocks:
            card = _SaraminCard()
            try:
                card.feed(f'<div class="item_recruit">{b}')
            except Exception:
                pass
            if not card.rid:
                m = re.search(r'value="(\d+)"|rec_idx=(\d+)', b)
                card.rid = (m.group(1) or m.group(2)) if m else ""
            if not card.rid or card.rid in seen:
                continue
            seen.add(card.rid)
            out.append(dict(
                board="saramin",
                title=_clean(card.title),
                company=_clean(card.company),
                location=card.conditions[0] if card.conditions else "",
                experience=", ".join(card.conditions[1:3]) if len(card.conditions) > 1 else "",
                stack=[s for s in card.sectors if s != "외"][:8],
                date=card.date,
                url=f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={card.rid}",
            ))
            if len(out) >= limit:
                return out
        time.sleep(0.8)
    return out[:limit]


def jobkorea(kw, limit, pages=2):
    out, seen = [], set()
    for page in range(1, max(1, min(pages, 5)) + 1):
        url = f"https://www.jobkorea.co.kr/Search/?stext={urllib.parse.quote(kw)}&tabType=recruit&Page_No={page}"
        try:
            h = _get(url, referer="https://www.jobkorea.co.kr/")
        except Exception as e:
            print(f"경고: 잡코리아 page{page} 실패 ({e})", file=sys.stderr)
            _FAILURES.append("잡코리아")
            break
        added = 0
        # 1) Next.js __NEXT_DATA__ JSON
        nm = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S | re.I)
        if nm:
            try:
                data = json.loads(nm.group(1))
                found = []
                def walk(n):
                    if isinstance(n, list):
                        for x in n:
                            if isinstance(x, dict) and (x.get("gNo") or x.get("giNo")) and (x.get("gTitle") or x.get("title")):
                                found.append(x)
                            else:
                                walk(x)
                    elif isinstance(n, dict):
                        for v in n.values():
                            walk(v)
                walk(data)
                for item in found:
                    gi = str(item.get("gNo") or item.get("giNo") or "")
                    if not gi or gi in seen:
                        continue
                    seen.add(gi)
                    out.append(dict(
                        board="jobkorea",
                        title=_clean(item.get("gTitle") or item.get("title") or ""),
                        company=_clean(item.get("cName") or item.get("corpName") or ""),
                        location=_clean(item.get("workPlace") or item.get("area") or ""),
                        experience=_clean(item.get("career") or ""),
                        stack=[],
                        date=str(item.get("regDt") or "")[:10],
                        url=f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gi}",
                    ))
                    added += 1
                    if len(out) >= limit:
                        return out
            except json.JSONDecodeError:
                pass
        # 2) HTML card blocks fallback
        if added == 0:
            for block in re.split(r'<article\b|class="[^"]*\blist-item\b[^"]*"', h)[1:]:
                gm = re.search(r'Recruit/GI_Read/(\d{4,12})', block)
                if not gm or gm.group(1) in seen:
                    continue
                gi = gm.group(1)
                tm = re.search(r'href="[^"]*GI_Read/' + gi + r'[^"]*"[^>]*(?:title="([^"]+)")?[^>]*>(.*?)</a>', block, re.S | re.I)
                title = _clean((tm.group(1) or tm.group(2)) if tm else "")
                if not title or len(title) < 2:
                    continue
                cm = re.search(r'class="[^"]*(?:corp-name-link|name\s+dev_view|corp-name)[^"]*"[^>]*>(.*?)</a>', block, re.S | re.I)
                company = _clean(cm.group(1)) if cm else ""
                if not company:
                    bracket = re.match(r"\[([^\]]{2,30})\]", title)
                    company = bracket.group(1) if bracket else ""
                seen.add(gi)
                out.append(dict(
                    board="jobkorea", title=title, company=company, location="", experience="", stack=[], date="",
                    url=f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gi}",
                ))
                added += 1
                if len(out) >= limit:
                    return out
        if added == 0:
            break
        time.sleep(0.8)
    return out[:limit]


def jumpit(kw, limit, pages=2):
    out, seen = [], set()
    for page in range(1, max(1, min(pages, 5)) + 1):
        qs = urllib.parse.urlencode({"keyword": kw, "page": page, "sort": "rsp_rate"})
        try:
            raw = _get(f"https://api.jumpit.co.kr/api/positions?{qs}", accept="application/json", referer="https://www.jumpit.co.kr/")
            data = json.loads(raw)
        except Exception as e:
            print(f"경고: 점핏 page{page} 실패 ({e})", file=sys.stderr)
            _FAILURES.append("점핏")
            break
        positions = (data.get("result") or {}).get("positions") if isinstance(data, dict) else []
        if not isinstance(positions, list) or not positions:
            break
        added = 0
        for p in positions:
            pid = str(p.get("id") or "")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            locs = p.get("locations") or []
            out.append(dict(
                board="jumpit",
                title=_clean(p.get("title") or ""),
                company=_clean(p.get("companyName") or ""),
                location=", ".join(locs) if isinstance(locs, list) else str(locs),
                experience=f"경력 {p.get('minCareer', 0)}~{p.get('maxCareer', '')}년",
                stack=list(p.get("techStacks") or [])[:10],
                date=str(p.get("publishedAt") or p.get("closedAt") or "")[:10],
                url=f"https://www.jumpit.co.kr/position/{pid}",
            ))
            added += 1
            if len(out) >= limit:
                return out
        if added == 0:
            break
        time.sleep(0.5)
    return out[:limit]


def to_rows(jobs):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return [f"| {j['company']} | {j['title']} | {j['board']} |  | 발견 | {today} | {j['url']} |" for j in jobs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--board", default="all", choices=["saramin", "jobkorea", "jumpit", "all"])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--junior-only", action="store_true", help="시니어·리더 제목 제외(구직용). 영업 신호 탐색은 기본값(전체 직급)")
    ap.add_argument("--all-levels", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()

    jobs = []
    if a.board in ("saramin", "all"):
        jobs += saramin(a.query, a.limit, pages=a.pages)
    if a.board in ("jobkorea", "all"):
        jobs += jobkorea(a.query, a.limit, pages=a.pages)
    if a.board in ("jumpit", "all"):
        jobs += jumpit(a.query, a.limit, pages=a.pages)
    if a.junior_only:
        jobs = [j for j in jobs if not is_senior(j.get("title", ""))]
    if not jobs and _FAILURES:
        print("❌ 조회 실패로 결과를 확인하지 못했습니다(0건이 아님): " + ", ".join(dict.fromkeys(_FAILURES))
              + ". 인터넷 연결·사이트 차단 여부를 확인하고 잠시 후 다시 시도하세요.", file=sys.stderr)
        return 2

    if a.json:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        return 0
    if a.table:
        print("| 회사 | 포지션 | 보드 | 적합도 | 상태 | 갱신일 | 공고링크 |")
        print("|---|---|---|---|---|---|---|")
        print("\n".join(to_rows(jobs)))
        return 0
    print(f'# "{a.query}" · {a.board} — {len(jobs)}건\n')
    for j in jobs:
        extra = " · ".join(x for x in (j.get("location"), j.get("experience")) if x)
        stack = f" · [{', '.join(j['stack'][:5])}]" if j.get("stack") else ""
        print(f"- **{j['title']}** · {j['company'] or '(회사미상)'} · [{j['board']}]" + (f" · {extra}" if extra else "") + stack + f"\n  {j['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
