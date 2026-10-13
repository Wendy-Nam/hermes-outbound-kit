#!/usr/bin/env python3
"""signal-outreach-draft — 채점된 계정의 실제 신호로 GTM 콜드메일 '초안'을 만든다. 자동 발송 없음.

입력: account_score.py --json-out 출력(stdin JSON 리스트). 각 항목의 signals(투자·채용)와 판정을 쓴다.
제품·고객: $HERMES_HOME/outbound-profile.json(키트 설치 때 생성)의 product / customer.
발신자: $HERMES_HOME/sender-profile.json(선택, profile.example.json 참고). 없으면 자리표시자.

원칙: 신호는 수집된 실제 값만 인용한다. 가설은 질문으로 쓴다. 채용·투자는 예산의 증거가 아니다.
"""
import argparse
import json
import os
import sys

# 볼트 기록은 account-crm 스킬의 공용 모듈을 쓴다(같은 skills 폴더에 함께 설치됨).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "account-crm", "scripts"))
try:
    import gtm_vault  # noqa: E402
except ImportError:
    gtm_vault = None

DEFAULT_SENDER = {
    "name": "[이름]",
    "company": "[회사]",
    "contact": "[이메일]",
    "cta": "관련이 있다면 다음 주 중 15분 정도 이야기 나눠볼 수 있을까요? 지금은 해당되지 않는다면 편하게 말씀해 주셔도 괜찮습니다.",
}


def _josa(word, with_final, without_final):
    last = word.rstrip()[-1:] if word.strip() else ""
    if "가" <= last <= "힣":
        return word + (with_final if (ord(last) - 0xAC00) % 28 else without_final)
    return f"{word}{with_final}({without_final})"


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def draft(rec, product, customer, sender):
    company = rec.get("company", "")
    sig = rec.get("signals") or {}
    funding, roles = sig.get("funding", ""), sig.get("roles") or []
    hooks = []
    if funding:
        hooks.append(f"최근 {funding} 투자 유치 소식을 보았습니다. 축하드립니다.")
    if roles:
        hooks.append(f"지금 {', '.join(roles[:2])} 채용을 진행 중이신 것도 확인했습니다.")
    if not hooks:
        hooks.append("공개된 최근 소식을 보고 연락드립니다.")
    subject = f"{company} {'투자 이후 ' if funding else ''}확장 관련 문의"
    lines = [
        f"제목: {subject}",
        "",
        f"안녕하세요, {company} 담당자님. {sender['company']}의 {sender['name']}입니다.",
        "",
        " ".join(hooks) + " 조직이 커지는 시기라 새로 정비하실 일이 있지 않을까 싶었습니다.",
        "",
        f"저희는 {_josa(product, '을', '를')} 제공하고 있고, {_josa(customer, '과', '와')} 비슷한 상황의 팀을 돕고 있습니다. "
        + sender["cta"],
        "",
        f"감사합니다.\n{sender['name']} · {sender['contact']}",
    ]
    return "\n".join(lines)


def main():
    home = os.environ.get("HERMES_HOME", "")
    ap = argparse.ArgumentParser(description="채점된 계정별 GTM 콜드메일 초안(자동 발송 없음)")
    ap.add_argument("--profile", default=os.path.join(home, "outbound-profile.json") if home else "outbound-profile.json",
                    help="제품·고객 정보(키트 설치 때 생성되는 outbound-profile.json)")
    ap.add_argument("--sender", default=os.path.join(home, "sender-profile.json") if home else "sender-profile.json",
                    help="발신자 정보 JSON(선택)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--include-research", action="store_true",
                    help="'리서치 필요' 계정도 초안 생성(기본은 지금 콜·콜 예약·너처링만)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--vault", help="Obsidian 볼트 경로(기본: 키트 설정의 볼트). GTM/Drafts에 초안 노트 저장")
    ap.add_argument("--no-vault", action="store_true", help="볼트에 저장하지 않고 화면에만 출력")
    a = ap.parse_args()
    profile = _load(a.profile)
    product = profile.get("product") or "[제품 한 줄 설명]"
    customer = profile.get("customer") or "[타깃 고객]"
    sender = dict(DEFAULT_SENDER, **_load(a.sender))
    try:
        rows = json.load(sys.stdin)
    except ValueError:
        sys.exit("stdin에 account_score.py --jsonl --json-out 출력을 파이프하세요")
    allowed = {"지금 콜", "콜 예약", "너처링"} | ({"리서치 필요"} if a.include_research else set())
    targets = [r for r in rows if r.get("action") in allowed][:a.top]
    drafts = [{"company": r.get("company"), "action": r.get("action"),
               "evidence": r.get("evidence") or {}, "draft": draft(r, product, customer, sender)}
              for r in targets]
    vault = None if a.no_vault or not gtm_vault else gtm_vault.resolve_vault(a.vault)
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
    if saved:
        print(f"Obsidian 볼트에 초안 노트 {len(saved)}건 저장: {vault / 'GTM' / 'Drafts'}")
    if not drafts:
        print("대상 계정이 없습니다. '리서치 필요' 계정은 prospect-research로 적합도 근거를 채운 뒤 다시 채점하세요.")
    if "[" in product or "[" in sender["name"]:
        print(f"⚠️  자리표시자가 남아 있습니다. 제품·고객: {a.profile}, 발신자: {a.sender}"
              " (스킬 폴더의 profile.example.json 참고)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
