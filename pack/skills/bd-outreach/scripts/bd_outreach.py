#!/usr/bin/env python3
"""bd-outreach — 랭크된 BD 타깃에 보낼 개인화 콜드메시지 '초안'을 생성.

입력: startup_score.py --json (stdin, 점수 내림차순).
출력: 회사별 초안(사람이 검토 후 직접 발송). **자동 발송 안 함** — 콜드 BD는 사람 검토 필수.

payload-first: 두루뭉술한 소개("채용 도와드립니다") 금지. 상대의 **구체 시그널**(방금 받은 투자 +
지금 뽑는 실제 직무)을 콕 집어 관련성을 증명한다. 진짜 데이터만 쓴다(날조 금지).

채용사 정체성은 profile.json에서 온다(이름·회사·전문분야·연락처·CTA). 예시는 profile.example.json.
"""
import argparse
import json
import os
import sys

DEFAULT_PROFILE = {
    "recruiter_name": "[이름]",
    "firm": "[회사]",
    "specialty": "[전문 분야 — 예: 테크/GTM 포지션]",
    "value_prop": "[한 줄 가치 제안 — 예: 시리즈A~C 스타트업의 엔지니어·리더 포지션을 빠르게 매칭]",
    "contact": "[이메일 / 연락처]",
    "cta": "혹시 채용에 도움이 될지 15분만 이야기 나눠볼 수 있을까요?",
}


def _eul(word):
    """목적격 조사 을/를 — 마지막 글자 받침 유무로 선택."""
    if word and "가" <= word[-1] <= "힣":
        return "을" if (ord(word[-1]) - 0xAC00) % 28 else "를"
    return "를"


def draft(rec, prof):
    company = rec.get("company", "")
    amount = rec.get("amount", "")
    rnd = rec.get("round", "")
    roles = rec.get("roles", []) or []
    hot = ", ".join(roles[:2])                          # 가장 관련 있는 직무 1~2개로 훅

    # 투자 축하 훅(있는 것만) — 날조 금지
    fund = " ".join(x for x in (amount, rnd) if x).strip()
    fund_line = f"{company}의 {fund} 투자 소식 반갑게 봤습니다. 축하드립니다." if fund \
        else f"{company}의 최근 투자 소식 반갑게 봤습니다. 축하드립니다."

    if hot:
        role_line = f"지금 {hot}" + (f" 등 {len(roles)}개 포지션" if len(roles) > 1 else " 포지션") + \
            "을 채용 중이신 것도 확인했는데요,"
    else:
        role_line = "채용 계획이 있으실 것 같아 연락드립니다 —"

    return (
        f"받는 곳: {company} 대표님 / 채용 담당자님\n\n"
        f"안녕하세요, {prof['firm']}의 {prof['recruiter_name']}입니다.\n\n"
        f"{fund_line}\n"
        f"{role_line} 저는 {prof['specialty']}{_eul(prof['specialty'])} 주로 매칭합니다.\n\n"
        f"{prof['value_prop']}\n\n"
        f"{prof['cta']}\n\n"
        f"{prof['recruiter_name']} · {prof['contact']}"
    )


def main():
    ap = argparse.ArgumentParser(description="BD 타깃별 콜드메시지 초안 생성(자동발송 없음)")
    _home = os.environ.get("HERMES_HOME", "")
    _default = os.path.join(_home, "headhunt-profile.json") if _home else "profile.json"
    ap.add_argument("--profile", default=_default, help="채용사 정체성 JSON(없으면 플레이스홀더)")
    ap.add_argument("--top", type=int, default=5, help="상위 N개 타깃만")
    ap.add_argument("--min-roles", type=int, default=1, help="열린 포지션 최소치(채용신호 없으면 스킵)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    prof = dict(DEFAULT_PROFILE)
    try:
        with open(a.profile, encoding="utf-8") as f:
            prof.update(json.load(f))
    except FileNotFoundError:
        pass                                            # 플레이스홀더로 진행(초안 틀 확인용)
    try:
        rows = json.load(sys.stdin)
    except Exception:
        sys.exit("stdin에 startup_score.py --json 출력을 파이프하세요")
    # 채용 신호 있는 타깃만(콜드 BD는 훅이 있어야 함)
    targets = [r for r in rows if (r.get("open_roles") or 0) >= a.min_roles][:a.top]
    drafts = [{"company": r.get("company"), "score": r.get("score"), "draft": draft(r, prof)} for r in targets]
    if a.json:
        print(json.dumps(drafts, ensure_ascii=False, indent=2))
        return 0
    print(f"※ 초안 {len(drafts)}건 — 검토 후 직접 발송하세요 (자동 발송 아님)\n")
    for i, d in enumerate(drafts, 1):
        print(f"{'─'*60}\n[{i}] {d['company']} (점수 {d['score']})\n{'─'*60}")
        print(d["draft"], "\n")
    if "[이름]" in prof["recruiter_name"]:
        print(f"⚠️  {a.profile} 없음 — 지금은 플레이스홀더 초안입니다. "
              "스킬 폴더의 profile.example.json을 그 위치로 복사해 본인 정보로 채우세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
