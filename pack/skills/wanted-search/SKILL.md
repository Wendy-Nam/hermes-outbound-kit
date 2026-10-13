---
name: wanted-search
description: "원티드 공개 검색 API로 국내 채용 공고를 키워드 조회한다. 아웃바운드에서는 특정 직무를 뽑는 회사를 찾아 영업 신호 후보로 쓴다. 키 불필요."
version: 1.1.0
author: Hermes Outbound Kit contributors
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [채용신호, 원티드, wanted, outbound]
    related_skills: [kr-search, ats-search, buying-signals, startup-enrich]
---

# 원티드 채용 공고 조회 (wanted-search)

## When to use
- "원티드에서 해외영업 뽑는 회사 찾아줘", "CS 매니저 채용 중인 SaaS 회사" 같은 요청.
- 내 제품이 필요해지는 직무(예: 영업 자료 도구 → 영업 직무 채용 회사)를 뽑는 회사를 리드 후보로 모을 때.

## How

```bash
python3 ${HERMES_SKILL_DIR}/scripts/wanted_search.py "해외영업" --limit 20          # 목록
python3 ${HERMES_SKILL_DIR}/scripts/wanted_search.py "데이터 엔지니어" --limit 30 --json   # 파이프라인용 JSON
```

출력 필드: 제목 · 회사 · 지역 · 보상 · 링크(`wanted.co.kr/wd/<id>`). 기본은 전체 직급이다.
`--junior-only`는 구직자용 옵션이라 영업 신호 탐색에는 쓰지 않는다.

## 다음 단계
결과의 회사명을 `buying-signals`/`outbound-scoring`의 채용 신호로 넣는다. 같은 회사를 여러 번 찾으면
공고 링크를 모두 근거로 남긴다. 공고는 구매 의도나 예산의 증거가 아니다.

## Pitfalls
- 원티드는 클라우드·데이터센터 IP를 차단할 수 있다(서버 설치 시 403). 이때 실패로 보고하고,
  허용된 프록시나 로컬 PC 실행을 사용자에게 안내한다. 차단 우회는 하지 않는다.
- 응답 구조가 바뀌면 결과가 비어 보일 수 있다. `--json`으로 구조를 확인한다.
- 짧은 시간에 대량 반복 조회하지 않는다.
