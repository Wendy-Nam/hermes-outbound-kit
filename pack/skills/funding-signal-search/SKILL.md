---
name: funding-signal-search
description: "최근 투자를 유치한 국내 기업을 GTM 타깃 계정 후보로 수집한다. Platum 투자 카테고리(공개 WordPress REST API)에서 회사·라운드·금액·섹터·게시일·링크를 추출. 키 불필요."
version: 1.1.0
author: Hermes Outbound Kit contributors
license: MIT
metadata:
  hermes:
    tags: [GTM, 투자신호, 계정발굴, outbound]
    related_skills: [hiring-signal-enrich, outbound-scoring, signal-outreach-draft, account-crm]
---

# funding-signal-search — 투자 유치 기업 수집

투자 직후 기업은 조직을 키우고 새 도구·서비스를 검토하는 경우가 많다. 그래서 투자 소식은
**지금 연락할 이유(긴급도)의 후보**가 된다. 단, 투자는 내 제품 예산의 증거가 아니다.

## When to use
- "이번 주 투자받은 회사 중 우리 타깃 뽑아줘", "최근 시리즈A 받은 SaaS 리스트"
- GTM 파이프라인 1단계(계정 후보 수집)

## How

```bash
python3 ${HERMES_SKILL_DIR}/scripts/funding_search.py --table    # 표로 보기
python3 ${HERMES_SKILL_DIR}/scripts/funding_search.py --json     # 파이프라인 입력
python3 ${HERMES_SKILL_DIR}/scripts/funding_search.py --pages 4  # 더 많이(페이지당 20건)
```

출력 필드: `company · round · amount · sector · date · url`. 접속에 실패하면 0건이 아니라 실패로 알리고
종료 코드 2를 낸다.

## 전체 GTM 파이프라인

```bash
python3 ${HERMES_SKILL_DIR}/../funding-signal-search/scripts/funding_search.py --json \
  | python3 ${HERMES_SKILL_DIR}/../hiring-signal-enrich/scripts/hiring_enrich.py --json \
  | python3 ${HERMES_SKILL_DIR}/../outbound-scoring/scripts/signals_to_accounts.py \
  | python3 ${HERMES_SKILL_DIR}/../outbound-scoring/scripts/account_score.py --jsonl --json-out > scored.json
python3 ${HERMES_SKILL_DIR}/../signal-outreach-draft/scripts/signal_outreach.py < scored.json     # 초안
python3 ${HERMES_SKILL_DIR}/../account-crm/scripts/account_crm.py --ingest < scored.json          # 계정 장부
```

투자 기사만으로는 수익모델·기술스택을 모르므로 대부분 `리서치 필요`로 나온다. 정상이다.
상위 계정을 `prospect-research`로 조사해 근거를 채운 뒤 다시 채점한다.

## 한계
- 회사명은 기사 제목에서 추출해 노이즈가 있을 수 있다. 정확한 회사명·금액은 기사 본문으로 확인한다.
- 투자사·펀드 결성 뉴스는 제외한다(`벤처스·파트너스·캐피탈`, `펀드 결성·출자`).
- Platum 단일 소스다. 다른 투자 뉴스는 `naver-news-search`로 보완한다.
