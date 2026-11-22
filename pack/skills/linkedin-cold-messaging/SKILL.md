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

## 실행 파이프라인 (`linkedin_outbound.py`)

`setup.json`의 ICP를 기반으로 **Boolean X-Ray 검색 쿼리 → Apify LinkedIn Company & 담당자(People) 소싱 → ICP 채점/DNC 필터 → 워밍업 플랜(3~6일) → 300자 연결 요청 & 1촌 DM 시퀀스 → Obsidian `LinkedIn/Queue.md`**까지 한 번에 생성한다.

```bash
# 1) ICP 기반 X-Ray 쿼리 & Apify Actor 입력 JSON 생성
python3 linkedin_outbound.py xray --config setup.json

# 2) Apify 공식 API(APIFY_TOKEN은 $HERMES_HOME/.env에만 저장)로 회사 -> 의사결정자 소싱
python3 linkedin_outbound.py run \
  --config setup.json --home "$HERMES_HOME" --vault ~/Documents/Hermes-GTM \
  --apify-company-actor <owner/company-actor> \
  --apify-people-actor <owner/people-actor> \
  --max-companies 20 --max-people 40

# 3) 또는 Sales Navigator CSV / Apify JSON 파일로 오프라인 실행
python3 linkedin_outbound.py run \
  --config setup.json --home "$HERMES_HOME" --vault ~/Documents/Hermes-GTM \
  --contacts-file ./sales-nav-export.csv
```

- 자동 발송 및 로그인/쿠키 우회는 하지 않는다. 생성된 워밍업 체크리스트와 300자 연결 요청·DM 초안을 사람이 검토 후 직접 발송한다.
