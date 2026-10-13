---
name: hiring-signal-enrich
description: "계정 후보 목록(예: funding-signal-search 결과)에 원티드 공개 공고 수·직무를 붙여 채용 신호를 보강한다. 키 불필요."
version: 1.1.0
author: Hermes Outbound Kit contributors
license: MIT
metadata:
  hermes:
    tags: [GTM, 채용신호, 원티드, outbound]
    related_skills: [funding-signal-search, wanted-search, outbound-scoring]
---

# hiring-signal-enrich — 채용 신호 보강

회사별로 지금 어떤 직무를 뽑는지 붙인다. 내 제품이 필요해지는 직무(예: 데이터 도구 → 데이터 엔지니어,
영업 자료 도구 → 영업 직무)를 뽑는 회사는 긴급도가 올라간다. 공고는 예산의 증거가 아니다.

## How

```bash
python3 ${HERMES_SKILL_DIR}/../funding-signal-search/scripts/funding_search.py --json \
  | python3 ${HERMES_SKILL_DIR}/scripts/hiring_enrich.py --limit 12 --json
```

보강 필드: `open_roles`(원티드 공고 수), `roles`(직무 목록).
`open_roles`: `null`=조회 실패 · `0`=원티드에 없음(채용 안 함이 아님) · `N`=공고 N건.
다음 단계는 `outbound-scoring`의 `signals_to_accounts.py`다. 어떤 직무가 신호인지는
`sales-profile.json`의 `hiring_bands`에서 정한다.

## 서버에서 쓸 때
원티드는 클라우드·데이터센터 IP를 차단할 수 있다. 허용된 프록시가 있으면 환경변수
`HERMES_SCRAPER_PROXY`(인증 정보가 포함된 HTTP 프록시 주소)를 사용자가 직접 서버 `.env`에 넣는다.
프록시 주소는 비밀값이라 채팅에 붙여넣지 않는다. 차단 우회는 하지 않는다.

## 한계
- 갓 생긴 회사는 원티드에 없을 수 있다. 회사 채용 페이지나 `kr-search`로 보완한다.
- 원티드 등록명이 기사 표기와 다르면 못 찾을 수 있다.
- 회사명 판별·대표자 같은 산문 추출은 스크립트가 아니라 모델이 기사 본문을 읽고 한다.
