---
name: kr-search
description: "사람인·잡코리아 공개 검색 결과에서 채용 공고를 키워드 조회한다. 아웃바운드에서는 특정 직무를 뽑는 회사를 리드 후보·영업 신호로 쓴다. 키 불필요."
version: 1.1.0
author: Hermes Outbound Kit contributors
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [채용신호, 사람인, 잡코리아, saramin, jobkorea, outbound]
    related_skills: [wanted-search, ats-search, buying-signals]
---

# 사람인·잡코리아 채용 공고 조회 (kr-search)

## When to use
- "사람인에서 영업관리 뽑는 제조사 찾아줘", "잡코리아 품질관리 채용 회사" 같은 요청.
- 원티드에 잘 안 올라오는 중견·제조·유통 기업의 채용 신호가 필요할 때.

## How

```bash
S=${HERMES_SKILL_DIR}/scripts/kr_job_search.py
python3 $S "영업관리" --board saramin --limit 20     # 사람인
python3 $S "품질관리" --board jobkorea --limit 15    # 잡코리아
python3 $S "해외영업" --board all --limit 30 --json  # 둘 다, 파이프라인용 JSON
```

기본은 전체 직급이다. `--junior-only`는 구직자용 옵션이다. 보드 조회가 실패하면 "0건"이 아니라
실패로 보고하고 종료 코드 2를 낸다.

## 보드 특성
- **사람인**: 제목·회사명이 모두 파싱된다. 비교적 안정적.
- **잡코리아**: 회사명은 제목의 `[회사명]`에서 추출한다(없으면 공란). 제목·링크는 정확하다.

## 다음 단계
회사명이 비어 있거나 애매하면 공고 링크를 `web-reader`로 열어 확인한 뒤 근거로 남긴다.
그다음 `buying-signals`/`outbound-scoring`에 채용 신호로 넣는다.

## Pitfalls
- 웹 구조가 바뀌면 파싱이 깨질 수 있다. `--json`으로 확인한다.
- 짧은 시간 대량 반복 조회 금지(페이지 사이 1.2초 대기 내장). 로그인·차단 우회는 하지 않는다.
