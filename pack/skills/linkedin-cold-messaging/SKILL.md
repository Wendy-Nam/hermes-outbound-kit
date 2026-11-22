---
name: linkedin-cold-messaging
description: "LinkedIn 콜드 DM을 진정성 있고 짧게 작성하는 절차"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [linkedin, sales, messaging, research]
    category: sales
---

# LinkedIn 콜드 메시징

## 수신자 선정 전: 볼트 지식베이스 먼저 읽기

지식베이스 문서는 **DM 초안 본문에 그대로 복붙하지 않는다**(초안은 상대의 공개 디테일 1~2개로만 짧게 쓴다).
대신 누구에게 말을 걸고 누구를 제외할지 정할 때 볼트 문서를 먼저 읽는다(`outbound` 스킬 절차 준수):

- `Knowledge/영업 포지셔닝.md`: 구매 결정자와 실제 사용자를 구분해 **목표 직무와 제외 직무**를 가른다.
- `Knowledge/먼저 공략할 고객과 피할 고객.md`: 회사 제외 조건과 DNC 후보를 소싱·발송 대상에서 먼저 거른다.
- `Knowledge/경쟁사 비교와 영업 판단.md`: 승산 낮은 상황은 건너뛰고 시도해볼 만한 상황만 선별한다.
- `Accounts/` · `LinkedIn/` 사람 메모: 실제 미팅까지 간 담당자·회사의 공통점을 타깃 선정에 참고한다.

## 작성 원칙
- 상대가 공개한 구체적 디테일을 실제로 읽고 한 가지 이상 개인화한다. 사실을 꾸며내거나 과도하게 칭찬하지 않는다.
- 존댓말을 사용하되, 틀에 박힌 격식어와 영업 문구는 피한다.
- 목적은 채용 부탁이나 즉시 판매가 아니라 배움과 의견 교환으로 명확히 한다.
- 기본 형식은 3문단이다: (1) 공개 디테일에 대한 짧은 관찰, (2) 내가 궁금한 맥락과 배울 점, (3) 부담 없는 의견 교환 제안.
- 수신자를 근거 없이 `Hiring Manager`로 단정하지 않는다. 이 표현은 HR 연락처를 찾는 함정이 될 수 있으므로 실제 역할을 확인한다.

## 개인정보·도구 경계
- 개인정보나 비공개 프로필 정보는 무료 모델·public 위임으로 보내지 않는다. 외부 전송은 먼저 승인을 받는다.
- 공개 정보만 사용하며, 메시지에 필요 이상의 개인정보를 복사하지 않는다.
- 개인화 근거가 부족하면 억지로 작성하지 말고 추가 공개 출처를 조사하거나 보류한다.

## 실행 파이프라인 (`python3 outbound.py linkedin`)

`setup.json`의 ICP를 기반으로 **Boolean X-Ray 검색 쿼리 → Apify LinkedIn Company & 담당자(People) 소싱 → ICP 채점/DNC 필터 → 워밍업 플랜(3~6일) → 300자 연결 요청 & 1촌 DM 시퀀스 → Obsidian `LinkedIn/{회사명}/{이름}.md` + `CRM Board.md`**까지 한 번에 생성한다.

```bash
# 1) ICP 기반 X-Ray 쿼리 & Apify Actor 입력 JSON 생성
python3 outbound.py linkedin xray --config setup.json

# 2) Apify 공식 API(APIFY_TOKEN은 $HERMES_HOME/.env에만 저장)로 회사 -> 의사결정자 소싱
python3 outbound.py linkedin run \
  --config setup.json --home "$HERMES_HOME" --vault ~/Documents/Hermes-GTM \
  --apify-company-actor <owner/company-actor> \
  --apify-people-actor <owner/people-actor> \
  --max-companies 20 --max-people 40

# 3) 또는 Sales Navigator CSV / Apify JSON 파일로 오프라인 실행
python3 outbound.py linkedin run \
  --config setup.json --home "$HERMES_HOME" --vault ~/Documents/Hermes-GTM \
  --contacts-file ./sales-nav-export.csv

# 4) 실제 발송 후에만 단계·연락이력 갱신 + CRM Board 동기화 & 볼트 감사
python3 outbound.py crm stage --vault ~/Documents/Hermes-GTM \
  --note ~/Documents/Hermes-GTM/LinkedIn/회사명/이름.md --to 컨택함 --mark-sent
python3 outbound.py vault audit --vault ~/Documents/Hermes-GTM
```

- **초안 작성과 실제 연락 이력을 엄격히 분리한다** (`메시지상태: 미발송`, `연락횟수: 0`). 공개 게시물이 없으면 성향·문체를 추정하지 않는다.
- 자동 발송 및 로그인/쿠키 우회는 하지 않는다. 생성된 워밍업 체크리스트와 300자 연결 요청·DM 초안을 사람이 검토 후 직접 발송한다.
