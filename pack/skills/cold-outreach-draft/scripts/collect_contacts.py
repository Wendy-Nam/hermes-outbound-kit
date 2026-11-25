#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""리드 홈페이지에서 '문의 가능한 공개 창구'를 모은다 (무료, 표준 라이브러리 직접 HTTP).

수집: 대표·고객센터 전화, 카카오 채널, 네이버 톡톡, 인스타그램, 문의·고객센터 페이지 주소, 채팅 위젯 흔적.
수집하지 않음: 이메일 주소 (정보통신망법 제50조의2 - 프로그램으로 이메일 자동 수집 금지). 이메일이 적힌 페이지 주소만 남긴다.
보안: TLS 인증서 검증 기본 활성, SSRF(localhost·사설 IP·비공개 스킴·내부 리다이렉트) 차단, CSV 수식 주입 중화.

사용:
  python3 collect_contacts.py LEADS_CSV(id,lead,homepage) OUT_CSV
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import ipaddress
import re
import socket
import ssl
import sys
from typing import Any
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; hermes-outbound-kit/1.0; +https://github.com/Wendy-Nam/hermes-outbound-kit)"

PHONE = re.compile(r"(?<![\d-])((?:0(?:2|[3-6][1-5]|70|50\d?)|1[5-9]\d{2})[-.)\s]?\d{3,4}[-.\s]?\d{4})(?!\d)")
KAKAO = re.compile(r"https?://pf\.kakao\.com/_[A-Za-z0-9]+(?:/chat)?")
TALK = re.compile(r"https?://talk\.naver\.com/[A-Za-z0-9_/]+")
INSTA = re.compile(r"https?://(?:www\.)?instagram\.com/(?!p/|explore|accounts|reel)[A-Za-z0-9_.]+")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WIDGET = {
    "channel.io": "channel.io",
    "카카오 상담": "kakao_chat",
    "zendesk": "zendesk",
    "intercom": "intercom",
    "네이버 톡톡": "talk.naver",
}
CONTACT_WORDS = re.compile(r"문의|고객센터|contact|cs\s?center|qna|q&a|inquiry|상담|1:1|제휴|교육문의", re.I)
A_TAG = re.compile(r'<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', re.I | re.S)


def _csv_safe_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """Reject non-http(s), credentials in URL, localhost, and private/loopback/link-local IPs."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False, "invalid_url"
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False, "unsupported_scheme"
    if parsed.username or parsed.password:
        return False, "credentials_not_allowed"
    host = parsed.hostname.strip().lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal")):
        return False, "blocked_local_host"
    try:
        ip_obj = ipaddress.ip_address(host)
        if not ip_obj.is_global:
            return False, "blocked_private_ip"
        return True, ""
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        return False, "dns_failed"
    for _fam, _type, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            if not ip_obj.is_global:
                return False, "blocked_private_ip"
        except ValueError:
            return False, "invalid_resolved_ip"
    return True, ""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        ok, _reason = is_safe_public_url(resolved)
        if not ok:
            return None
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def _build_opener():
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx),
        _SafeRedirectHandler(),
    )


def fetch(url: str, *, opener=None) -> tuple[str | None, str]:
    ok, reason = is_safe_public_url(url)
    if not ok:
        return None, f"blocked:{reason}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        transport = opener or _build_opener()
        with transport.open(req, timeout=12) as resp:
            raw = resp.read(1_500_000)
            cs = resp.headers.get_content_charset() or "utf-8"
            try:
                return raw.decode(cs, errors="replace"), resp.geturl()
            except LookupError:
                return raw.decode("utf-8", errors="replace"), resp.geturl()
    except Exception as e:
        return None, str(e)[:80]


def phones(text: str) -> list[str]:
    out: list[str] = []
    for m in PHONE.finditer(text):
        before = text[max(0, m.start() - 20) : m.start()].lower()
        if "fax" in before or "팩스" in before or "f." in before[-4:]:
            continue
        p = re.sub(r"[.)\s]", "-", m.group(1)).replace("--", "-")
        if p not in out:
            out.append(p)
    return out


def parse(html: str, base: str) -> dict[str, Any]:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    plain = re.sub(r"<[^>]+>", " ", text)
    tel = [urllib.parse.unquote(t) for t in re.findall(r'href=["\']tel:([^"\']+)', html, re.I)]
    ph: list[str] = []
    for p in tel + phones(plain):
        p = re.sub(r"[^\d-]", "", p)
        if len(re.sub(r"\D", "", p)) >= 8 and p not in ph:
            ph.append(p)
    contact_pages: list[str] = []
    for href, label in A_TAG.findall(html):
        lab = re.sub(r"<[^>]+>", "", label).strip()
        if CONTACT_WORDS.search(lab) or re.search(r"contact|inquiry|qna|cs|counsel|board.*(qa|qna)", href, re.I):
            u = urllib.parse.urljoin(base, href)
            if (
                u.startswith(("http://", "https://"))
                and u not in contact_pages
                and not re.search(r"kakao|naver|instagram|facebook|youtube|javascript", u)
            ):
                contact_pages.append(u)
    return {
        "ph": ph[:4],
        "kakao": sorted(set(KAKAO.findall(html)))[:2],
        "talk": sorted(set(TALK.findall(html)))[:2],
        "insta": sorted(set(INSTA.findall(html)))[:1],
        "widget": [k for k, v in WIDGET.items() if v in html],
        "pages": contact_pages[:3],
        "has_email": bool(EMAIL.search(plain)),
    }


def work(r: dict[str, str], *, opener=None) -> dict[str, Any]:
    html, final = fetch(r["hp"], opener=opener)
    res: dict[str, Any] = {"rid": r["rid"], "co": r["co"], "hp": r["hp"], "ok": bool(html), "err": "" if html else final}
    if not html:
        return res
    p = parse(html, final)
    email_page = final if p["has_email"] else ""
    if p["pages"]:
        h2, f2 = fetch(p["pages"][0], opener=opener)
        if h2:
            p2 = parse(h2, f2)
            for k in ("ph", "kakao", "talk", "insta", "widget"):
                p[k] = list(dict.fromkeys(p[k] + p2[k]))[:4]
            if p2["has_email"] and not email_page:
                email_page = f2
    res.update({k: " | ".join(v) for k, v in p.items() if isinstance(v, list)})
    res["email_page"] = email_page
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="리드 홈페이지 공개 연락 창구 수집기 (이메일 자동 수집 금지, SSRF/TLS 안전)")
    ap.add_argument("input_csv", help="입력 CSV (id, lead, homepage)")
    ap.add_argument("output_csv", help="출력 CSV 경로")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    rows: list[dict[str, str]] = []
    with open(args.input_csv, encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            hp = (x.get("homepage") or x.get("hp") or "").strip()
            if hp and not hp.startswith(("http://", "https://")):
                hp = "https://" + hp
            if hp:
                rows.append({"rid": x.get("id") or x.get("lead", ""), "co": x.get("lead", ""), "hp": hp})

    with ThreadPoolExecutor(max_workers=max(1, min(16, args.workers))) as ex:
        results = list(ex.map(work, rows))

    cols = ["rid", "co", "hp", "ok", "err", "ph", "kakao", "talk", "insta", "widget", "pages", "email_page"]
    with open(args.output_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for x in results:
            w.writerow({k: _csv_safe_cell(x.get(k, "")) for k in cols})

    ok = [x for x in results if x["ok"]]
    print(
        "sites", len(rows), "ok", len(ok),
        "phone", sum(1 for x in ok if x.get("ph")),
        "kakao", sum(1 for x in ok if x.get("kakao")),
        "talk", sum(1 for x in ok if x.get("talk")),
        "insta", sum(1 for x in ok if x.get("insta")),
        "contact_page", sum(1 for x in ok if x.get("pages")),
        "email_page", sum(1 for x in ok if x.get("email_page")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
