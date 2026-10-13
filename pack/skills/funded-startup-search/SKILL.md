---
name: funded-startup-search
description: "최근 투자받은 한국 스타트업을 헤드헌팅 BD 타깃으로 수집한다. Platum 투자 카테고리(공개 WordPress REST API)에서 회사·라운드·금액·섹터·게시일·링크를 구조화 추출. 투자 직후 = 대규모 채용 임박이라 헤드헌터의 선점 타깃."
author: Hermes Outbound Kit contributors
---

# funded-startup-search — 투자받은 스타트업 수집

투자를 막 받은 스타트업은 그 돈으로 사람을 뽑는다. 그래서 **투자 발표 직후가 헤드헌터의 골든타임** —
경쟁 리크루터가 붙기 전에 선점해 플레이스먼트를 제안할 수 있다. 이 스킬은 그 시그널(신규 투자 라운드)을
매일 자동으로 모은다.

## When to use
- "이번 주 투자받은 스타트업 뽑아줘", "최근 펀딩 리스트"
- 헤드헌팅 BD 타깃 파이프라인의 **1단계(시그널)**
- 정기 수집 크론(매일 아침)의 소스

## How

```bash
python3 ${HERMES_SKILL_DIR}/scripts/funded_search.py --table          # 표로 보기
python3 ${HERMES_SKILL_DIR}/scripts/funded_search.py --json           # 정규화 리스트(파이프라인 입력)
python3 ${HERMES_SKILL_DIR}/scripts/funded_search.py --pages 4        # 더 많이(페이지당 20건)
```

출력 필드: `company · round · amount · sector · date · url`

## 소스
- **Platum 투자 카테고리** — WordPress REST API(`/wp-json/wp/v2/posts?categories=7521`).
  공개·인증불필요·합법(RSS/REST는 신디케이션용). 카테고리 ID는 `/categories?search=투자`로 확인.
- 투자사/펀드 결성 뉴스는 제외한다(스타트업이 '받은' 것만). 이름이 `벤처스·파트너스·캐피탈`로
  끝나거나 제목이 `펀드 결성·출자`면 거른다.

## 한계 (정직)
- **회사명 파싱**: 제목이 설명으로 시작하고 회사명이 본문에만 있으면(예: "AI 인프라 스타트업, …")
  회사명이 노이즈일 수 있다. 정확한 회사명·금액은 **startup-enrich 단계의 본문 1-hop**에서 확정한다.
- **금액**: 제목/요약에 없으면 빈값(본문에 있음). enrich 단계가 채운다.
- Platum 단일 소스. 커버리지를 넓히려면 THE VC·벤처스퀘어·로켓펀치를 추가 보드로 붙일 수 있다.

## 파이프라인 위치
`funded-startup-search`(수집) → `startup-enrich`(채용현황·결정권자) → 스코어링 → BD 아웃리치 → CRM.
구직 키트의 수집→스테이징→판정→노트 인프라를 그대로 재사용한다.
