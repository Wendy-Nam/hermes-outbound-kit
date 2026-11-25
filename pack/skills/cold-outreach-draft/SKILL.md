---
name: cold-outreach-draft
description: 어떤 제품·서비스·출강/컨설팅이든 B2B 콜드메일·DM 초안을 신호(채용 공고, 문의, 검토 이력, 발주계획, 투자, 강사플랫폼/세미나, 링크드인 등) 기반으로 쓰고, 리드 목록이 있으면 한 번에 수백~수천 건을 만든다. 상황별 질문 훅("~하시는 만큼, 혹시 ~지는 않으신가요?"), 상황별 소개 한 문장, "~을 사용하시게 되면, ~. 또한, ~" 이득 문장, 높임 주어·공손형·인과 흐름 점검, 근거 교차검증 HTML 패널 출력, 리드 홈페이지 공개 연락 창구 수집까지 포함. 발송은 하지 않는다.
version: 1.2.0
license: MIT
metadata:
  hermes:
    tags: [GTM, 콜드메일, DM, 아웃바운드, 초안, 프리랜서, 강사, 컨설팅]
    related_skills: [outbound-scoring, evidence-to-outreach, korean-humanizer, gtm-copy-qa, linkedin-cold-messaging]
---

# 콜드메일·DM 초안 (범용 · 키트 통합판)

제품·SaaS·제조·프리랜서 AI 강사/컨설턴트까지 범용으로 쓰는 콜드메일·DM 초안 스킬이다.
규칙은 실제 영업 담당자의 피드백을 수십 차례 반영해 다듬은 결과이며, `copy_guard.py`, `korean-humanizer`, `jev_client.py`, `review_panel.py`(근거 교차검증 패널)와 통합되어 동작한다.

## 파일

| 파일 | 내용 |
|---|---|
| `references/writing-rules.md` | 구조·문형·높임 주어·문장 간 인과/흐름·금지 표현·법 규칙·자체 점검. **초안을 쓰기 전에 반드시 읽는다** |
| `references/profiles/_template.json` | 새 제품/서비스 프로필 양식 |
| `references/profiles/example-helpdesk.json` | 가상 예시 프로필 (B2B SaaS — 헬프데스크X) |
| `references/profiles/example-freelance-instructor.json` | 가상 예시 프로필 (프리랜서 AI 강사 · 기업 출강 · 비즈니스 컨설턴트) |
| `references/sample-leads.csv` | 가상 리드 CSV 예시 (헬프데스크X) |
| `samples/leads-freelance-instructor.csv` | 가상 리드 CSV 예시 (기업 직접 콜드메일 · LinkedIn · 나라장터 · 강사플랫폼/세미나) |
| `scripts/gen_drafts.py` | 프로필 + 리드 CSV → 메일·DM 초안 일괄 생성 + 자동 QA + 근거 교차검증 HTML 패널(`--html`) |
| `scripts/collect_contacts.py` | 리드 홈페이지에서 전화·카카오·톡톡·인스타·문의 페이지 수집 (이메일 주소 자동 수집 금지, SSRF/TLS 안전) |

## 작업 순서

1. `references/writing-rules.md`를 읽는다.
2. 제품·서비스 프로필을 정한다.
   - `references/profiles/`에 맞는 예시가 있으면 복사해 쓴다 (`example-helpdesk.json`, `example-freelance-instructor.json`).
   - 없으면 `_template.json`을 복사해 사용자에게 아래를 받아 채운다.
     - 제품/강의/컨설팅이 무엇인지 한 문장
     - 상황별 고민 → 얻는 결과 3~6개
     - 확인된 가격·플랜·커리큘럼 범위
     - 다른 부서/범위 밖이라 빼야 할 항목
     - 쓰면 안 되는 주장
   - 모르는 사실은 지어내지 말고 `[확인 필요]`로 남긴다.
3. 리드가 한두 곳이면 규칙대로 직접 쓴다.
   - 홈페이지·공고 원문(`evidence_url`)을 먼저 읽고, 상대 상황을 "~하시는 만큼, 혹시 ~"에 자연스럽게 녹인다.
4. 리드가 많으면 CSV를 만들어 생성기를 돌린다.
   ```bash
   python3 outbound.py draft generate \
     --profile pack/skills/cold-outreach-draft/references/profiles/example-freelance-instructor.json \
     --leads samples/leads-freelance-instructor.csv \
     --out ./output/instructor-drafts \
     --html ./output/instructor-review.html
   ```
   - 리드 CSV 열: `lead`(필수), `id`, `signal`(hire|inquiry|review|tender|funding|platform|linkedin|default), `detail`, `site`, `channels`, `tool`, `industry`, `size`, `role`, `product_interest`, `known`, `homepage`, `evidence_url`(또는 `url`), `evidence_date`, `evidence_excerpt`
   - 회사별로 직접 쓴 문장은 `lead_in`, `question`, `benefit`(줄은 ` / `로 구분), `cta` 열에 넣으면 템플릿보다 우선한다.
   - `--copy-guard`를 붙이면 `copy_guard.py` 린터와 통합 점검하고, `--use-jev`를 붙이면 TypeSafe AI Jev 근거 정합성·흐름 QA까지 함께 실행한다(API 키 없으면 자동 생략).
   - `--html <경로>`를 붙이면 사람이 초안과 근거 원문 링크(`evidence_url`, `homepage`)를 나란히 보며 교차검증·승인할 수 있는 단일 HTML 패널을 만든다.
5. 결과 점검:
   - 출력 `flags` 열이 비어 있는지 본다(금지 표현, 자리표시, 높임 주어 오류, 문장 반복, em-dash).
   - 생성된 HTML 패널 또는 표본 5건 이상을 사람 눈으로 읽으며 원문 링크를 직접 열어 교차검증한다.
6. 공개 연락 창구가 필요하면:
   ```bash
   python3 outbound.py draft contacts <id,lead,homepage CSV> <out.csv>
   ```
   - 이메일 주소는 프로그램으로 수집하지 않는다(정보통신망법 제50조의2). "이메일 표기 페이지" 주소만 남기고 사람이 직접 확인한다.

## 지켜야 할 것

- **자동 발송 금지**: 초안만 만든다. 발송·CRM 기록·임시 저장은 사용자가 따로 요청할 때만 한다.
- **사용자 말투 및 `korean-humanizer` 조화**:
  - `korean-humanizer`로 윤문할 때 **아웃바운드·사용자 말투 보존 모드**를 적용한다.
  - 사용자가 의도한 호흡 쉼표(`~하시는 만큼,`, `또한,`, `~사용하시게 되면,`)와 `~할 수 있습니다`는 지우지 않는다.
  - 대신 번역체(`~을 통해` 남발, 이중피동), 훈수 표현(`~것 같았습니다`, `~기 쉽습니다`), 높임 주어 오류, 문장 간 인과 비약·중복을 집중적으로 다듬는다.
- 광고성 메일 법 규칙(정보통신망법 제50조·제50조의2)은 결과 보고 때 한 줄로 다시 알린다.

## 결과 보고

- 만든 건수, 각도(angle)별 분포, flags 건수, 근거 교차검증 패널 경로를 표로 보고한다.
- 표본 1~2건을 원문 그대로 보여 준다.
- 확인이 필요한 사실(가격·기능·일정)을 따로 적는다.
