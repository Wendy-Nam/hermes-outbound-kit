#!/usr/bin/env python3
"""signal-outreach-draft — 채점된 계정의 실제 신호와 영업 프로필(톤·채널·발신자)로 GTM 초안을 만든다.

자동 발송 없음.
입력: account_score.py --json-out 출력(stdin JSON 리스트).
제품·고객·톤·채널: $HERMES_HOME/outbound-profile.json.
발신자: $HERMES_HOME/sender-profile.json (없으면 outbound-profile.json의 sender_* 필드 폴백).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "account-crm", "scripts"))
try:
    import gtm_vault  # noqa: E402
except ImportError:
    gtm_vault = None

DEFAULT_SENDER = {
    "name": "[이름]",
    "company": "[회사]",
    "role": "",
    "contact": "[이메일]",
    "cta": "지금 보시는 시기가 아니면 편하게 패스하셔도 되고, 필요하시면 짧은 자료 1장 보내드릴까요?",
    "tone": "concise",
    "channel": "email",
    "value_proposition": "",
    "proof_points": "",
}


def _josa(word, with_final, without_final):
    last = word.rstrip()[-1:] if word.strip() else ""
    if "가" <= last <= "힣":
        return word + (with_final if (ord(last) - 0xAC00) % 28 else without_final)
    return f"{word}{with_final}({without_final})"


def _key(name):
    return re.sub(r"[^가-힣a-z0-9]", "", (name or "").lower())


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def draft(rec, product, customer, sender, writing_style=None):
    company = rec.get("company", "")
    sig = rec.get("signals") or {}
    funding = sig.get("funding", "")
    roles = sig.get("roles") or []
    wstyle = writing_style or {}
    wpat = wstyle.get("patterns") if isinstance(wstyle.get("patterns"), dict) else {}
    tone = sender.get("tone") or wstyle.get("detected_tone") or "concise"
    channel = sender.get("channel") or "email"
    value_prop = (sender.get("value_proposition") or "").strip()
    proof = (sender.get("proof_points") or "").strip()
    cta = sender.get("cta") or wpat.get("preferred_cta") or DEFAULT_SENDER["cta"]

    if funding and roles:
        hook = f"{funding} 소식과 「{', '.join(roles[:2])}」 공고 보고 짧게 연락드립니다."
    elif funding:
        hook = f"{funding} 기사 보고 짧게 연락드립니다."
    elif roles:
        hook = f"「{', '.join(roles[:2])}」 공고 보고 짧게 연락드립니다."
    else:
        hook = f"{company} 공개 소식 보고 짧게 연락드립니다."

    intro_role = f" {sender['role']}" if sender.get("role") else ""
    sign_off = f"{sender['name']}{intro_role} · {sender['company']} · {sender['contact']}"
    val_line = value_prop or f"{product}로 관련 실무를 돕고 있습니다"
    if not val_line.endswith((".", "다", "요", "?")):
        val_line += "."

    if channel == "linkedin":
        return "\n".join([
            "[LinkedIn DM 초안]",
            f"{company} 담당자님, 안녕하세요. {sender['company']} {sender['name']}입니다.",
            hook,
            val_line,
            cta,
        ])

    if channel == "call":
        return "\n".join([
            "[콜드콜 메모 · 20초]",
            f"1) 첫마디: 안녕하세요, {sender['company']} {sender['name']}입니다. 지금 30초만 여쭤봐도 될까요?",
            f"2) 이유: {hook}",
            f"3) 한 줄: {val_line}",
            f"4) 확인: {cta}",
        ])

    if wpat.get("preferred_greeting") and wstyle.get("language", "ko") == "ko":
        greeting = (wpat["preferred_greeting"].replace("{회사}", company).replace("{담당자}", "담당자")
                    + f" {sender['company']} {sender['name']}{intro_role}입니다.")
    elif tone == "formal":
        greeting = f"{company} 담당자님, 안녕하십니까. {sender['company']} {sender['name']}{intro_role}입니다."
    else:
        greeting = f"{company} 담당자님, 안녕하세요. {sender['company']} {sender['name']}{intro_role}입니다."

    closing = (
        wpat["preferred_closing"]
        if wpat.get("preferred_closing") and wstyle.get("language", "ko") == "ko"
        else "감사합니다."
    )

    subject_focus = roles[0][:20] if roles else ("최근 소식" if funding else "짧은 확인")
    subject = f"{company} {subject_focus} 관련 확인"

    lines = [
        f"제목: {subject}",
        "",
        greeting,
        "",
        hook,
        f"저희는 {product}를 만들고 있고, {val_line}",
    ]
    if proof:
        lines.append(proof if proof.endswith((".", "다", "요", "?")) else f"{proof}.")
    lines.extend([
        "",
        cta,
        "",
        closing,
        sign_off,
        "",
        "---",
        "[발송 전 내 말로 바꿀 1줄 메모]",
        f"- 타깃 고객 맥락: {customer}",
        "- 보낼 때 위 본문 중 1줄만 상대 팀에서 실제로 본 사실로 바꿔서 보내세요.",
    ])
    return "\n".join(lines)


def main():
    home = os.environ.get("HERMES_HOME", "")
    ap = argparse.ArgumentParser(description="채점된 계정별 GTM 콜드메일/DM/콜 초안(자동 발송 없음)")
    ap.add_argument("--profile", default=os.path.join(home, "outbound-profile.json") if home else "outbound-profile.json")
    ap.add_argument("--sender", default=os.path.join(home, "sender-profile.json") if home else "sender-profile.json")
    ap.add_argument("--style", default=os.path.join(home, "writing-style.json") if home else "writing-style.json")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--include-research", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--vault")
    ap.add_argument("--no-vault", action="store_true")
    ap.add_argument("--include-contacted", action="store_true")
    ap.add_argument("--do-not-contact", default=os.path.join(home, "do-not-contact.txt") if home else "do-not-contact.txt")
    a = ap.parse_args()
    profile = _load(a.profile)
    writing_style = _load(a.style)
    product = profile.get("product") or "[제품 한 줄 설명]"
    customer = profile.get("customer") or "[타깃 고객]"

    sender_from_profile = {
        k: v for k, v in {
            "name": profile.get("sender_name"),
            "company": profile.get("sender_company"),
            "role": profile.get("sender_role"),
            "contact": profile.get("sender_contact"),
            "cta": profile.get("sender_cta"),
            "tone": profile.get("outreach_tone"),
            "channel": profile.get("outreach_channel"),
            "value_proposition": profile.get("value_proposition"),
            "proof_points": profile.get("proof_points"),
        }.items() if v
    }
    sender_file = {k: v for k, v in _load(a.sender).items() if v}
    sender = dict(DEFAULT_SENDER, **sender_from_profile, **sender_file)

    try:
        rows = json.load(sys.stdin)
    except ValueError:
        sys.exit("stdin에 account_score.py --jsonl --json-out 출력을 파이프하세요")
    allowed = {"지금 콜", "콜 예약", "너처링"} | ({"리서치 필요"} if a.include_research else set())
    blocked = {_key(x) for x in (profile.get("do_not_contact") or []) if isinstance(x, str) and x.strip()}
    try:
        with open(a.do_not_contact, encoding="utf-8") as fh:
            blocked |= {_key(l) for l in fh if l.strip() and not l.startswith("#")}
    except FileNotFoundError:
        pass
    vault = None if a.no_vault or not gtm_vault else gtm_vault.resolve_vault(a.vault)
    status = {}
    if vault and not a.include_contacted:
        status = {k: v.get("status") for k, v in gtm_vault.VaultLedger(vault).load().items()}
    skipped = []
    targets = []
    for r in rows:
        k = _key(r.get("company"))
        if r.get("action") not in allowed:
            continue
        if k in blocked:
            skipped.append(f"{r.get('company')}(연락 금지)")
            continue
        if status.get(k) not in (None, "발굴"):
            skipped.append(f"{r.get('company')}({status[k]})")
            continue
        targets.append(r)
    targets = targets[:a.top]
    drafts = [{"company": r.get("company"), "action": r.get("action"),
               "evidence": r.get("evidence") or {}, "draft": draft(r, product, customer, sender, writing_style=writing_style)}
              for r in targets]
    saved = []
    if vault:
        for d in drafts:
            path = gtm_vault.write_draft(vault, d["company"], d["action"], d["draft"], d["evidence"])
            if path:
                saved.append(str(path))
                d["note"] = str(path)
    if a.json:
        print(json.dumps(drafts, ensure_ascii=False, indent=2))
        return 0
    print(f"※ 초안 {len(drafts)}건 — 사람이 근거를 확인하고 직접 발송하세요 (자동 발송 아님)\n")
    for i, d in enumerate(drafts, 1):
        print(f"{'─' * 60}\n[{i}] {d['company']} ({d['action']})\n{'─' * 60}")
        print(d["draft"])
        for key, url in d["evidence"].items():
            print(f"  근거({key}): {url}")
        print()
    if skipped:
        print("제외: " + ", ".join(skipped))
    if saved:
        print(f"Obsidian 볼트에 초안 노트 {len(saved)}건 저장: {vault / 'GTM' / 'Drafts'}")
    if not drafts:
        print("대상 계정이 없습니다. '리서치 필요' 계정은 prospect-research로 적합도 근거를 채운 뒤 다시 채점하세요.")
    if "[" in product or "[" in sender["name"]:
        print(f"⚠️  자리표시자가 남아 있습니다. `python3 profile.py customize`로 발신자·제품 프로필을 설정할 수 있습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
