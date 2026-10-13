---
name: bd-outreach
description: "랭크된 BD 타깃에 보낼 개인화 콜드메시지 초안을 생성한다. 상대의 구체 시그널(방금 받은 투자 + 지금 뽑는 실제 직무)을 콕 집어 payload-first로. 초안만 — 검토 후 사람이 직접 발송."
author: Hermes Outbound Kit contributors
---

# bd-outreach — 개인화 콜드메시지 초안

3단계 스코어의 상위 타깃에, 실제로 보낼 수 있는 콜드메시지 초안을 만든다.

## 원칙: payload-first
두루뭉술한 소개("채용 도와드립니다")는 안 읽힌다. 상대의 **구체 시그널**을 콕 집는다:
- "방금 {금액} {라운드} 받으셨죠, 축하합니다" (타이밍 증명)
- "지금 {실제 직무명} 채용 중이시더라고요" (숙제 했음 + 관련성 증명)
- → 그다음 가치 제안 + 가벼운 CTA

**진짜 데이터만 쓴다** — 회사·라운드·금액·직무는 파이프라인이 가져온 실제 값. 날조 없음.
목적격 조사 을/를은 받침으로 자동 선택(한국어 품질).

## ⚠️ 초안만, 자동 발송 없음
콜드 BD는 **사람이 반드시 검토 후 직접 발송**한다. 이 스킬은 초안 텍스트만 출력한다.

## How

```bash
# 채용사 정체성 설정(1회)
cp ${HERMES_SKILL_DIR}/profile.example.json "$HERMES_HOME/headhunt-profile.json"   # 이름·회사·전문분야·가치제안·연락처 채우기

# 상위 타깃 초안 생성
python3 ${HERMES_SKILL_DIR}/../funded-startup-search/scripts/funded_search.py --json \
  | python3 ${HERMES_SKILL_DIR}/../startup-enrich/scripts/startup_enrich.py --json \
  | python3 ${HERMES_SKILL_DIR}/../startup-score/scripts/startup_score.py --json \
  | python3 ${HERMES_SKILL_DIR}/scripts/bd_outreach.py --top 5 --min-roles 1
```

- `--top N` 상위 N개 · `--min-roles K` 열린 포지션 K개 이상만(채용신호 없으면 콜드훅이 없어 스킵)
- `--json` CRM 노트 입력용

## profile.json (채용사 정체성)
`recruiter_name · firm · specialty · value_prop · contact · cta`. 미설정 시 플레이스홀더 초안으로
틀만 확인된다. 예시: `profile.example.json`. 실제 값은 스킬 폴더가 아니라 `$HERMES_HOME/headhunt-profile.json`에 둔다(개인 연락처라 공유·커밋 금지).

## 파이프라인 위치
`…score` → **`bd-outreach`(초안)** → [사람 검토·발송] → `startup-crm`(응답·계약 추적).
