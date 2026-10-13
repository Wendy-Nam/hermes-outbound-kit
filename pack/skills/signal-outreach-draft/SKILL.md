---
name: signal-outreach-draft
description: "채점된 계정의 실제 신호(투자 유치·채용 직무)를 인용해 내 제품 소개 콜드메일 초안을 만든다. 초안만, 사람이 검토 후 직접 발송."
version: 1.1.0
author: Hermes Outbound Kit contributors
license: MIT
metadata:
  hermes:
    tags: [GTM, 콜드메일, 초안, outbound]
    related_skills: [outbound-scoring, evidence-to-outreach, korean-humanizer, gtm-copy-qa]
---

# signal-outreach-draft — 신호 기반 콜드메일 초안

`outbound-scoring` 결과에서 `지금 콜·콜 예약·너처링` 계정만 골라, 수집된 실제 신호를 첫 문장에 쓰고
내 제품 한 줄과 부담 없는 CTA로 마무리하는 초안을 만든다. 규칙 기반 템플릿이라 모델 없이도 돌아간다.
더 자연스러운 문장은 `evidence-to-outreach`로 다시 쓰고 `korean-humanizer`, `gtm-copy-qa`로 다듬는다.

## How

```bash
# 발신자 정보(1회, 선택)
cp ${HERMES_SKILL_DIR}/profile.example.json "$HERMES_HOME/sender-profile.json"

python3 ${HERMES_SKILL_DIR}/scripts/signal_outreach.py --top 5 < scored.json
python3 ${HERMES_SKILL_DIR}/scripts/signal_outreach.py --include-research < scored.json  # 리서치 필요 계정도
```

- 입력: `account_score.py --jsonl --json-out` 결과.
- 제품·고객: 키트 설치 때 만든 `$HERMES_HOME/outbound-profile.json`의 `product`, `customer`.
- 근거 URL을 초안 아래에 함께 출력한다. 발송 전에 사람이 열어서 확인한다.
- `$HERMES_HOME/do-not-contact.txt`(한 줄에 회사 하나)에 있는 회사와, CRM 상태가 `발굴`이 아닌 계정
  (이미 접촉·진행·보류·실패)은 제외한다. 다시 쓰려면 `--include-contacted`.
- 볼트가 설정되어 있으면 초안을 `GTM/Drafts/<회사>.md` 노트로도 저장하고 계정 노트와 서로 링크한다.
  노트의 `review` 속성(pending → approved/rejected)과 사람 메모는 다시 만들어도 유지된다. `--no-vault`면 화면에만 출력.

## 원칙
- 신호는 수집된 값만 인용한다. 금액·직무를 지어내지 않는다.
- 가설은 질문으로 쓴다. 채용·투자를 예산이나 구매 의사로 단정하지 않는다.
- 자동 발송하지 않는다. 메신저 요청도 발송 허가가 아니다.
