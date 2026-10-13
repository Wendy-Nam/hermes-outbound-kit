---
name: startup-enrich
description: "funded-startup-search로 모은 투자 스타트업에 '채용 긴급도'를 붙인다. 원티드 회사명 질의로 열린 포지션 수·직무목록을 확인 — 투자받고 많이 뽑는 회사일수록 뜨거운 헤드헌팅 BD 타깃."
author: Hermes Outbound Kit contributors
---

# startup-enrich — 채용 긴급도 보강

1단계(`funded-startup-search`)가 '투자받은 회사'를 준다면, 이 스킬은 각 회사가 **실제로 얼마나
뽑는지**를 붙인다. 열린 포지션 수 = 채용 긴급도 = BD 우선순위의 핵심 신호. (투자 1,500억 + 공고
8개 = 즉시 접근할 뜨거운 리드.)

## When to use
- 1단계 수집 직후, BD 타깃 우선순위를 매기기 전
- "이 투자 회사들 지금 뭐 뽑나" 확인

## How

```bash
# 파이프로 연결 — 1단계 출력을 그대로 받는다
python3 ${HERMES_SKILL_DIR}/../funded-startup-search/scripts/funded_search.py --json \
  | python3 ${HERMES_SKILL_DIR}/scripts/startup_enrich.py --limit 12
python3 ${HERMES_SKILL_DIR}/scripts/startup_enrich.py --json   # 파이프라인 입력용 정규화 리스트
```

보강 필드: `open_roles`(원티드 공고 수), `roles`(직무 목록).
`open_roles`: `?`=미확인 · `0`=원티드 미등록(시드단계 흔함) · `N`=채용 중.

## 소스
- **원티드 검색 API**(`/api/chaos/search/v1/results`, 공개). 회사명으로 질의 → `positions.data`에서
  그 회사 공고만 필터해 카운트. 인증불필요.

## ⚠️ VPS 배포 시 프록시 필수
원티드는 **클라우드/데이터센터 IP(호스팅어 등)를 403 차단**한다. 일반 IP(로컬 PC)에선 그냥 되지만,
Hermes VPS에서 돌리려면 프록시를 거쳐야 한다.
- 환경변수 `HERMES_SCRAPER_PROXY`(인증 정보가 포함된 HTTP 프록시 주소, 예: Webshare 개별 프록시)를 설정하면
  원티드 요청이 자동으로 경유한다. 미설정이면 직접(로컬용).
- 프록시 주소는 비밀값이다. 채팅에 붙여넣지 말고 사용자가 직접 서버 `.env`에 넣는다.
- **주의**: 무료티어 개별 프록시는 죽을 수 있다. 죽으면 Webshare API로 새 IP 조회해 교체.
  (1단계 `funded-startup-search`의 Platum은 차단 안 되므로 프록시 불필요.)

## 설계 원칙 (중요)
**스크래퍼는 구조화 데이터만 뽑는다.** 대표/CEO 이름, 제목 노이즈에서 정확 회사명, 본문 금액이
투자금인지 시장규모인지 판별 — 이런 **지저분한 한국어 산문 추출은 regex가 아니라 Hermes LLM
(기사 본문 판독)의 몫**이다. 초기 프로토타입이 regex로 대표를 뽑으려다 "공동"(공동대표에서)·
회사명 조각을 잡는 걸 확인하고, 기계적으로 확실한 것(원티드 공고 수)만 남겼다. 구직 키트와 동일한
분업: **스크래퍼=구조화 / LLM=판단**.

## 한계 (정직)
- **시드단계 미검출**: 갓 투자받은 시드 스타트업은 아직 원티드에 없다(0). 초기 회사 채용신호를
  잡으려면 회사 careers 페이지·로켓펀치를 추가 소스로 붙여야 한다.
- **회사명 변형**: 원티드 등록명이 기사 표기와 크게 다르면(영문병기·법인격) 못 잡을 수 있다.
- 대표·정확 회사명은 판정(LLM) 단계에서 기사 본문으로 확정한다.

## 파이프라인 위치
`funded-startup-search`(수집) → **`startup-enrich`(채용 긴급도)** → 스코어링(라운드×채용볼륨) →
BD 아웃리치 → CRM.
