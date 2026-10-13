---
name: startup-score
description: "보강된 투자 스타트업을 헤드헌팅 BD 우선순위로 랭크한다. 우선도 = 라운드규모 + 채용볼륨×1.5 + 신선도 + 섹터적합. '돈만 받은 회사'가 아니라 '지금 실제로 뽑는 회사'를 위로 올린다."
author: Hermes Outbound Kit contributors
---

# startup-score — BD 우선순위 랭킹

1·2단계가 모은 데이터(투자 라운드 + 채용현황)를 하나의 점수로 합쳐 **랭크된 BD 히트리스트**를 만든다.
헤드헌터가 위에서부터 순서대로 공략하면 되게.

## 우선도 공식

```
우선도 = 라운드규모 + 채용볼륨 × 1.5 + 신선도 + 섹터적합
```

- **라운드규모**: 금액(1,000억↑=5 … <10억=1). 금액 없으면 라운드 단계(시리즈C=4.5 … 시드=1.5).
- **채용볼륨**(열린 포지션): `0=0 · 1~2=1 · 3~5=2 · 6~10=3 · 10+=4`. **×1.5 최대 가중** — 실제로 뽑는 회사가 최고 타깃.
- **신선도**: 투자 후 `≤7일=3 · ≤14=2 · ≤30=1 · 그 외=0.5`. 직후일수록 경쟁 리크루터 미접촉.
- **섹터적합**: `--sectors`에 매치하면 +1.

**설계 의도**: 채용볼륨 가중 덕에 "1,000억 받았지만 공고 0"인 회사가 "165억+7공고"인 회사보다
아래로 간다 — 돈이 아니라 채용 활동이 BD 기회다.

## How

```bash
python3 ${HERMES_SKILL_DIR}/../funded-startup-search/scripts/funded_search.py --json \
  | python3 ${HERMES_SKILL_DIR}/../startup-enrich/scripts/startup_enrich.py --json \
  | python3 ${HERMES_SKILL_DIR}/scripts/startup_score.py --sectors "AI,로보틱스" --top 15
python3 ${HERMES_SKILL_DIR}/scripts/startup_score.py --json   # 정규화 리스트(CRM 노트 입력)
```

## 파이프라인 위치
`funded-startup-search` → `startup-enrich` → **`startup-score`** → BD 아웃리치 → CRM.
여기까지가 "타깃 발굴"이고, 다음은 상위 타깃에 실제로 연락하는 아웃리치 단계다.
