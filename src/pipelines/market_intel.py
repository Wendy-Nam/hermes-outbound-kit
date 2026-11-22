#!/usr/bin/env python3
"""Competitor Reverse-Engineering Market Intelligence Ledger & Lookalike Target Queue.

Core operational philosophy:
- Do NOT blindly treat competitor case studies as a "rip-and-replace" target list.
- Instead:
  1) Extract WHY a customer paid the competitor (problem / industry / operational trigger).
  2) Generate search queries & lookalike segments to find similar companies with the same pain.
  3) Identify coverage gaps (regions, headcount, projects, local handoff) for a low-friction
     partial-supplement pilot rather than full replacement.
- Guarantees strict ID + canonical URL deduplication (0 duplicates).
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
import json
from pathlib import Path
import re
from typing import Any

import sources

ROOT = Path(__file__).resolve().parents[2]

PAIN_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("해외 파견·출장 안전/의료 대응", ("evacuation", "medical", "expat", "travel risk", "duty of care", "offshore", "해외", "주재원", "출장", "후송", "안전", "hse", "ehs"), "기존 글로벌 계약에서 빠진 국가·프로젝트·한국 귀환 인계 구간부터 부분 보완 제안"),
    ("클라우드·보안·컴플라이언스", ("security", "soc2", "iso 27001", "cloud", "zero trust", "보안", "클라우드", "컴플라이언스"), "신규 규제·인증 대응이 급한 팀부터 작은 범위 검증 제안"),
    ("제조·설비·물류 자동화", ("factory", "plant", "mes", "plc", "logistics", "supply chain", "제조", "공장", "물류", "스마트팩토리"), "특정 라인·거점 1곳에서 짧은 시험 운영 후 확대 제안"),
    ("데이터·AI·업무 자동화", ("ai", "data", "analytics", "automation", "mlops", "데이터", "자동화", "파이프라인"), "반복 수작업이 가장 큰 1개 워크플로부터 먼저 적용 제안"),
)


def _norm_url(url: str) -> str:
    cleaned = sources.canonical_url(url or "")
    return cleaned.rstrip("/").lower() if cleaned else ""


def _infer_pain_and_angle(text: str) -> tuple[str, str]:
    low = (text or "").lower()
    for pain, keywords, angle in PAIN_RULES:
        if any(k in low for k in keywords):
            return pain, angle
    return "핵심 운영 과제 해결", "전체 교체 대신 기존 계약·업무에서 비어 있는 1개 구간부터 작은 시험 운영 제안"


def load_competitor_signals(
    *,
    file_path: str | Path | None = None,
    records: list[dict[str, Any]] | None = None,
    competitor_name: str = "",
) -> dict[str, Any]:
    """Load and strictly deduplicate competitor signals by signal ID and canonical URL."""
    raw_items: list[dict[str, Any]] = []
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
    }


def export_market_intel_to_vault(
    loaded: dict[str, Any],
    vault_dir: str | Path,
    *,
    target_region: str = "한국 기업",
) -> dict[str, Any]:
    """Write Competitor-Signals.md ledger and Lookalike-Queue.md into Obsidian vault."""
    vault = Path(vault_dir).expanduser().absolute()
    mi_dir = vault / "Market Intelligence"
    mi_dir.mkdir(parents=True, exist_ok=True)
    signals = loaded["signals"]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sig_rows = []
    for s in signals:
        sig_rows.append(
            f"| {s['id']} | {s['competitor']} | {s['industry']} | {s['title'][:50]} | {s['pain_theme']} |"
        )
    ledger_md = (
        "# 경쟁사 신호 원장 (Competitor Signals)\n\n"
        "> 경쟁사 고객을 그대로 빼앗기 위한 목록이 아닙니다. 고객이 비용을 쓴 문제 유형을 파악해 비슷한 타깃을 찾는 근거 원장입니다.\n\n"
        f"- **갱신 시각**: {now_iso}\n"
        f"- **고유 신호**: {len(signals)}건 (중복 ID 제거 {loaded['duplicate_ids_dropped']}건 · 중복 URL 제거 {loaded['duplicate_urls_dropped']}건)\n\n"
        "| 신호 ID | 경쟁사 | 업종·세그먼트 | 공개 사례·발표 | 고객이 돈을 쓴 문제 |\n"
        "|---|---|---|---|---|\n"
        + ("\n".join(sig_rows) if sig_rows else "| — | — | — | 수집된 신호 없음 | — |")
        + "\n"
    )
    ledger_path = mi_dir / "Competitor-Signals.md"
    ledger_path.write_text(ledger_md, encoding="utf-8")

    # Group by (industry, pain_theme) to build lookalike sourcing queue
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
        "signal_count": len(signals),
        "lookalike_segments": len(groups),
        "duplicate_ids": 0,
        "duplicate_urls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="경쟁사 역추적 마켓 인텔리전스 원장 & 비슷한 타깃 발굴 큐 생성")
    parser.add_argument("--input", required=True, help="경쟁사 신호 CSV/JSON 파일")
    parser.add_argument("--competitor", default="", help="기본 경쟁사 이름")
    parser.add_argument("--region", default="한국 기업")
    parser.add_argument("--vault", required=True, help="Obsidian 볼트 경로")
    args = parser.parse_args(argv)

    loaded = load_competitor_signals(file_path=args.input, competitor_name=args.competitor)
    out = export_market_intel_to_vault(loaded, args.vault, target_region=args.region)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
