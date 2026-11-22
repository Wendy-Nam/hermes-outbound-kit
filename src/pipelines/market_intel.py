#!/usr/bin/env python3
"""Competitor Reverse-Engineering Market Intelligence Ledger & Lookalike Target Queue.

Core operational philosophy:
- Do NOT blindly treat competitor case studies as a "rip-and-replace" target list.
- Instead:
  1) Collect competitor case studies/announcements from CSV/JSON, live RSS/Atom feeds,
     or public web pages (with Crawl4AI-first JS rendering fallback).
  2) Deduplicate strictly by signal ID and canonical URL (0 duplicates) and track baseline
     state (`.competitor-signals-state.json`) so daily cron runs highlight ONLY new signals.
  3) Extract WHY the customer paid (problem / industry / trigger) and build a lookalike
     target queue with low-friction partial-supplement entry angles.
"""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html as html_lib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import urllib.parse
import xml.etree.ElementTree as ET

import sources
import web_extract

ROOT = Path(__file__).resolve().parents[2]

PAIN_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("해외 파견·출장 안전/의료 대응", ("evacuation", "medical", "expat", "travel risk", "duty of care", "offshore", "해외", "주재원", "출장", "후송", "안전", "hse", "ehs"), "기존 글로벌 계약에서 빠진 국가·프로젝트·한국 귀환 인계 구간부터 부분 보완 제안"),
    ("클라우드·보안·컴플라이언스", ("security", "soc2", "iso 27001", "cloud", "zero trust", "보안", "클라우드", "컴플라이언스"), "신규 규제·인증 대응이 급한 팀부터 작은 범위 검증 제안"),
    ("제조·설비·물류 자동화", ("factory", "plant", "mes", "plc", "logistics", "supply chain", "제조", "공장", "물류", "스마트팩토리"), "특정 라인·거점 1곳에서 짧은 시험 운영 후 확대 제안"),
    ("데이터·AI·업무 자동화", ("ai", "data", "analytics", "automation", "mlops", "데이터", "자동화", "파이프라인"), "반복 수작업이 가장 큰 1개 워크플로부터 먼저 적용 제안"),
)

_LINK_HEADING_RE = re.compile(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _norm_url(url: str) -> str:
    cleaned = sources.canonical_url(url or "")
    return cleaned.rstrip("/").lower() if cleaned else ""


def _infer_pain_and_angle(text: str) -> tuple[str, str]:
    low = (text or "").lower()
    for pain, keywords, angle in PAIN_RULES:
        if any(k in low for k in keywords):
            return pain, angle
    return "핵심 운영 과제 해결", "전체 교체 대신 기존 계약·업무에서 비어 있는 1개 구간부터 작은 시험 운영 제안"


def parse_rss_signals(raw_xml: bytes | str, *, competitor_name: str = "", default_industry: str = "일반 B2B") -> list[dict[str, Any]]:
    """Parse RSS 2.0 / Atom XML safely (rejects DOCTYPE/ENTITY to block XXE)."""
    text = raw_xml.decode("utf-8-sig", errors="replace") if isinstance(raw_xml, bytes) else (raw_xml or "")
    if re.search(r"<!(?:DOCTYPE|ENTITY)\b", text, re.I):
        raise ValueError("보안상 DOCTYPE/ENTITY가 포함된 XML 피드는 거부합니다.")
    root = ET.fromstring(text.strip())
    items: list[dict[str, Any]] = []

    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    for elem in root.iter():
        tag = _local(elem.tag)
        if tag not in ("item", "entry"):
            continue
        title, link, summary, pub_date = "", "", "", ""
        for child in elem:
            ctag = _local(child.tag)
            ctext = (child.text or "").strip()
            if ctag == "title" and not title:
                title = html_lib.unescape(re.sub(r"\s+", " ", _TAG_STRIP_RE.sub(" ", ctext))).strip()
            elif ctag == "link" and not link:
                href = (child.attrib.get("href") or "").strip()
                link = href or ctext
            elif ctag in ("description", "summary", "content") and not summary:
                summary = html_lib.unescape(re.sub(r"\s+", " ", _TAG_STRIP_RE.sub(" ", ctext))).strip()
            elif ctag in ("pubdate", "published", "updated") and not pub_date:
                pub_date = ctext
        if title:
            items.append({
                "competitor": competitor_name or "경쟁사",
                "industry": default_industry,
                "title": title[:200],
                "summary": summary[:400],
                "url": link,
                "date": pub_date[:40],
            })
    return items


def fetch_competitor_rss(
    rss_urls: list[str],
    *,
    competitor_name: str = "",
    opener=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in rss_urls:
        u = url.strip()
        if not u:
            continue
        status, raw, err = sources.fetch_bytes(u, "competitor-rss", timeout=20, opener=opener)
        if status != "ok" or not raw:
            errors.append(f"{u}: {status} ({err or 'fetch failed'})")
            continue
        try:
            out.extend(parse_rss_signals(raw, competitor_name=competitor_name))
        except Exception as exc:
            errors.append(f"{u}: parse_error ({exc})")
    return out, errors


def parse_html_case_studies(raw_html: str | bytes, base_url: str, *, competitor_name: str = "") -> list[dict[str, Any]]:
    """Extract likely case-study/news links and titles from a public competitor page."""
    text = raw_html.decode("utf-8-sig", errors="replace") if isinstance(raw_html, bytes) else (raw_html or "")
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for m in _LINK_HEADING_RE.finditer(text):
        href = html_lib.unescape(m.group(1).strip())
        label = html_lib.unescape(re.sub(r"\s+", " ", _TAG_STRIP_RE.sub(" ", m.group(2)))).strip()
        if len(label) < 12 or len(label) > 200:
            continue
        resolved = urllib.parse.urljoin(base_url, href)
        norm = _norm_url(resolved)
        if not norm or norm in seen_urls:
            continue
        seen_urls.add(norm)
        out.append({
            "competitor": competitor_name or (urllib.parse.urlsplit(base_url).hostname or "경쟁사"),
            "industry": "공개 사례",
            "title": label,
            "summary": "",
            "url": resolved,
            "date": "",
        })
    return out[:40]


def fetch_competitor_pages(
    urls: list[str],
    *,
    competitor_name: str = "",
    render_js: bool = False,
    home: str | Path | None = None,
    opener=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in urls:
        u = url.strip()
        if not u:
            continue
        status, raw, err = sources.fetch_bytes(u, "competitor-page", timeout=20, opener=opener)
        if status != "ok" or not raw:
            errors.append(f"{u}: {status} ({err or 'fetch failed'})")
            continue
        parsed = parse_html_case_studies(raw, u, competitor_name=competitor_name)
        if render_js or (not parsed and web_extract.looks_like_js_shell(raw)):
            rendered = web_extract.render_js_page(u, home=home, formats=("html", "markdown"), opener=opener)
            if rendered.get("status") == "ok" and (rendered.get("html") or rendered.get("markdown")):
                html_src = rendered.get("html") or ""
                if html_src:
                    parsed = parse_html_case_studies(html_src, u, competitor_name=competitor_name)
                elif rendered.get("markdown"):
                    for line in rendered["markdown"].splitlines():
                        m = re.search(r"\[([^\]]{12,180})\]\((https?://[^)]+)\)", line)
                        if m:
                            parsed.append({
                                "competitor": competitor_name or "경쟁사",
                                "industry": "공개 사례",
                                "title": m.group(1).strip(),
                                "summary": "",
                                "url": m.group(2).strip(),
                                "date": "",
                            })
            elif rendered.get("status") in ("missing_key", "js_renderer_unavailable") and not parsed:
                errors.append(f"{u}: js_shell_detected ({rendered.get('hint') or 'Crawl4AI 필요'})")
        out.extend(parsed)
    return out, errors


def load_competitor_signals(
    *,
    file_path: str | Path | None = None,
    records: list[dict[str, Any]] | None = None,
    rss_urls: list[str] | None = None,
    page_urls: list[str] | None = None,
    competitor_name: str = "",
    render_js: bool = False,
    home: str | Path | None = None,
    opener=None,
) -> dict[str, Any]:
    """Load and strictly deduplicate competitor signals by signal ID and canonical URL."""
    raw_items: list[dict[str, Any]] = []
    errors: list[str] = []
    if records is not None:
        raw_items.extend(records)
    if file_path:
        target = Path(file_path).expanduser().absolute()
        if target.suffix.lower() == ".json":
            loaded = json.loads(target.read_text(encoding="utf-8-sig"))
            items = loaded.get("items", loaded) if isinstance(loaded, dict) else loaded
            if isinstance(items, list):
                raw_items.extend(x for x in items if isinstance(x, dict))
        else:
            with target.open("r", encoding="utf-8-sig", newline="") as fh:
                raw_items.extend(dict(r) for r in csv.DictReader(fh))
    if rss_urls:
        rss_items, rss_errs = fetch_competitor_rss(rss_urls, competitor_name=competitor_name, opener=opener)
        raw_items.extend(rss_items)
        errors.extend(rss_errs)
    if page_urls:
        pg_items, pg_errs = fetch_competitor_pages(
            page_urls, competitor_name=competitor_name, render_js=render_js, home=home, opener=opener
        )
        raw_items.extend(pg_items)
        errors.extend(pg_errs)

    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []
    dup_ids = 0
    dup_urls = 0

    for raw in raw_items:
        title = re.sub(r"\s+", " ", str(raw.get("title") or raw.get("headline") or "")).strip()
        summary = re.sub(r"\s+", " ", str(raw.get("summary") or raw.get("description") or "")).strip()
        url = _norm_url(str(raw.get("url") or raw.get("link") or ""))
        comp = re.sub(r"\s+", " ", str(raw.get("competitor") or competitor_name or "경쟁사")).strip()
        industry = re.sub(r"\s+", " ", str(raw.get("industry") or raw.get("segment") or "일반 B2B")).strip()
        sig_id = str(raw.get("id") or raw.get("signal_id") or "").strip()
        if not sig_id:
            sig_id = "sig-" + hashlib.sha256(f"{comp}|{title}|{url}".encode("utf-8")).hexdigest()[:12]

        if sig_id in seen_ids:
            dup_ids += 1
            continue
        if url and url in seen_urls:
            dup_urls += 1
            continue
        seen_ids.add(sig_id)
        if url:
            seen_urls.add(url)

        pain, angle = _infer_pain_and_angle(f"{title} {summary} {industry}")
        unique.append({
            "id": sig_id,
            "competitor": comp,
            "title": title or "(제목 없음)",
            "industry": industry,
            "summary": summary[:400],
            "url": url,
            "date": str(raw.get("date") or raw.get("published_at") or "").strip(),
            "pain_theme": pain,
            "entry_angle": angle,
        })

    return {
        "signals": unique,
        "duplicate_ids_dropped": dup_ids,
        "duplicate_urls_dropped": dup_urls,
        "errors": errors,
    }


def export_market_intel_to_vault(
    loaded: dict[str, Any],
    vault_dir: str | Path,
    *,
    target_region: str = "한국 기업",
    initialize: bool = False,
) -> dict[str, Any]:
    """Write stateful Competitor-Signals.md ledger (with baseline diff) and Lookalike-Queue.md."""
    vault = Path(vault_dir).expanduser().absolute()
    mi_dir = vault / "Market Intelligence"
    mi_dir.mkdir(parents=True, exist_ok=True)
    state_file = mi_dir / ".competitor-signals-state.json"

    prev_ids: set[str] = set()
    if state_file.is_file() and not initialize:
        try:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(saved.get("ids"), list):
                prev_ids = set(saved["ids"])
        except (OSError, ValueError):
            prev_ids = set()

    signals = loaded["signals"]
    new_signals: list[dict[str, Any]] = []
    for s in signals:
        is_new = (s["id"] not in prev_ids) and not initialize
        s["diff_status"] = "신규" if is_new else ("기준선" if initialize else "기존")
        if is_new:
            new_signals.append(s)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_ids = sorted(prev_ids | {s["id"] for s in signals})
    fd, staged = tempfile.mkstemp(prefix=".intel-", dir=mi_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": "hermes_competitor_intel/v1", "updated_at": now_iso, "ids": all_ids}, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(staged, state_file)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)

    sig_rows = []
    for s in signals:
        sig_rows.append(
            f"| {s['id']} | {s['diff_status']} | {s['competitor']} | {s['industry']} | {s['title'][:50]} | {s['pain_theme']} |"
        )
    ledger_md = (
        "# 경쟁사 신호 원장 (Competitor Signals)\n\n"
        "> 경쟁사 고객을 그대로 빼앗기 위한 목록이 아닙니다. 고객이 비용을 쓴 문제 유형을 파악해 비슷한 타깃을 찾는 근거 원장입니다.\n\n"
        f"- **갱신 시각**: {now_iso}\n"
        f"- **고유 신호**: {len(signals)}건 (신규 {len(new_signals)}건 · 중복 ID 제거 {loaded['duplicate_ids_dropped']}건 · 중복 URL 제거 {loaded['duplicate_urls_dropped']}건)\n\n"
        "| 신호 ID | 상태 | 경쟁사 | 업종·세그먼트 | 공개 사례·발표 | 고객이 돈을 쓴 문제 |\n"
        "|---|---|---|---|---|---|\n"
        + ("\n".join(sig_rows) if sig_rows else "| — | — | — | — | 수집된 신호 없음 | — |")
        + "\n"
    )
    ledger_path = mi_dir / "Competitor-Signals.md"
    ledger_path.write_text(ledger_md, encoding="utf-8")

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for s in signals:
        key = (s["industry"], s["pain_theme"])
        if key not in groups:
            groups[key] = {
                "industry": s["industry"],
                "pain_theme": s["pain_theme"],
                "entry_angle": s["entry_angle"],
                "count": 0,
                "search_query": f'"{s["industry"]}" {target_region} "{s["pain_theme"].split("·")[0]}"',
            }
        groups[key]["count"] += 1

    q_rows = []
    for g in sorted(groups.values(), key=lambda x: -x["count"]):
        q_rows.append(
            f"| {g['industry']} | {g['pain_theme']} | {g['count']}건 | `{g['search_query']}` | {g['entry_angle']} |"
        )
    queue_md = (
        "# 비슷한 고객 발굴 큐 (Lookalike Queue)\n\n"
        "> 경쟁사 사례에서 확인된 문제를 바탕으로, 같은 고민을 가진 비슷한 타깃을 찾고 **부분 보완(작은 시험 운영)**으로 접근합니다.\n\n"
        "| 세그먼트 | 확인된 문제 | 근거 신호 | 추천 탐색 키워드 | 추천 진입 방식 |\n"
        "|---|---|---|---|---|\n"
        + ("\n".join(q_rows) if q_rows else "| — | — | 0건 | — | — |")
        + "\n"
    )
    queue_path = mi_dir / "Lookalike-Queue.md"
    queue_path.write_text(queue_md, encoding="utf-8")

    readme_path = mi_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# Market Intelligence 안내\n\n"
            "- 경쟁사 신호 원장: [[Competitor-Signals]]\n"
            "- 비슷한 고객 발굴 큐: [[Lookalike-Queue]]\n"
            "- 나라장터 발주계획·공고: [[Procurement/G2B 발주계획 원장]]\n",
            encoding="utf-8",
        )

    return {
        "ledger": str(ledger_path),
        "lookalike_queue": str(queue_path),
        "state_path": str(state_file),
        "signal_count": len(signals),
        "new_signals_count": len(new_signals),
        "lookalike_segments": len(groups),
        "duplicate_ids": 0,
        "duplicate_urls": 0,
        "errors": loaded.get("errors", []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="경쟁사 역추적 마켓 인텔리전스 원장 & 비슷한 타깃 발굴 큐 생성")
    parser.add_argument("--input", default="", help="경쟁사 신호 CSV/JSON 파일")
    parser.add_argument("--rss", action="append", default=[], help="경쟁사 공개 RSS/Atom 피드 URL (여러 번 지정 가능)")
    parser.add_argument("--url", action="append", default=[], help="경쟁사 공개 사례/뉴스 페이지 URL (Crawl4AI JS 렌더 폴백 지원)")
    parser.add_argument("--render-js", action="store_true", help="웹 페이지 강제 JS 렌더링 (Crawl4AI 우선)")
    parser.add_argument("--initialize", action="store_true", help="기준선 초기 저장 모드")
    parser.add_argument("--competitor", default="", help="기본 경쟁사 이름")
    parser.add_argument("--region", default="한국 기업")
    parser.add_argument("--home", default="")
    parser.add_argument("--vault", required=True, help="Obsidian 볼트 경로")
    args = parser.parse_args(argv)

    if not args.input and not args.rss and not args.url:
        parser.error("--input, --rss, --url 중 최소 하나는 지정해야 합니다.")

    loaded = load_competitor_signals(
        file_path=args.input or None,
        rss_urls=args.rss or None,
        page_urls=args.url or None,
        competitor_name=args.competitor,
        render_js=args.render_js,
        home=args.home or None,
    )
    out = export_market_intel_to_vault(loaded, args.vault, target_region=args.region, initialize=args.initialize)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
