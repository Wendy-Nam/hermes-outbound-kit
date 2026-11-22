---
name: overseas-partner-research
description: 제품·국가·파트너 유형을 확인해 해외 파트너 후보를 공개 근거로 조사하고 검토용 제안 초안을 만듭니다.
---

# 해외 파트너 조사

## 먼저 물어볼 것

제품·해결하는 문제, 판매 국가, 필요한 유형(대리점/유통사/수입사/사용기업), 필수 인증과
최소 조건을 한 번에 1~3개씩 확인합니다. 조건을 모르면 정하지 말고 후보 기준 초안을 제안합니다.

## 단계별 실행

1. 키트의 `workflow.py --help`, `distributor_finder.py --help`, `docs/MANUAL.md`를 확인합니다.
   `overseas_partner`는 공개 RSS 피드·글로벌 ATS live 수집과 CSV/JSON file 모드를 모두 지원하며,
   해외 B2B 엔드유저 직접 영업(`--mode end_user`) 및 대리점 발굴(`--mode distributor`)은 `distributor_finder.py`로 실행합니다.
   샘플을 실제 발굴 결과처럼 보여 주지 않습니다.
2. 사용 가능한 승인된 웹 도구로 공식 기업 사이트, 제조사의 공개 대리점 목록, 전시회 공개
   참가사 목록, KOTRA·tradeKorea 공개 디렉토리를 조사합니다. 로그인·CAPTCHA는 우회하지 않습니다.
   ImportYeti/FDA/EUDAMED 등은 제품·국가에 맞고 접근 가능한 경우에만 보조 근거로 사용합니다.
3. 후보마다 법인명·국가·공식 도메인·취급 제품·파트너 적합 근거·출처 URL·조회일·미확인 사항을
   기록합니다. 브랜드와 법인을 구분하고, 이메일·담당자·수입 실적을 지어내지 않습니다.
4. `sources.py --help`의 typed import 계약에 맞춰 해외 후보를 정규화합니다. 키트 계약 밖의
   임의 JSON을 실행기에 전달하지 않습니다. source_id와 원문 링크를 보존합니다.
5. 사용자 제품과 후보의 공개 근거를 연결한 영문 또는 요청 언어의 초안을 만듭니다.
   이메일 제목 2개, 짧은 본문, 낮은 부담의 질문 하나, 출처와 확인할 주장을 별도로 제공합니다.
6. `workflow.py`의 file 모드 또는 제공 초안 모드로 Obsidian의 근거→분석→초안→검토에 연결합니다.
   먼저 실제 도움말로 옵션을 확인합니다. 인간 검토와 이전 노트를 보존합니다.

## 품질·안전

국가·제품 적합도, 근거 확인 범위, 미확인 항목을 분리합니다. 후보 발견은 거래 가능성 검증이
아닙니다. 자동 DM·메일·폼 제출·CRM 등록·유료 데이터 구매는 하지 않습니다. 사용자의 내부
매출·가격·고객 리스트를 외부 검색어에 넣지 않습니다.

## 실행 파이프라인 (`distributor_finder.py`)

해외 영업은 **엔드유저 직접 B2B(`--mode end_user`, 기본값)**와 **현지 대리점·총판·수입상 개척(`--mode distributor`)** 두 가지 모드를 모두 지원한다.

```bash
# 1) 해외 B2B 엔드유저 직접 영업 (전시회 참가사/업종 디렉터리 -> 4축 채점 -> 현지어 초안 + LinkedIn 의사결정자 핸드오프)
python3 distributor_finder.py --mode end_user \
  --config setup.json --file ./exhibitors.csv --country US --country DE --country JP \
  --vault ~/Documents/Hermes-GTM

# 2) 해외 대리점·총판·수입상 발굴 (경쟁사 Where-to-Buy/Distributors 페이지 또는 CSV -> 대리점 4축 채점 -> EN/JA/DE/KO 초안)
python3 distributor_finder.py --mode distributor \
  --config setup.json --distributor-url https://competitor.example.com/distributors \
  --country DE --country JP --competitor-brand "CompBrand" --cert CE \
  --vault ~/Documents/Hermes-GTM
```

- 발굴된 해외 기업 리스트는 자동으로 `linkedin_handoff`(타깃 회사별 X-Ray 쿼리 + Apify People 입력)까지 생성되어 현지 의사결정자(VP/Head/Director/Plant Manager) 소싱으로 바로 이어진다.
- 출력은 후보별 근거와 검토용 초안이며, `review_required=true`, `automatic_send=false`입니다.
