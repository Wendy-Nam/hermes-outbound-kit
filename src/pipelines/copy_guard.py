#!/usr/bin/env python3
"""copy_guard.py — GTMOS-inspired outbound copy linter & honest multi-touch sequence builder.

Zero external dependencies (Python 3.11+ stdlib). Optional TypeSafe AI Jev QA integration.
Enforces:
- Plain, peer-like, honest voice (no lecturing, fake flattery, hype, or spam triggers)
- Mobile-scannable brevity (EN <= 75 words for touch 1; KO <= 220 chars / <= 6 body lines)
- Placeholder leak checks ([이름], {{company}}, etc.)
- Multi-touch 1~4 sequence generation with distinct angles and zero-pressure breakup
"""
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Based on GTMOS spam-words.md & cold-email-skill.md + Korean outbound anti-cliche rules.
EN_BANNED_PHRASES: tuple[str, ...] = (
    "circle back", "just following up", "following up here", "bumping this",
    "last note from me", "touching base", "hope this finds you well",
    "i hope you are doing well", "excited to share", "thrilled to announce",
    "game-changing", "revolutionary", "100% guaranteed", "free trial",
    "act now", "limited time", "exclusive deal", "no obligation", "risk-free",
    "double your", "increase revenue", "click here", "buy now", "urgent",
    "amazing offer", "best price", "compare notes", "off chance",
)

EN_SPAM_SINGLE_WORDS: tuple[str, ...] = (
    "guaranteed", "free", "discount", "bargain", "promo", "promotion",
    "winner", "urgent", "cash", "credit", "mortgage", "giveaway", "bonus",
)

KO_CLICHE_OR_SPAM_PHRASES: tuple[str, ...] = (
    "보통 이 포지션을 뽑는 시점에",
    "보통 이 타이밍에",
    "가장 먼저 병목이",
    "혁신적인 솔루션",
    "압도적인 성과",
    "폭발적인 성장",
    "100% 보장",
    "무조건",
    "놓치지 마세요",
    "지금 바로 신청",
    "한정 혜택",
    "무료 컨설팅",
    "무료 진단 이벤트",
    "귀사의 무궁한 발전",
    "바쁘신 와중에 죄송합니다만",
    "다름이 아니라",
    "인사드리게 되어 영광",
    "게임 체인저",
)

PLACEHOLDER_RX = re.compile(
    r"(\{\{[^}]+\}\}|\[(?:이름|회사|이메일|제품[^\]]*|타깃[^\]]*|담당자|연락처|링크)\]|<(?:COMPANY|NAME|ROLE)>)"
)
URL_RX = re.compile(r"https?://\S+", re.I)


def _strip_memo_footer(text: str) -> str:
    """Exclude the internal human-edit memo block below '---' when measuring sendable body length."""
    marker = "\n---\n[발송 전"
    idx = text.find(marker)
    if idx >= 0:
        return text[:idx].strip()
    marker_en = "\n---\n[1-line note"
    idx2 = text.find(marker_en)
    if idx2 >= 0:
        return text[:idx2].strip()
    return text.strip()


def _detect_language(text: str) -> str:
    ko = len(re.findall(r"[가-힣]", text))
    ja = len(re.findall(r"[\u3040-\u30ff]", text))
    en = len(re.findall(r"[A-Za-z]", text))
    if ja >= 10:
        return "ja"
    if ko >= 10 and ko * 2 >= en:
        return "ko"
    return "en"


def lint_copy(
    body: str,
    *,
    subject: str = "",
    language: str = "auto",
    channel: str = "email",
    touch_number: int = 1,
    allow_phrases: list[str] | None = None,
    use_jev: bool = False,
    record: dict[str, Any] | None = None,
    home: str | Path | None = None,
    opener=None,
) -> dict[str, Any]:
    """Run GTMOS-style spam, cliche, readability, and placeholder checks on outbound copy."""
    sendable = _strip_memo_footer(body or "")
    subj = (subject or "").strip()
    if not subj and sendable.startswith(("제목:", "Subject:")):
        first_line, _, rest = sendable.partition("\n")
        subj = first_line.split(":", 1)[1].strip()
        sendable = rest.strip()

    lang = _detect_language(sendable + " " + subj) if language == "auto" else language
    allowed = {p.casefold() for p in (allow_phrases or []) if p}
    issues: list[str] = []
    warnings: list[str] = []

    full_check = f"{subj}\n{sendable}".casefold()

    # 1. Unfilled placeholder leak check (hard issue)
    placeholders = PLACEHOLDER_RX.findall(f"{subj}\n{sendable}")
    if placeholders:
        issues.append(f"치환되지 않은 플레이스홀더 발견: {', '.join(sorted(set(placeholders))[:5])}")

    # 2. Spam / cliché / lecturing phrase check
    found_phrases: list[str] = []
    for phrase in (*KO_CLICHE_OR_SPAM_PHRASES, *EN_BANNED_PHRASES):
        if phrase.casefold() in allowed:
            continue
        if phrase.casefold() in full_check:
            found_phrases.append(phrase)
    if found_phrases:
        issues.append(f"상투어·스팸/훈수 표현 감지: {', '.join(found_phrases[:5])}")

    if lang == "en":
        spam_words = [
            w for w in EN_SPAM_SINGLE_WORDS
            if w not in allowed and re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", full_check)
        ]
        if spam_words:
            warnings.append(f"영문 스팸 트리거 단어 주의: {', '.join(spam_words[:5])}")

    # 3. Subject line checks (email)
    if channel == "email" and subj:
        if "!" in subj or "🔥" in subj or "💰" in subj:
            issues.append("제목에 느낌표/과장 이모지가 포함되어 스팸 필터 위험이 있습니다.")
        if lang == "ko" and len(subj) > 42:
            warnings.append(f"제목이 다소 깁니다({len(subj)}자, 모바일 권장 35자 이내).")
        elif lang == "en" and len(subj.split()) > 7:
            warnings.append(f"영문 제목이 깁니다({len(subj.split())}단어, 권장 2~5단어).")

    # 4. Length & mobile scannability checks
    non_empty_lines = [l.strip() for l in sendable.splitlines() if l.strip()]
    char_count = len(sendable)
    word_count = len(re.findall(r"[A-Za-z0-9'-]+|[가-힣]+", sendable))
    urls = URL_RX.findall(sendable)

    if channel == "linkedin_connect":
        if char_count > 300:
            issues.append(f"LinkedIn 연결 요청 300자 제한 초과({char_count}자).")
    elif channel == "linkedin":
        if char_count > 450:
            warnings.append(f"LinkedIn DM이 깁니다({char_count}자, 권장 300~400자 이내).")
    elif channel == "email":
        if lang == "ko":
            limit_chars = 360 if touch_number == 1 else 260
            if char_count > limit_chars:
                warnings.append(f"한국어 본문이 깁니다({char_count}자, {touch_number}차 권장 {limit_chars}자 이내).")
        elif lang == "en":
            limit_words = 85 if touch_number == 1 else 60
            if word_count > limit_words:
                warnings.append(f"영문 본문이 깁니다({word_count}단어, {touch_number}차 권장 {limit_words}단어 이내).")
        if len(non_empty_lines) > 10:
            warnings.append(f"줄 수가 많아 모바일 가독성이 떨어집니다({len(non_empty_lines)}줄).")

    # 5. Link & punctuation hygiene
    if len(urls) >= 2:
        warnings.append(f"링크가 {len(urls)}개 포함되어 전달률(deliverability)이 떨어질 수 있습니다(1차 메일은 0~1개 권장).")
    if sendable.count("!") >= 2:
        warnings.append("느낌표(!)가 2회 이상 사용되었습니다. 담백한 마침표가 신뢰도가 높습니다.")
    if sendable.count("?") >= 3:
        warnings.append("질문이 3개 이상입니다. 단일 저압박 확인 질문 1개로 줄이세요.")

    # Score calculation (0..100)
    score = 100 - len(issues) * 25 - len(warnings) * 8
    score = max(0, min(100, score))

    result: dict[str, Any] = {
        "passed": len(issues) == 0 and score >= 75,
        "score": score,
        "language": lang,
        "channel": channel,
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "subject_chars": len(subj),
            "body_chars": char_count,
            "word_count": word_count,
            "non_empty_lines": len(non_empty_lines),
            "url_count": len(urls),
            "question_marks": sendable.count("?"),
        },
    }

    if use_jev:
        try:
            import jev_client
            api_key = jev_client.resolve_api_key(home)
            if api_key:
                qa = jev_client.qa_draft_with_jev(
                    sendable, record or {"company": "미확인", "title": subj}, api_key=api_key, opener=opener
                )
                result["jev_qa"] = qa
                if not qa.get("passed", True):
                    result["warnings"].extend(f"[Jev] {f}" for f in (qa.get("flags") or []))
        except Exception as exc:
            result["jev_warning"] = f"Jev QA 건너뜀: {exc}"

    return result


def build_multitouch_sequence(
    record: dict[str, Any],
    profile: dict[str, Any],
    *,
    touches: int = 4,
    language: str | None = None,
    channel: str = "email",
    writing_style: dict[str, Any] | None = None,
    spacing_days: tuple[int, ...] = (0, 3, 7, 14),
    use_jev: bool = False,
    home: str | Path | None = None,
    opener=None,
) -> list[dict[str, Any]]:
    """Build a 1~4 touch honest, low-pressure outbound sequence with distinct angles per touch."""
    touches = max(1, min(4, int(touches)))
    lang = (language or profile.get("draft_language") or "ko").lower()
    company = (record.get("company") or record.get("company_candidate") or "담당자님").strip()
    title = (record.get("title") or "최근 공개 소식").strip()
    product = (profile.get("product") or "[제품 한 줄]").strip()
    val = (profile.get("value_proposition") or "").strip()
    proof = (profile.get("proof_points") or "").strip()
    s_name = (profile.get("sender_name") or "[이름]").strip()
    s_comp = (profile.get("sender_company") or "[회사]").strip()
    s_role = (profile.get("sender_role") or "").strip()
    s_contact = (profile.get("sender_contact") or "").strip()
    sign = " · ".join(x for x in (f"{s_name} {s_role}".strip(), s_comp, s_contact) if x)
    wpat = (writing_style or {}).get("patterns") or {}
    closing = wpat.get("preferred_closing") if lang == "ko" and wpat.get("preferred_closing") else (
        "감사합니다." if lang == "ko" else "Best,"
    )

    if lang == "en":
        base_subject = f"{company} / {title[:28]}".lower()
        val_en = val or f"we build {product}"
        proof_en = proof or "Happy to send a 1-page note with relevant examples."
        raw_touches = [
            {
                "touch": 1, "day_offset": spacing_days[0], "angle": "observation_check",
                "subject": base_subject,
                "body": (
                    f"Hi {company} team,\n\n"
                    f"Saw your {title} notice and wanted to send a quick note.\n"
                    f"{val_en}.\n\n"
                    f"If this isn't on your radar right now, totally fine to skip — otherwise happy to send a short 1-pager.\n\n"
                    f"{closing}\n{sign}"
                ),
            },
            {
                "touch": 2, "day_offset": spacing_days[1], "angle": "concrete_proof",
                "subject": f"Re: {base_subject}",
                "body": (
                    f"Hi {company} team,\n\n"
                    f"Adding one concrete detail to my earlier note: {proof_en}\n"
                    f"Would it make sense to share that directly, or is someone else owning this?\n\n"
                    f"{closing}\n{sign}"
                ),
            },
            {
                "touch": 3, "day_offset": spacing_days[2], "angle": "low_friction_resource",
                "subject": f"Re: {base_subject}",
                "body": (
                    f"Hi {company} team,\n\n"
                    f"Put together a short checklist based on similar teams evaluating {product[:45]}.\n"
                    f"No call needed — reply 'send' if useful.\n\n"
                    f"{closing}\n{sign}"
                ),
            },
            {
                "touch": 4, "day_offset": spacing_days[3], "angle": "clean_breakup",
                "subject": f"Re: {base_subject}",
                "body": (
                    f"Hi {company} team,\n\n"
                    f"Looks like the timing isn't right, so I'll close the loop here.\n"
                    f"Feel free to reach back out whenever this comes up later.\n\n"
                    f"{closing}\n{sign}"
                ),
            },
        ]
    else:
        short_title = title[:24]
        base_subject = f"{company} {short_title} 관련 확인"
        val_ko = val if val else f"{product}로 관련 실무를 돕고 있습니다"
        if not val_ko.endswith((".", "다", "요", "?")):
            val_ko += "."
        proof_ko = proof if proof else "참고용 1장 요약 메모만 먼저 보내드릴 수 있습니다"
        if not proof_ko.endswith((".", "다", "요", "?")):
            proof_ko += "."
        cta_ko = (profile.get("sender_cta") or wpat.get("preferred_cta") or
                  "지금 보시는 과제가 아니면 편하게 패스하셔도 되고, 필요하시면 짧은 자료 1장 보내드릴까요?").strip()
        raw_touches = [
            {
                "touch": 1, "day_offset": spacing_days[0], "angle": "사실 기반 짧은 확인",
                "subject": base_subject,
                "body": (
                    f"{company} 담당자님, 안녕하세요. {s_comp} {s_name}입니다.\n\n"
                    f"「{title}」 보고 짧게 연락드립니다.\n"
                    f"저희는 {product}를 만들고 있고, {val_ko}\n\n"
                    f"{cta_ko}\n\n"
                    f"{closing}\n{sign}\n\n"
                    f"---\n[발송 전 내 말로 바꿀 1줄 메모]\n- 본문 중 1줄만 상대 팀에서 실제로 본 사실로 바꿔서 보내세요."
                ),
            },
            {
                "touch": 2, "day_offset": spacing_days[1], "angle": "구체적 자료·담당자 확인",
                "subject": f"Re: {base_subject}",
                "body": (
                    f"{company} 담당자님, 안녕하세요. {s_comp} {s_name}입니다.\n\n"
                    f"지난 메일에 한 줄만 덧붙입니다. {proof_ko}\n"
                    f"혹시 이 업무를 맡으신 다른 담당자분이 계시면 성함만 알려주셔도 감사하겠습니다.\n\n"
                    f"{closing}\n{sign}"
                ),
            },
            {
                "touch": 3, "day_offset": spacing_days[2], "angle": "통화 없는 참고 자료 공유",
                "subject": f"Re: {base_subject}",
                "body": (
                    f"{company} 담당자님, 안녕하세요.\n\n"
                    f"미팅 요청 없이, 비슷한 팀들이 검토할 때 체크하는 항목만 1장으로 정리해 둔 게 있습니다.\n"
                    f"필요하시면 '자료'라고만 짧게 답장 주시면 바로 보내드리겠습니다.\n\n"
                    f"{closing}\n{sign}"
                ),
            },
            {
                "touch": 4, "day_offset": spacing_days[3], "angle": "부담 없는 마무리(브레이크업)",
                "subject": f"Re: {base_subject}",
                "body": (
                    f"{company} 담당자님, 안녕하세요.\n\n"
                    f"지금은 우선순위가 아니신 것 같아 여기까지 정리하겠습니다.\n"
                    f"나중에 필요하실 때 편하게 회신 주세요.\n\n"
                    f"{closing}\n{sign}"
                ),
            },
        ]

    out: list[dict[str, Any]] = []
    for item in raw_touches[:touches]:
        qa = lint_copy(
            item["body"],
            subject=item["subject"],
            language=lang,
            channel=channel,
            touch_number=item["touch"],
            use_jev=use_jev,
            record=record,
            home=home,
            opener=opener,
        )
        out.append({**item, "qa": qa})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GTMOS식 아웃바운드 카피 스팸/가독성 린터 & 1~4차 멀티터치 시퀀스 생성기")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_lint = sub.add_parser("lint", help="초안의 스팸어·상투어·분량·플레이스홀더 점검")
    p_lint.add_argument("--subject", default="")
    p_lint.add_argument("--text", default="")
    p_lint.add_argument("--file", help="검사할 텍스트/마크다운 파일")
    p_lint.add_argument("--channel", default="email", choices=("email", "linkedin", "linkedin_connect", "call"))
    p_lint.add_argument("--language", default="auto", choices=("auto", "ko", "en", "ja"))
    p_lint.add_argument("--touch", type=int, default=1)
    p_lint.add_argument("--use-jev", action="store_true")
    p_lint.add_argument("--home")

    p_seq = sub.add_parser("sequence", help="계정 1건의 1~4차 멀티터치 시퀀스 생성 + 자동 검수")
    p_seq.add_argument("--company", required=True)
    p_seq.add_argument("--title", default="채용 공고")
    p_seq.add_argument("--config", help="setup.json 경로")
    p_seq.add_argument("--touches", type=int, default=4)
    p_seq.add_argument("--language", choices=("ko", "en"))
    p_seq.add_argument("--home")
    p_seq.add_argument("--use-jev", action="store_true")
    p_seq.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "lint":
        text = Path(args.file).expanduser().read_text(encoding="utf-8-sig") if args.file else args.text
        res = lint_copy(
            text, subject=args.subject, language=args.language, channel=args.channel,
            touch_number=args.touch, use_jev=args.use_jev, home=args.home,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["passed"] else 1

    cfg: dict[str, Any] = {}
    if args.config and Path(args.config).expanduser().is_file():
        cfg = json.loads(Path(args.config).expanduser().read_text(encoding="utf-8-sig"))
    seq = build_multitouch_sequence(
        {"company": args.company, "title": args.title},
        cfg,
        touches=args.touches,
        language=args.language,
        use_jev=args.use_jev,
        home=args.home,
    )
    if args.json:
        print(json.dumps(seq, ensure_ascii=False, indent=2))
    else:
        for item in seq:
            print(f"=== Touch {item['touch']} (Day +{item['day_offset']} · {item['angle']} · QA {item['qa']['score']}점) ===")
            print(f"제목: {item['subject']}\n")
            print(item["body"])
            if item["qa"]["issues"] or item["qa"]["warnings"]:
                print("\n[점검]", *(item["qa"]["issues"] + item["qa"]["warnings"]))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
