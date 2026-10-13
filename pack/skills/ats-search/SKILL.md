---
name: ats-search
description: "국내에 지사를 둔 외국계 회사의 채용 공고를 Greenhouse·Lever·Ashby 공개 API에서 직접 조회한다. 아웃바운드에서는 '지금 어떤 직무를 뽑는가'를 영업 신호로 쓴다. 키 불필요."
version: 1.1.0
author: Hermes Outbound Kit contributors
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [채용신호, ats, greenhouse, lever, ashby, 외국계, outbound]
    related_skills: [wanted-search, kr-search, buying-signals, outbound-scoring]
---

# 외국계 ATS 채용 공고 조회 (ats-search)

국내 외국계 기업은 채용 공고를 **Greenhouse/Lever/Ashby**에 올린다. 공개 JSON API라 인증이 필요 없고,
LinkedIn보다 공고가 더 완전하다. 아웃바운드에서는 공고를 **구매 신호의 후보**로 쓴다.
예: 영업·CS·데이터 직무를 새로 여러 개 뽑는다 → 조직 확장 중일 가능성(예산의 증거는 아님).

## How

```bash
S=${HERMES_SKILL_DIR}/scripts/ats_search.py
python3 $S --keyword sales --limit 40                 # 대상 회사 전체에서 Korea + 키워드
python3 $S --keyword "customer success" --json        # 파이프라인 입력용 JSON
python3 $S --company coupang --all-locations          # 한 회사, 지역 제한 없이
```

- 기본은 **Korea 지역 필터 + 전체 직급**이다. `--all-locations`로 지역 제한 해제.
- `--junior-only`는 구직자용 옵션(시니어·리더 제목 제외)이다. 영업 신호 탐색에는 쓰지 않는다.
  리더급 채용(영업본부장, Head of Sales)은 오히려 강한 신호다.
- 조회가 실패하면 "0건"이 아니라 실패로 보고하고 종료 코드 2를 낸다.

## 대상 회사 관리

`${HERMES_SKILL_DIR}/data/ats-targets.json`의 `{company, ats, token}` 목록을 조회한다. 기본 목록은 공개 채용
보드가 확인된 예시 회사들이다. 내 타깃 회사로 바꿔서 쓴다.
- **토큰 찾는 법**: 공고 링크가 `boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`,
  `jobs.ashbyhq.com/<token>` 형태면 그 `<token>`을 추가한다.
- 스킬 폴더 파일을 고치면 키트 재설치 때 "기존 변경 보존"으로 멈출 수 있다. 수정 내용은 따로 기록해 둔다.

## 다음 단계

조회 결과의 회사·직무·링크를 `buying-signals` 근거로 정리하고, `outbound-scoring`의 `urgency.hiring`
신호(텍스트 + 링크)로 넣는다. 공고 1건은 회사 전체 채용 규모나 예산을 증명하지 않는다.

## Pitfalls
- 회사가 ATS나 토큰을 바꾸면 조회가 실패한다(경고 후 건너뜀). 목록을 갱신한다.
- Korea 필터는 location 문자열 기준이다. remote/APAC 공고는 `--all-locations`로 본다.
- 짧은 시간에 반복 조회하지 않는다(회사 사이 0.4초 대기 내장).
