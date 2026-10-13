---
name: outbound-scoring
description: "아웃바운드 계정을 적합도·긴급도 2축으로 채점해 콜 우선순위를 정한다. SDR 리서치→스코어링→콜 큐."
version: 1.0.0
author: Hermes Outbound Kit contributors
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [세일즈, SDR, 아웃바운드, 스코어링, 리서치]
    related_skills: [prospect-research, lead-prospecting, web-reader, evidence-to-outreach]
---

## When to Use
- 아웃바운드 리스트를 받아 "누구부터 콜할지" 정해야 할 때
- 특정 계정을 조사하고 지금 연락할 타이밍인지 판단할 때
- 콜 큐를 주간으로 재정렬할 때

---

## 두 축

| 축 | 묻는 것 | 신호 |
|---|---|---|
| **적합도(fit)** | 이 회사가 우리 고객이 될 수 있나 | 수익모델·업종·규모·기술스택 |
| **긴급도(urgency)** | 지금 연락할 이유가 있나 | 임원 발언·투자 유치·채용·발표 이력·경쟁사 접점 |

`scripts/account_score.py`가 유일 계산자다. **손으로 점수 매기지 말 것** — 가중치·구간은 `sales-profile.json`이 기준이다.

```
점수 = 100 × Σ(가중치 × 비율) / Σ(적용된 가중치)
```

### 가장 중요한 규칙 — 모르는 건 0점이 아니라 제외

증거가 없는 신호는 **분모에서 뺀다.** 리서치가 덜 된 계정을 낮은 점수로 묻으면 스코어가 계정의 질이 아니라 **내 리서치 진행도**를 재게 된다. 한 축이 통째로 비면 점수 대신 `리서치 필요`가 나온다.

추측으로 칸을 채우지 말 것. 모르면 그 키를 아예 넣지 않는다.

다만 **너무 적게 알면 점수 자체를 내지 않는다.** 축 가중치의 절반(`min_coverage: 0.5`)을 못 채우면 `리서치 필요`가 나온다 — 이 게이트가 없으면 신호 하나만 맞아도 100점이 나와서 리서치 부족이 고득점으로 둔갑한다(실제로 첫 테스트에서 업종 하나로 적합 100점이 나왔다).

---

## 워크플로

### 1. 리서치 (증거 수집)
축별로 **출처 URL과 함께** 모은다. 없으면 빈칸으로 둔다.

| 신호 | 어디서 |
|---|---|
| 수익모델·업종·규모 | 회사 홈페이지·채용공고·투자 기사 (`web-reader`로 본문 추출) |
| 임원 AI/데이터 발언 | 인터뷰·기고·링크드인 포스트 — **누가, 언제** 말했는지가 핵심 |
| 발표 이력 | 컨퍼런스·세미나 프로그램. **직급이 높을수록 가중** |
| 경쟁사 접점 | 도입 사례·후기·벤더 세미나 참석자 명단 |
| 투자 유치 | `funding-signal-search`, `naver-news-search` — 라운드·금액·날짜(`days_ago`) |
| 채용 | `wanted-search`·`kr-search`·`ats-search`·`hiring-signal-enrich` — 내 제품이 필요해지는 직무인지가 핵심. 예산의 증거는 아님 |

발언·발표는 **며칠 지났는지(`days_ago`)를 반드시 기록한다.** 신선도 감쇠가 적용된다(30일 이내 100% → 1년 20%).

### 1-1. 수집 결과를 채점 입력으로 바꾸기
투자·채용 수집 스크립트의 `--json` 출력은 `signals_to_accounts.py`가 회사당 1줄 입력으로 바꾼다.
확인된 값만 옮기고(업종·규모·투자·채용), 모르는 값은 비워 둔다.
```bash
python3 ${HERMES_SKILL_DIR}/../funding-signal-search/scripts/funding_search.py --json \
  | python3 ${HERMES_SKILL_DIR}/../hiring-signal-enrich/scripts/hiring_enrich.py --json \
  | python3 ${HERMES_SKILL_DIR}/scripts/signals_to_accounts.py \
  | python3 ${HERMES_SKILL_DIR}/scripts/account_score.py --jsonl --json-out > scored.json
```
투자 기사와 채용 공고만으로는 수익모델·기술스택을 모르므로 보통 `리서치 필요`가 나온다.
상위 계정을 `prospect-research`로 조사해 근거를 채우고 다시 채점한다.

### 2. 채점
```bash
python3 ${HERMES_SKILL_DIR}/scripts/account_score.py --in account.json
python3 ${HERMES_SKILL_DIR}/scripts/account_score.py --in accounts.jsonl --jsonl   # 리스트 일괄
```

입력 형식은 스크립트 도큐스트링 참조. 모르는 키는 **생략**한다.

### 3. 판정 → 액션

| 결과 | 조건 | 할 일 |
|---|---|---|
| **지금 콜** | 적합·긴급 둘 다 70+ | 당일 콜 큐. 훅은 긴급도 신호 그대로 사용 |
| **콜 예약** | 적합 70+ · 긴급 45~69 | 이번 주 안에. 트리거 이벤트 하나 더 찾으면 승격 |
| **너처링** | 적합 45+ | 콘텐츠·팔로우만. 신호 뜨면 재채점 |
| **리서치 필요** | 한 축이 통째로 빔 | 채점 대상 아님 — 증거부터 |
| **보류** | 그 외 | 리스트에서 내림 |

### 4. 콜 오프닝
긴급도 최고점 신호를 **그대로 인용**한다. 지어내지 말 것 — `evidence` URL이 있는 것만 말한다.

> "지난달 컨퍼런스에서 CTO님이 데이터 파이프라인 이야기 하신 거 봤습니다."

---

## Pitfalls
- **점수를 손으로 조정하지 말 것.** 기준이 틀렸으면 `sales-profile.json`을 고친다 — 그래야 다음 계정에도 같은 기준이 간다.
- **빈칸을 추측으로 채우지 말 것.** 그 순간 스코어가 거짓말이 된다.
- `sales-profile.json`의 ICP 값은 **예시값**이다. 담당 제품·고객군으로 교체하고 시작할 것.
  스킬 폴더의 파일을 직접 고치지 말고 `$HERMES_HOME/sales-profile.json`으로 복사해서 고치면 업데이트 때 덮이지 않는다.
  (다른 위치는 환경변수 `OUTBOUND_SALES_PROFILE`로 지정.)
- 신선도 없는 임원 발언은 감쇠가 안 걸려 과대평가된다. `days_ago`를 꼭 넣을 것.
- 같은 회사를 여러 번 채점하면 최신 신호로 덮어쓰되, 이전 근거 URL은 남긴다.

## Self-test
```bash
python3 ${HERMES_SKILL_DIR}/scripts/account_score.py --selftest
```
