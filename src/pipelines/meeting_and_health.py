#!/usr/bin/env python3
"""meeting_and_health.py — Pre-meeting 1-page brief, post-meeting recap generator, and SPF/DKIM/DMARC DNS health check.

Zero external dependencies (Python 3.11+ stdlib).
Features:
1. Pre-meeting 1-page brief (GTMOS prep-meeting): pulls Obsidian Vault evidence/account/GTM notes +
   optional live company website summary into vault/Meetings/Prep-<date>-<company>.md.
2. Post-meeting recap & follow-up (GTMOS post-meeting): parses raw meeting notes into agreed next steps,
   stated pain/requirements, and a plain 4-line recap email draft (no auto-send).
3. Sending-domain deliverability health check (GTMOS inbox-health): inspects MX, SPF, DMARC, and common
   DKIM selectors via local dig/nslookup/host DNS lookups (no external API keys required).
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
import re
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import copy_guard  # noqa: E402
import profile_bootstrap  # noqa: E402
import sources  # noqa: E402

COMMON_DKIM_SELECTORS = ("google", "selector1", "selector2", "k1", "default", "s1", "mail", "dkim")


def _safe_slug(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', " ", (name or "").strip())
    return re.sub(r"\s+", "-", cleaned)[:60] or "account"


# ---------------------------------------------------------------------------
# 1. Pre-Meeting 1-Page Brief
# ---------------------------------------------------------------------------

def _collect_vault_context(vault_dir: Path, company: str) -> dict[str, list[str]]:
    """Read existing Vault account/evidence/GTM snippets for the company (read-only)."""
    key = sources._norm_company_key(company)
    ctx: dict[str, list[str]] = {"accounts": [], "evidence": [], "gtm": [], "drafts": []}
    if not vault_dir.is_dir():
        return ctx
    for folder, bucket in (("Accounts", "accounts"), ("Evidence", "evidence"), ("GTM/Accounts", "gtm"), ("Drafts", "drafts")):
        sub = vault_dir / folder
        if not sub.is_dir():
            continue
        for md in sorted(sub.glob("*.md"))[:200]:
            text = md.read_text(encoding="utf-8", errors="replace")
            if key and (key in sources._norm_company_key(md.stem) or company.casefold() in text[:800].casefold()):
                ctx[bucket].append(f"[{md.name}]\n" + text[:1200].strip())
                if len(ctx[bucket]) >= 3:
                    break
    return ctx


def generate_meeting_prep(
    company: str,
    *,
    attendees: list[str] | None = None,
    company_url: str = "",
    goal: str = "상대 팀의 현재 업무 방식·우선순위 확인 및 적합성 판단",
    vault: str | Path | None = None,
    config: dict[str, Any] | None = None,
    opener=None,
) -> dict[str, Any]:
    """Build a concise 1-page pre-meeting brief grounded strictly in Vault + public website facts."""
    cfg = config or {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    vault_ctx = _collect_vault_context(Path(vault).expanduser().absolute(), company) if vault else {
        "accounts": [], "evidence": [], "gtm": [], "drafts": []
    }

    web_summary: dict[str, Any] | None = None
    if company_url.strip():
        doc = profile_bootstrap.fetch_website(company_url.strip(), "company_site", max_subpages=1, opener=opener)
        if doc.status == "ok":
            web_summary = {
                "url": doc.origin,
                "title": doc.title,
                "meta": doc.meta_description,
                "headings": doc.headings[:6],
                "tech_stack": sources.extract_tech_stack(doc.text) or [],
            }

    evidence_bullets: list[str] = []
    for raw in vault_ctx["evidence"] + vault_ctx["gtm"] + vault_ctx["accounts"]:
        for line in raw.splitlines():
            s = line.strip()
            if s.startswith(("- ", "title:", "url:", "판정:", "- 판정:", "- 채용 중인 직무:", "- 투자")):
                evidence_bullets.append(s.lstrip("- ").strip()[:180])
    evidence_bullets = list(dict.fromkeys(evidence_bullets))[:8]

    product = (cfg.get("product") or "[제안 제품]").strip()
    val = (cfg.get("value_proposition") or "").strip()
    att_list = [a.strip() for a in (attendees or []) if a and a.strip()]

    questions = [
        f"현재 {company} 팀에서 이 영역 업무는 어떤 도구/프로세스로 처리하고 계신가요?",
        "이번 분기 기준으로 가장 먼저 줄이고 싶은 병목이나 수작업 구간이 어디인가요?",
        "만약 검토하신다면 내부 의사결정 기준(보안·연동·비용·일정)에서 제일 중요하게 보시는 건 무엇인가요?",
    ]
    cautions = [
        "근거에 없는 예산·성과 수치를 먼저 단정하지 말 것",
        "제품 전체 데모보다 상대가 말한 1가지 병목에 맞춰 짧게 확인하고 다음 단계 합의할 것",
    ]

    lines = [
        "---",
        f'company: "{company}"',
        f'date: "{today}"',
        'kind: "meeting-prep"',
        "---",
        "",
        f"# 미팅 전 1장 브리핑 — {company} ({today})",
        "",
        f"- **미팅 목표**: {goal}",
        f"- **참석자**: {', '.join(att_list) if att_list else '미입력 (미팅 전 확인 필요)'}",
        f"- **우리 제안 요약**: {product}" + (f" — {val}" if val else ""),
        "",
        "## 1. 회사 공개 정보 요약",
    ]
    if web_summary:
        lines.append(f"- **홈페이지**: {web_summary['url']} ({web_summary['title']})")
        if web_summary["meta"]:
            lines.append(f"- **설명**: {web_summary['meta']}")
        if web_summary["tech_stack"]:
            lines.append(f"- **감지된 기술/도구**: {', '.join(web_summary['tech_stack'][:8])}")
    else:
        lines.append("- 홈페이지 URL 미제공 (필요 시 `--company-url`로 추가 조회)")

    lines += ["", "## 2. 볼트에 축적된 시그널 · 근거"]
    if evidence_bullets:
        lines += [f"- {b}" for b in evidence_bullets]
    else:
        lines.append("- 볼트에 아직 기록된 근거 없음 (미팅 시작 전 2분간 최근 공고/뉴스 확인 권장)")

    lines += ["", "## 3. 미팅 오프닝 & 핵심 질문 3개"]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    lines += ["", "## 4. 주의 사항"]
    lines += [f"- {c}" for c in cautions]
    lines += ["", "## 5. 미팅 중 메모 (직접 기록)", "- 현재 사용 중인 도구/벤더: ", "- 확인된 Pain / 우선순위: ", "- 합의된 Next Step & 일정: ", ""]

    md = "\n".join(lines)
    out_path: str | None = None
    if vault:
        m_dir = Path(vault).expanduser().absolute() / "Meetings"
        m_dir.mkdir(parents=True, exist_ok=True)
        p = m_dir / f"Prep-{today}-{_safe_slug(company)}.md"
        p.write_text(md, encoding="utf-8")
        out_path = str(p)

    return {
        "schema_version": "hermes_meeting_prep/v1",
        "company": company,
        "date": today,
        "vault_note": out_path,
        "evidence_count": len(evidence_bullets),
        "web_summary": web_summary,
        "markdown": md,
    }


# ---------------------------------------------------------------------------
# 2. Post-Meeting Recap & Follow-Up Generator
# ---------------------------------------------------------------------------

NEXT_STEP_RX = re.compile(r"(next\s*step|다음\s*단계|액션|todo|보내드리|공유드리|일정|검토\s*후|poc|견적|자료|회신)", re.I)
PAIN_RX = re.compile(r"(어려움|병목|수작업|시간이?\s*많이|불편|이슈|문제|고민|비용|정합성|연동|bottleneck|manual|pain|challenge)", re.I)


def generate_post_meeting(
    company: str,
    notes_text: str,
    *,
    attendee: str = "담당자",
    config: dict[str, Any] | None = None,
    vault: str | Path | None = None,
) -> dict[str, Any]:
    """Parse raw meeting notes into structured next steps and a plain 4-line follow-up email draft."""
    cfg = config or {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_lines = [l.strip(" -*•\t") for l in (notes_text or "").splitlines() if l.strip(" -*•\t")]
    if not raw_lines:
        raise ValueError("미팅 메모 내용이 비어 있습니다.")

    next_steps = [l for l in raw_lines if NEXT_STEP_RX.search(l)][:5]
    pains = [l for l in raw_lines if PAIN_RX.search(l) and l not in next_steps][:5]
    if not next_steps:
        next_steps = raw_lines[-2:]

    s_name = (cfg.get("sender_name") or "[이름]").strip()
    s_comp = (cfg.get("sender_company") or "[회사]").strip()
    s_contact = (cfg.get("sender_contact") or "").strip()
    sign = " · ".join(x for x in (s_name, s_comp, s_contact) if x)

    subject = f"{company} 오늘 미팅 정리 및 다음 단계"
    bullet_steps = "\n".join(f"- {s}" for s in next_steps[:3])
    pain_line = f"말씀 주신 핵심 포인트({pains[0][:80]}) 기준으로 정리했습니다.\n" if pains else ""
    recap_email = (
        f"{company} {attendee}님, 안녕하세요. {s_comp} {s_name}입니다.\n\n"
        f"오늘 시간 내주셔서 감사합니다. {pain_line}"
        f"얘기 나눈 다음 단계만 짧게 정리드립니다:\n"
        f"{bullet_steps}\n\n"
        f"빠지거나 다르게 이해한 부분이 있으면 편하게 회신 주세요.\n\n"
        f"감사합니다.\n{sign}"
    )
    qa = copy_guard.lint_copy(recap_email, subject=subject, language="ko", channel="email", touch_number=1)

    md = (
        f"---\ncompany: \"{company}\"\ndate: \"{today}\"\nkind: \"meeting-recap\"\nautomatic_send: false\n---\n\n"
        f"# 미팅 후 정리 & 팔로업 초안 — {company} ({today})\n\n"
        f"## 확인된 Pain / 요구사항\n"
        + ("\n".join(f"- {p}" for p in pains) if pains else "- (메모에서 별도 Pain 키워드 미감지)")
        + "\n\n## 합의된 Next Steps\n"
        + "\n".join(f"- [ ] {s}" for s in next_steps)
        + f"\n\n## 리캡 메일 초안 (QA {qa['score']}점 · 검토 후 직접 발송)\n"
        f"**제목**: `{subject}`\n\n"
        f"```text\n{recap_email}\n```\n"
    )

    out_path: str | None = None
    if vault:
        m_dir = Path(vault).expanduser().absolute() / "Meetings"
        m_dir.mkdir(parents=True, exist_ok=True)
        p = m_dir / f"Recap-{today}-{_safe_slug(company)}.md"
        p.write_text(md, encoding="utf-8")
        out_path = str(p)

    return {
        "schema_version": "hermes_meeting_recap/v1",
        "company": company,
        "date": today,
        "pains": pains,
        "next_steps": next_steps,
        "subject": subject,
        "recap_email": recap_email,
        "qa": qa,
        "vault_note": out_path,
        "markdown": md,
        "automatic_send": False,
    }


# ---------------------------------------------------------------------------
# 3. Sending Domain Deliverability Health Check (MX / SPF / DKIM / DMARC)
# ---------------------------------------------------------------------------

def _default_dns_lookup(name: str, rtype: str) -> list[str]:
    """Query DNS records using local dig/host/nslookup (zero third-party Python deps)."""
    if shutil.which("dig"):
        proc = subprocess.run(
            ["dig", "+short", rtype, name],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if proc.returncode == 0:
            return [line.strip().strip('"').replace('" "', "") for line in proc.stdout.splitlines() if line.strip()]
    if shutil.which("host"):
        proc = subprocess.run(
            ["host", "-t", rtype, name],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if proc.returncode == 0:
            lines = []
            for line in proc.stdout.splitlines():
                if "descriptive text" in line:
                    m = re.search(r'"(.+)"', line)
                    if m:
                        lines.append(m.group(1).replace('" "', ""))
                elif "handled by" in line:
                    lines.append(line.split("handled by", 1)[1].strip())
            return lines
    if shutil.which("nslookup"):
        proc = subprocess.run(
            ["nslookup", f"-type={rtype}", name],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if proc.returncode == 0:
            out: list[str] = []
            for line in proc.stdout.splitlines():
                if "text =" in line:
                    out.append(line.split("text =", 1)[1].strip().strip('"'))
                elif "mail exchanger =" in line:
                    out.append(line.split("mail exchanger =", 1)[1].strip())
            return out
    raise RuntimeError("로컬 DNS 조회 도구(dig/host/nslookup)를 찾을 수 없습니다.")


def check_domain_health(
    domain: str,
    *,
    dkim_selectors: list[str] | None = None,
    resolver=None,
) -> dict[str, Any]:
    """Inspect MX, SPF, DMARC, and DKIM selectors for cold-email deliverability readiness."""
    clean_domain = (domain or "").strip().lower().removeprefix("http://").removeprefix("https://").split("/")[0]
    if "@" in clean_domain:
        clean_domain = clean_domain.split("@", 1)[1]
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", clean_domain):
        raise ValueError(f"올바른 도메인 형식이 아닙니다: {domain!r}")

    query = resolver or _default_dns_lookup
    selectors = list(dkim_selectors or COMMON_DKIM_SELECTORS)

    mx_records = query(clean_domain, "MX")
    txt_records = query(clean_domain, "TXT")
    dmarc_records = query(f"_dmarc.{clean_domain}", "TXT")

    spf_records = [r for r in txt_records if r.lower().startswith("v=spf1")]
    dmarc_valid = [r for r in dmarc_records if r.lower().startswith("v=dmarc1")]

    dkim_found: dict[str, str] = {}
    for sel in selectors:
        recs = query(f"{sel}._domainkey.{clean_domain}", "TXT")
        hits = [r for r in recs if "v=dkim1" in r.lower() or "p=" in r.lower()]
        if hits:
            dkim_found[sel] = hits[0][:120]

    score = 0
    issues: list[str] = []
    recommendations: list[str] = []

    # MX (20 pts)
    if mx_records:
        score += 20
    else:
        issues.append("MX 레코드가 없어 회신 수신 및 발신 평판에 문제가 생깁니다.")

    # SPF (30 pts)
    if len(spf_records) == 1:
        spf = spf_records[0]
        if "-all" in spf or "~all" in spf:
            score += 30
        elif "+all" in spf:
            score += 5
            issues.append("SPF가 '+all'로 열려 있어 스푸핑 위험이 매우 높습니다('-all' 또는 '~all' 권장).")
        else:
            score += 18
            recommendations.append("SPF 끝에 '~all' 또는 '-all' 정책을 명시하세요.")
    elif len(spf_records) > 1:
        score += 10
        issues.append(f"SPF 레코드가 {len(spf_records)}개 중복되어 있습니다(RFC상 1개로 통합 필요).")
    else:
        issues.append("SPF(v=spf1) TXT 레코드가 없습니다.")
        recommendations.append("발신 메일 서비스(Google Workspace/M365 등)의 SPF 레코드를 등록하세요.")

    # DMARC (30 pts)
    if dmarc_valid:
        dmarc = dmarc_valid[0].lower()
        if "p=reject" in dmarc or "p=quarantine" in dmarc:
            score += 30
        elif "p=none" in dmarc:
            score += 20
            recommendations.append("DMARC가 모니터링 단계(p=none)입니다. 안정화 후 p=quarantine 또는 p=reject로 올리세요.")
        else:
            score += 15
    else:
        issues.append("_dmarc TXT 레코드가 없습니다(Gmail/Yahoo 대량 발신 필수 요건).")
        recommendations.append(f"_dmarc.{clean_domain}에 'v=DMARC1; p=quarantine; pct=100' 이상 설정을 권장합니다.")

    # DKIM (20 pts)
    if dkim_found:
        score += 20
    else:
        recommendations.append(
            f"대표 셀렉터({', '.join(selectors[:5])})에서 DKIM을 찾지 못했습니다. "
            "커스텀 셀렉터를 쓰신다면 --selector 옵션으로 직접 확인하세요."
        )

    status = "healthy" if score >= 85 and not issues else ("warning" if score >= 55 else "at_risk")
    warmup_guide = [
        "신규/보조 도메인은 최소 14~21일 워밍업 후 콜드메일 시작 권장",
        "인박스당 일일 발송량: 1주차 10~15건 → 2주차 20~30건 → 안정화 후 40~50건 이하 유지",
        "메인 기업 도메인 보호를 위해 콜드 아웃바운드 전용 서브/유사 도메인 분리 권장",
    ]
    return {
        "schema_version": "hermes_domain_health/v1",
        "domain": clean_domain,
        "status": status,
        "score": score,
        "checks": {
            "mx": {"ok": bool(mx_records), "records": mx_records[:5]},
            "spf": {"ok": len(spf_records) == 1, "records": spf_records},
            "dmarc": {"ok": bool(dmarc_valid), "records": dmarc_valid},
            "dkim": {"ok": bool(dkim_found), "selectors_found": dkim_found},
        },
        "issues": issues,
        "recommendations": recommendations,
        "warmup_guide": warmup_guide,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="미팅 전 1장 브리핑 · 미팅 후 팔로업 · 발신 도메인 SPF/DKIM/DMARC 헬스체크")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prep", help="미팅 전 1장 브리핑 생성")
    p_prep.add_argument("--company", required=True)
    p_prep.add_argument("--attendee", action="append", default=[])
    p_prep.add_argument("--company-url", default="")
    p_prep.add_argument("--goal", default="상대 팀의 현재 업무 방식·우선순위 확인 및 적합성 판단")
    p_prep.add_argument("--config", default=str(ROOT / "setup.json"))
    p_prep.add_argument("--vault")
    p_prep.add_argument("--json", action="store_true")

    p_post = sub.add_parser("post", help="미팅 메모 또는 Plaud/음성 녹음(--audio-file) → 합의된 Next Steps & 리캡 이메일 초안 생성")
    p_post.add_argument("--company", required=True)
    p_post.add_argument("--attendee", default="담당자")
    p_post.add_argument("--notes-file", help="미팅 메모 파일(.md/.txt)")
    p_post.add_argument("--audio-file", help="Plaud/미팅 녹음 파일(.mp3/.m4a/.wav) — Groq Whisper(무료 티어)로 자동 전사")
    p_post.add_argument("--audio-model", default="whisper-large-v3-turbo", choices=("whisper-large-v3-turbo", "whisper-large-v3"))
    p_post.add_argument("--audio-language", default="ko")
    p_post.add_argument("--notes", default="", help="직접 전달할 미팅 메모 텍스트")
    p_post.add_argument("--config", default=str(ROOT / "setup.json"))
    p_post.add_argument("--home", default=None)
    p_post.add_argument("--vault")
    p_post.add_argument("--json", action="store_true")

    p_health = sub.add_parser("health", help="발신 도메인 MX / SPF / DKIM / DMARC 헬스체크")
    p_health.add_argument("--domain", required=True, help="점검할 발신 도메인 또는 이메일 (예: example.com)")
    p_health.add_argument("--selector", action="append", default=[], help="추가 확인할 DKIM 셀렉터")
    p_health.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "health":
            sels = [*COMMON_DKIM_SELECTORS, *args.selector] if args.selector else None
            res = check_domain_health(args.domain, dkim_selectors=sels)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if res["status"] != "at_risk" else 1

        cfg: dict[str, Any] = {}
        cfg_p = Path(args.config).expanduser()
        if cfg_p.is_file():
            cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))

        if args.cmd == "prep":
            res = generate_meeting_prep(
                args.company, attendees=args.attendee, company_url=args.company_url,
                goal=args.goal, vault=args.vault, config=cfg,
            )
        else:
            notes = Path(args.notes_file).expanduser().read_text(encoding="utf-8-sig") if args.notes_file else args.notes
            transcript_meta = None
            if args.audio_file:
                import audio_transcribe
                out_txt = None
                if args.vault:
                    t_dir = Path(args.vault).expanduser().absolute() / "Meetings" / "Transcripts"
                    t_dir.mkdir(parents=True, exist_ok=True)
                    out_txt = t_dir / f"{Path(args.audio_file).stem}.txt"
                tr = audio_transcribe.transcribe_audio(
                    args.audio_file,
                    out_path=out_txt,
                    model=args.audio_model,
                    language=args.audio_language,
                    home=args.home,
                )
                if tr.get("status") != "ok":
                    raise ValueError(tr.get("hint") or tr.get("error") or "오디오 전사에 실패했습니다.")
                transcript_meta = {k: v for k, v in tr.items() if k != "text"}
                notes = (notes + "\n\n" + tr["text"]).strip() if notes else tr["text"]
            res = generate_post_meeting(
                args.company, notes, attendee=args.attendee, config=cfg, vault=args.vault,
            )
            if transcript_meta:
                res["transcript"] = transcript_meta

        if args.json:
            print(json.dumps({k: v for k, v in res.items() if k != "markdown"}, ensure_ascii=False, indent=2))
        else:
            print(res["markdown"])
        return 0
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
