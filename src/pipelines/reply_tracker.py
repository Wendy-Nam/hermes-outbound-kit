#!/usr/bin/env python3
"""reply_tracker.py — GTMOS-inspired 11-label reply classifier, positive reply rate tracker & auto-suppression.

Zero external dependencies (Python 3.11+ stdlib). Optional TypeSafe AI Jev acceleration.
Features:
- Classifies inbound replies (CSV/JSON/MBOX) into GTMOS's 11-label taxonomy:
  positive_interested, positive_soft, positive_referral, neutral_question,
  negative_notnow, negative_notfit, negative_hostile, unsubscribe, ooo, bounce, other
- Treats reply text strictly as untrusted data (no prompt injection execution)
- Deduplicates to first reply per lead, excludes OOO & bounces from net denominator
- Computes Positive Reply Rate (north-star), hostile risk (>0.3%), and unsubscribe risk (>2%)
- Automatically appends unsubscribe / bounce / hostile contacts to $HERMES_HOME/do-not-contact.txt
- Writes Obsidian GTM/Results.md and appends campaign takeaways to GTM/LEARNINGS.md
"""
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import paths  # noqa: E402
import sources  # noqa: E402
import style_analyzer  # noqa: E402

LABELS = (
    "positive_interested",
    "positive_soft",
    "positive_referral",
    "neutral_question",
    "negative_notnow",
    "negative_notfit",
    "negative_hostile",
    "unsubscribe",
    "ooo",
    "bounce",
    "other",
)
POSITIVE_LABELS = {"positive_interested", "positive_soft", "positive_referral"}
SUPPRESS_LABELS = {"unsubscribe", "bounce", "negative_hostile"}

# Ordered heuristic patterns (specific automated/suppression states checked first)
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bounce", re.compile(
        r"(delivery\s+(?:has\s+)?failed|undeliverable|address\s+not\s+found|550\s+5\.1\.1|"
        r"mailbox\s+unavailable|mailer-daemon|user\s+unknown|수신\s*불가|전송\s*실패|존재하지\s*않는\s*계정)", re.I
    )),
    ("ooo", re.compile(
        r"(out\s+of\s+(?:the\s+)?office|automatic\s+reply|auto[- ]?reply|on\s+(?:annual\s+)?leave|"
        r"on\s+vacation|부재중|자동\s*응답|휴가\s*중|출장\s*중으로\s*회신이)", re.I
    )),
    ("unsubscribe", re.compile(
        r"(unsubscribe|remove\s+me|take\s+me\s+off|stop\s+emailing|do\s+not\s+contact|"
        r"opt[- ]?out|수신\s*거부|메일\s*리스트에서\s*제외|더\s*이상\s*(?:연락|메일)\s*(?:주지|보내지)\s*마)", re.I
    )),
    ("negative_hostile", re.compile(
        r"(spam|report(?:ed|ing)?\s+you|harass|never\s+contact|scam|스팸\s*신고|신고하겠|불쾌하)", re.I
    )),
    ("positive_referral", re.compile(
        r"(cc['’]?d|ccing|looping\s+in|reach\s+out\s+to|talk\s+to\s+our|forward(?:ed|ing)\s+this\s+to|"
        r"담당자(?:님)?(?:께|에게)\s*(?:전달|공유)|참조(?:에|로)\s*넣어|다른\s*담당자|해당\s*업무는\s*.+?(?:님|팀))", re.I
    )),
    ("positive_interested", re.compile(
        r"(let['’]?s\s+(?:chat|talk|connect|meet)|book\s+a\s+(?:call|time|demo)|schedule\s+a|"
        r"happy\s+to\s+(?:chat|meet|hop\s+on)|interested\s+in\s+(?:learning|seeing|a\s+demo)|"
        r"미팅\s*(?:가능|잡|요청|진행)|데모\s*(?:요청|보고|가능)|통화\s*가능|시간\s*(?:괜찮|가능)|견적\s*(?:요청|부탁))", re.I
    )),
    ("positive_soft", re.compile(
        r"(send\s+(?:me\s+)?(?:the|more|that)\s+(?:info|deck|1-?pager|details|checklist|sheet)|"
        r"자료\s*(?:먼저\s*)?(?:보내|공유|부탁)|소개서\s*(?:보내|공유)|참고\s*자료|검토해\s*보겠)", re.I
    )),
    ("negative_notnow", re.compile(
        r"(not\s+(?:a\s+priority|right\s+now)|next\s+quarter|check\s+back\s+in|budget\s+(?:is\s+)?frozen|"
        r"지금은\s*(?:계획|여력|우선순위)이?\s*없|다음\s*분기|하반기|내년에|시기가\s*맞지)", re.I
    )),
    ("negative_notfit", re.compile(
        r"(not\s+interested|no\s+thanks|already\s+(?:have|use|working\s+with)|we\s+build\s+in-?house|"
        r"관심\s*없|필요\s*없|이미\s*(?:사용|도입|거래)|자체\s*구축|해당\s*사항\s*없)", re.I
    )),
    ("neutral_question", re.compile(
        r"(\?|how\s+much|pricing|what\s+does|can\s+you\s+explain|비용|가격|어떻게\s*연동|지원\s*여부)", re.I
    )),
)


def classify_reply(
    body: str,
    *,
    subject: str = "",
    use_jev: bool = False,
    home: str | Path | None = None,
    opener=None,
) -> dict[str, Any]:
    """Classify one reply into GTMOS's 11-label taxonomy (local deterministic + optional Jev)."""
    blob = f"{subject or ''}\n{body or ''}".strip()
    label = "other"
    confidence = 0.5
    engine = "local-rules"

    for cand_label, rx in _RULES:
        if rx.search(blob):
            label = cand_label
            confidence = 0.85 if cand_label in {"bounce", "ooo", "unsubscribe"} else 0.78
            break

    if use_jev:
        try:
            import jev_client
            api_key = jev_client.resolve_api_key(home)
            if api_key:
                # Always preserve deterministic bounce/ooo/unsubscribe detections; let Jev refine ambiguous human replies
                if label not in {"bounce", "ooo", "unsubscribe"}:
                    jev_res = jev_client.classify_reply_with_jev(
                        body, subject=subject, api_key=api_key, opener=opener
                    )
                    if jev_res.get("label") in LABELS and jev_res.get("confidence", 0) >= 0.65:
                        label = jev_res["label"]
                        confidence = jev_res["confidence"]
                        engine = "jev"
        except Exception:
            pass

    return {
        "label": label,
        "confidence": confidence,
        "engine": engine,
        "is_positive": label in POSITIVE_LABELS,
        "needs_suppression": label in SUPPRESS_LABELS,
    }


def load_replies_file(path: str | Path) -> list[dict[str, str]]:
    """Load inbound replies from CSV, JSON, or MBOX."""
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"읽을 수 있는 파일이 아닙니다: {path}")
    suf = target.suffix.lower()
    if suf == ".mbox":
        msgs = style_analyzer.load_mbox_messages(target, limit=500, skip_replies=False)
        return [
            {
                "lead_id": f"mbox-{i}",
                "company": "",
                "email": "",
                "subject": m.get("subject", ""),
                "body": m.get("body", ""),
                "angle": "",
                "date": m.get("date", ""),
            }
            for i, m in enumerate(msgs, 1)
        ]
    if suf == ".json":
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        rows = raw.get("replies", raw) if isinstance(raw, dict) else raw
    else:
        with target.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))

    out: list[dict[str, str]] = []
    for idx, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        email_addr = sources.clean_text(row.get("email") or row.get("Email") or row.get("from") or "")
        company = sources.clean_text(row.get("company") or row.get("Company") or "")
        lead_id = sources.clean_text(row.get("lead_id") or email_addr or company or f"reply-{idx}")
        out.append({
            "lead_id": lead_id,
            "company": company,
            "email": email_addr,
            "subject": sources.clean_text(row.get("subject") or row.get("Subject") or ""),
            "body": str(row.get("body") or row.get("Body") or row.get("reply") or row.get("text") or "").strip(),
            "angle": sources.clean_text(row.get("angle") or row.get("Angle") or row.get("signal") or ""),
            "date": sources.clean_text(row.get("date") or row.get("Date") or ""),
        })
    return out


def apply_auto_suppression(suppressed_entries: list[dict[str, str]], home: str | Path) -> dict[str, Any]:
    """Append unsubscribe/bounce/hostile companies & domains to $HERMES_HOME/do-not-contact.txt safely."""
    home_path = Path(home).expanduser().absolute()
    home_path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(home_path, 0o700)
    dnc_path = home_path / "do-not-contact.txt"
    existing_lines = dnc_path.read_text(encoding="utf-8").splitlines() if dnc_path.is_file() else [
        "# 연락 금지(Do-Not-Contact) 회사·도메인 목록 — 한 줄에 하나",
    ]
    existing_keys = {
        sources._norm_company_key(l.strip())
        for l in existing_lines if l.strip() and not l.strip().startswith("#")
    }
    added: list[str] = []
    for item in suppressed_entries:
        token = item.get("company") or item.get("email") or ""
        key = sources._norm_company_key(token)
        if token and key and key not in existing_keys:
            existing_keys.add(key)
            existing_lines.append(token)
            added.append(token)
    if added or not dnc_path.is_file():
        dnc_path.write_text("\n".join(existing_lines).rstrip() + "\n", encoding="utf-8")
        if os.name == "posix":
            os.chmod(dnc_path, 0o600)

    log_path = home_path / "suppression-log.jsonl"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if suppressed_entries:
        with log_path.open("a", encoding="utf-8") as fh:
            for item in suppressed_entries:
                fh.write(json.dumps({
                    "ts": now,
                    "company": item.get("company", ""),
                    "reason": item.get("reason", ""),
                }, ensure_ascii=False) + "\n")
        if os.name == "posix":
            os.chmod(log_path, 0o600)
    return {"dnc_path": str(dnc_path), "added": added, "added_count": len(added)}


def score_campaign_replies(
    replies: list[dict[str, str]],
    *,
    total_sent: int = 0,
    campaign_name: str = "outbound-campaign",
    home: str | Path | None = None,
    vault: str | Path | None = None,
    apply_suppression: bool = False,
    use_jev: bool = False,
    opener=None,
) -> dict[str, Any]:
    """Deduplicate to first reply per lead, classify, score Positive Reply Rate, and update Vault/DNC."""
    first_per_lead: list[dict[str, str]] = []
    seen_leads: set[str] = set()
    for r in replies:
        lid = (r.get("lead_id") or "").casefold()
        if lid and lid in seen_leads:
            continue
        if lid:
            seen_leads.add(lid)
        first_per_lead.append(r)

    classified: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    angle_pos: Counter[str] = Counter()
    angle_total: Counter[str] = Counter()
    suppress_candidates: list[dict[str, str]] = []

    for r in first_per_lead:
        cls = classify_reply(r.get("body", ""), subject=r.get("subject", ""), use_jev=use_jev, home=home, opener=opener)
        counts[cls["label"]] += 1
        angle = r.get("angle") or "unspecified"
        if cls["label"] not in {"ooo", "bounce"}:
            angle_total[angle] += 1
            if cls["is_positive"]:
                angle_pos[angle] += 1
        if cls["needs_suppression"]:
            suppress_candidates.append({
                "company": r.get("company") or "",
                "email": r.get("email") or "",
                "reason": cls["label"],
            })
        classified.append({**r, "classification": cls})

    ooo_n = counts["ooo"]
    bounce_n = counts["bounce"]
    net_replies = sum(c for k, c in counts.items() if k not in {"ooo", "bounce"})
    positive_n = sum(counts[k] for k in POSITIVE_LABELS)
    hostile_n = counts["negative_hostile"]
    unsub_n = counts["unsubscribe"]

    denom = max(0, total_sent - bounce_n) if total_sent > 0 else net_replies
    positive_rate = round((positive_n / denom) * 100, 2) if denom > 0 else 0.0
    hostile_rate = round((hostile_n / denom) * 100, 2) if denom > 0 else 0.0
    unsub_rate = round((unsub_n / denom) * 100, 2) if denom > 0 else 0.0

    # GTMOS Benchmarks
    risk_flags: list[str] = []
    if total_sent and total_sent < 500:
        risk_flags.append(f"표본 부족({total_sent}건 < 500건): 긍정 회신율 추세는 참고치로만 해석하세요.")
    if total_sent > 0 and hostile_rate > 0.3:
        risk_flags.append(f"부정/항의 비율 높음({hostile_rate}% > 0.3%): 타깃팅·카피 즉시 점검 필요.")
    if total_sent > 0 and unsub_rate > 2.0:
        risk_flags.append(f"수신거부 비율 높음({unsub_rate}% > 2.0%): 발신 도메인 평판 보호를 위해 일시 중지 권장.")

    benchmark = (
        "Great (≥2%)" if total_sent > 0 and positive_rate >= 2.0
        else "Good (≥1%)" if total_sent > 0 and positive_rate >= 1.0
        else "Needs tuning (<1%)" if total_sent > 0
        else "total_sent 미입력(답장 중 긍정 비율 기준)"
    )

    suppression_res = apply_auto_suppression(suppress_candidates, home) if (apply_suppression and home) else None

    angle_summary = [
        {
            "angle": ang,
            "net_replies": tot,
            "positive": angle_pos[ang],
            "positive_share_pct": round((angle_pos[ang] / tot) * 100, 1) if tot else 0.0,
        }
        for ang, tot in angle_total.most_common(10)
    ]

    report = {
        "schema_version": "hermes_reply_score/v1",
        "campaign_name": campaign_name,
        "total_sent": total_sent,
        "replies_processed": len(first_per_lead),
        "net_replies": net_replies,
        "ooo_excluded": ooo_n,
        "bounces_excluded": bounce_n,
        "positive_replies": positive_n,
        "positive_reply_rate_pct": positive_rate,
        "hostile_rate_pct": hostile_rate,
        "unsubscribe_rate_pct": unsub_rate,
        "benchmark": benchmark,
        "label_breakdown": dict(counts),
        "angle_performance": angle_summary,
        "risk_flags": risk_flags,
        "action_needed_positive": [
            {"company": c["company"], "label": c["classification"]["label"], "subject": c["subject"]}
            for c in classified if c["classification"]["is_positive"]
        ],
        "suppression_candidates_count": len(suppress_candidates),
        "suppression_applied": suppression_res,
    }

    if vault:
        vroot = Path(vault).expanduser().absolute()
        gtm_dir = vroot / "GTM"
        gtm_dir.mkdir(parents=True, exist_ok=True)
        now_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        res_md = (
            f"# Campaign Reply Score — {campaign_name}\n\n"
            f"- **기준일**: {now_day}\n"
            f"- **총 발송 / 유효 답장**: {total_sent or '미입력'}건 / {net_replies}건 (OOO {ooo_n} · 바운스 {bounce_n} 제외)\n"
            f"- **긍정 회신(North-Star)**: **{positive_n}건 ({positive_rate}%)** — {benchmark}\n"
            f"- **수신거부 / 항의**: {unsub_n}건 ({unsub_rate}%) / {hostile_n}건 ({hostile_rate}%)\n\n"
            "## 라벨 분포\n"
            + "\n".join(f"- `{k}`: {v}건" for k, v in counts.most_common())
            + "\n\n## 각도(Angle)별 반응\n"
            + ("\n".join(f"- **{a['angle']}**: 긍정 {a['positive']}/{a['net_replies']}건 ({a['positive_share_pct']}%)" for a in angle_summary) or "- 기록 없음")
            + ("\n\n## 경고\n" + "\n".join(f"- {w}" for w in risk_flags) if risk_flags else "")
            + "\n"
        )
        results_path = gtm_dir / "Results.md"
        results_path.write_text(res_md, encoding="utf-8")

        learn_path = gtm_dir / "LEARNINGS.md"
        if not learn_path.exists():
            learn_path.write_text("# Outbound Campaign Learnings\n\n", encoding="utf-8")
        top_angle = angle_summary[0]["angle"] if angle_summary else "미지정"
        entry = (
            f"## {now_day} — {campaign_name}\n"
            f"- 긍정 회신: {positive_n}건 ({positive_rate}%, {benchmark}) · 수신거부 {unsub_n}건 · 바운스 {bounce_n}건\n"
            f"- 최다 반응 각도: `{top_angle}`\n\n"
        )
        with learn_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)
        report["vault_files"] = {"results": str(results_path), "learnings": str(learn_path)}

    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GTMOS식 답장 11라벨 분류 · 긍정 회신율 · 자동 DNC 차단 · LEARNINGS 누적")
    ap.add_argument("--input", required=True, help="답장 CSV / JSON / MBOX 파일 경로")
    ap.add_argument("--sent", type=int, default=0, help="캠페인 총 발송 건수(긍정 회신율 계산용)")
    ap.add_argument("--campaign", default="outbound-campaign")
    ap.add_argument("--home")
    ap.add_argument("--vault")
    ap.add_argument("--apply-suppression", action="store_true", help="수신거부/바운스/항의 대상을 $HERMES_HOME/do-not-contact.txt에 자동 추가")
    ap.add_argument("--use-jev", action="store_true", help="TYPESAFE_API_KEY가 있으면 모호한 답장을 Jev로 보정")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        replies = load_replies_file(args.input)
        res = score_campaign_replies(
            replies,
            total_sent=args.sent,
            campaign_name=args.campaign,
            home=paths.normalize_home(args.home),
            vault=args.vault,
            apply_suppression=args.apply_suppression,
            use_jev=args.use_jev,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
