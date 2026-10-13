---
name: account-crm
description: "GTM 계정을 발굴→접촉→응답→미팅→제안→계약 파이프라인으로 추적한다. 채점을 다시 돌려도 사람이 바꾼 상태·메모는 덮지 않는다."
version: 1.1.0
author: Hermes Outbound Kit contributors
license: MIT
metadata:
  hermes:
    tags: [GTM, CRM, 파이프라인, outbound]
    related_skills: [outbound-scoring, signal-outreach-draft]
---

# account-crm — 계정 파이프라인 추적

## 단계
`발굴 → 접촉 → 응답 → 미팅 → 제안 → 계약` (+ `보류`, `실패`)

## 핵심 원칙: 사람 편집 보존
매일 수집·채점을 다시 돌려도 판정·점수·신호·근거 같은 데이터 필드만 갱신한다.
사람이 바꾼 상태·메모·접촉일은 덮지 않는다.

## How

```bash
C=${HERMES_SKILL_DIR}/scripts/account_crm.py
python3 $C --ingest < scored.json                 # account_score --json-out 결과 흡수
python3 $C --status "샘플로보틱스=접촉"            # 상태 갱신
python3 $C --note   "샘플로보틱스=CTO 발표 영상 확인"  # 메모 누적
python3 $C --list                                 # 파이프라인 보기
python3 $C --list --stage 미팅                     # 단계 필터
```

장부 기본 위치는 `$HERMES_HOME/gtm/accounts.json`이고 `OUTBOUND_CRM_LEDGER`로 바꿀 수 있다.
영업 데이터라 공유·커밋하지 않는다.
