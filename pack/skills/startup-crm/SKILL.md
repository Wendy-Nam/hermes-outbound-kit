---
name: startup-crm
description: "BD 타깃을 발굴→접촉→응답→미팅→계약 파이프라인으로 추적한다. 파이프라인이 새 데이터를 부어도 사람이 손댄 상태·메모는 절대 안 덮는다."
author: Hermes Outbound Kit contributors
---

# startup-crm — BD 파이프라인 추적

발굴한 타깃이 어느 단계에 있는지 장부(`targets.json`)로 관리한다. 헤드헌팅은 결국 사람 관계라
"누구에게 접촉했고, 누가 응답했고, 어디까지 갔나"를 놓치지 않는 게 핵심.

## 파이프라인 단계
`발굴 → 접촉 → 응답 → 미팅 → 계약` (+ `실패`)

## 핵심 원칙: 사람 편집 보존
파이프라인(수집·스코어)을 매일 재실행해 데이터를 갱신해도, **사람이 바꾼 상태·메모·접촉일은
절대 안 덮는다.** 갱신은 데이터 필드(라운드·공고·점수)만. 구직 키트에서 상태갱신이 노트를
날렸던 사고의 교훈 — 데이터 필드와 사람 필드를 분리한다.

## How

```bash
# 발굴 파이프라인 결과를 CRM에 흡수(신규=발굴, 기존=데이터만 갱신)
python3 ${HERMES_SKILL_DIR}/../funded-startup-search/scripts/funded_search.py --json \
  | python3 ${HERMES_SKILL_DIR}/../startup-enrich/scripts/startup_enrich.py --json \
  | python3 ${HERMES_SKILL_DIR}/../startup-score/scripts/startup_score.py --json \
  | python3 ${HERMES_SKILL_DIR}/scripts/crm.py --ingest

python3 ${HERMES_SKILL_DIR}/scripts/crm.py --status "샘플로보틱스=접촉"        # 상태 갱신
python3 ${HERMES_SKILL_DIR}/scripts/crm.py --note   "샘플로보틱스=대표 링크드인 확인"  # 메모 누적
python3 ${HERMES_SKILL_DIR}/scripts/crm.py --list                                # 파이프라인 보기
python3 ${HERMES_SKILL_DIR}/scripts/crm.py --list --stage 접촉                    # 단계 필터
```

장부 기본 위치는 `$HERMES_HOME/headhunt/targets.json`이고 `HH_CRM_LEDGER` 환경변수로 바꿀 수 있다.
**장부는 영업 데이터라 공유·커밋하지 않는다.**

## 파이프라인 위치 (마지막 단계)
`…score` → `bd-outreach`(초안) → [사람 발송] → **`startup-crm`(추적)**.
매일: 수집→스코어→CRM 흡수로 새 타깃 자동 유입, 사람은 상태만 옮긴다.
