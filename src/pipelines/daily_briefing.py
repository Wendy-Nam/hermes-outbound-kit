#!/usr/bin/env python3
"""Daily Outbound Briefing Digest Generator.

Aggregates current Obsidian vault status into a crisp, readable Korean briefing
(Daily/YYYY-MM-DD-Briefing.md + concise plain-text digest for terminal / cron / messenger):
- Live CRM lead count & 6-stage Kanban distribution
- Unsent draft count waiting for human review (with automatic_send: false guarantee)
- G2B procurement baseline & actionable items count
- Competitor Market Intelligence signal count
- Vault integrity audit summary (`crm_board.audit_vault`)
"""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import crm_board

ROOT = Path(__file__).resolve().parents[2]


def build_daily_briefing(
    vault_dir: str | Path,
    *,
    date_str: str = "",
    write_note: bool = True,
) -> dict[str, Any]:
    """Build daily Korean operational briefing from the vault and optionally save to Daily/."""
    vault = Path(vault_dir).expanduser().absolute()
    if not vault.is_dir():
        raise ValueError(f"볼트 디렉터리를 찾을 수 없습니다: {vault}")

    today = date_str.strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit = crm_board.audit_vault(vault)

    # Lead stage & unsent draft stats
    stage_counts = {s: 0 for s in crm_board.CRM_STAGES}
    unsent_drafts: list[str] = []
    sent_total = 0
    for note in crm_board._iter_live_lead_notes(vault):
        meta, _body, _errs = crm_board.parse_frontmatter(note.read_text(encoding="utf-8", errors="replace"))
        st = str(meta.get("단계") or "소싱됨").strip()
        if st in stage_counts:
            stage_counts[st] += 1
        if str(meta.get("메시지상태") or "미발송").strip() == "미발송":
            unsent_drafts.append(f"{meta.get('company') or note.parent.name} · {meta.get('name') or note.stem}")
        cnt = int(meta.get("연락횟수") or 0) if str(meta.get("연락횟수") or "0").isdigit() else 0
        sent_total += cnt

    # G2B state summary
    g2b_state_path = vault / "Market Intelligence" / "Procurement" / ".g2b-order-plan-state.json"
    g2b_total = 0
    g2b_actionable = 0
    if g2b_state_path.is_file():
        try:
            g2b_data = json.loads(g2b_state_path.read_text(encoding="utf-8"))
            items = g2b_data.get("items") or {}
            g2b_total = len(items)
            g2b_actionable = sum(1 for v in items.values() if isinstance(v, dict) and v.get("verdict") in ("적합", "추가검토"))
        except (OSError, ValueError):
            pass

    # Competitor signals summary
    comp_path = vault / "Market Intelligence" / "Competitor-Signals.md"
    comp_rows = 0
    if comp_path.is_file():
        for line in comp_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("| sig-"):
                comp_rows += 1

    stage_line = " · ".join(f"{k} {v}명" for k, v in stage_counts.items())
    audit_sum = audit["summary"]
    audit_status = "정상 (오류 0건)" if audit["status"] == "ok" else f"점검 필요 (오류 {audit_sum['total_issues']}건)"

    summary_text = (
        f"[{today} 아웃바운드 데일리 브리핑]\n"
        f"- 실사용 리드: {audit_sum['live_crm_leads']}명 ({stage_line})\n"
        f"- 승인 대기 미발송 초안: {len(unsent_drafts)}건 (실제 발송 누적 {sent_total}건)\n"
        f"- 나라장터(G2B) 감시: 기준선 {g2b_total}건 중 검토 대상 {g2b_actionable}건\n"
        f"- 경쟁사 시장정보 신호: {comp_rows}건\n"
        f"- 볼트 무결성 점검: {audit_status}\n"
    )

    note_path = None
    if write_note:
        daily_dir = vault / "Daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        note_path = daily_dir / f"{today}-Briefing.md"
        drafts_md = "\n".join(f"- [ ] {name}" for name in unsent_drafts[:20]) or "- 대기 중인 미발송 초안이 없습니다."
        issues_md = "\n".join(f"- `{it['type']}` ({it['file']}): {it['detail']}" for it in audit["issues"][:10]) or "- 발견된 오류가 없습니다."
        md = (
            f"# {today} 영업 데일리 브리핑\n\n"
            f"> 자동 발송 없음 — 오늘 검토할 리드, 발주계획, 시장 신호만 요약했습니다.\n\n"
            f"## 1. 오늘 현황 요약\n"
            f"- **실사용 CRM 리드**: {audit_sum['live_crm_leads']}명 ({stage_line})\n"
            f"- **승인 대기 초안(미발송)**: {len(unsent_drafts)}건 · **실제 발송 누적**: {sent_total}건\n"
            f"- **나라장터(G2B) 기준선**: 총 {g2b_total}건 (검토 대상 {g2b_actionable}건)\n"
            f"- **경쟁사 시장 신호**: {comp_rows}건\n"
            f"- **볼트 무결성**: {audit_status}\n\n"
            f"## 2. 오늘 검토할 미발송 초안\n"
            f"{drafts_md}\n\n"
            f"## 3. 볼트 점검 결과\n"
            f"{issues_md}\n"
        )
        note_path.write_text(md, encoding="utf-8")

    return {
        "status": "ok",
        "date": today,
        "briefing_note": str(note_path) if note_path else "",
        "summary_text": summary_text,
        "metrics": {
            "live_leads": audit_sum["live_crm_leads"],
            "stage_counts": stage_counts,
            "unsent_drafts": len(unsent_drafts),
            "sent_total": sent_total,
            "g2b_baseline": g2b_total,
            "g2b_actionable": g2b_actionable,
            "competitor_signals": comp_rows,
            "audit_issues": audit_sum["total_issues"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Obsidian 볼트 기준 데일리 아웃바운드 브리핑 생성")
    parser.add_argument("--vault", required=True)
    parser.add_argument("--date", default="")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--text", action="store_true", help="메신저/터미널용 짧은 요약 텍스트만 출력")
    args = parser.parse_args(argv)

    res = build_daily_briefing(args.vault, date_str=args.date, write_note=not args.no_write)
    if args.text:
        print(res["summary_text"])
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
