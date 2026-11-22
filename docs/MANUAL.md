# Hermes Outbound Kit 실전 사용 매뉴얼

이 문서는 개발 지식이 없어도 **설치 → 내 영업 스타일 세팅 → 타깃 발굴 → 초안 검토 → 답장·미팅 관리**까지 한 번에 따라 할 수 있도록 정리한 한국어 사용 설명서입니다.

> **참고**: 모든 명령은 키트 폴더의 **`python3 outbound.py <명령>`** 하나로 통일되어 있습니다.
> 또한 이 키트는 **OMH(oh-my-hermes) · OmniRoute에 의존하지 않고** 순정 Hermes에서 독립적으로 동작합니다.

---

## 1. 시작 전 준비물 & 외부 API 키 정리

- **필수**: Python 3.11 이상 (`python3 --version`으로 확인, Windows는 `py -3 --version`)
- **권장**: [Obsidian](https://obsidian.md) (결과 파이프라인과 초안을 한눈에 보고 수정할 때 사용)
- **선택 (필요한 기능만 골라 `~/.hermes-outbound/.env`에 API 키 추가)**:

| 사용하려는 기능 | 권장 설정 (무료 우선) | 없으면 어떻게 되나요? |
|---|---|---|
| **JS/SPA 웹사이트 렌더링** (React·Next 홈페이지, 동적 대리점 목록) | **무료 오픈소스 Crawl4AI** (`pip install crawl4ai && crawl4ai-setup` 또는 로컬 Docker `CRAWL4AI_BASE_URL=http://127.0.0.1:11235`) → 로컬 Playwright → 선택 `FIRECRAWL_API_KEY` | 유료 API 없이 무료 로컬 렌더러를 우선 사용하며, 아무것도 없으면 일반 정적 HTML만 추출하고 설치 안내를 표시합니다 |
| **이미지 공고 · 스캔 브로셔 인식** (사람인·잡코리아 이미지 JD, `.png/.jpg` 소개서) | 무료 로컬 `tesseract` 설치 또는 `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | 이미지 URL만 수집하고 텍스트는 지어내지 않은 채 설치 안내를 표시합니다 |
| **LinkedIn 회사·담당자 자동 소싱** | `APIFY_TOKEN` | 무료 Boolean X-Ray 검색 쿼리 + Sales Navigator CSV 가져오기로 동작합니다 |
| **나라장터(G2B) 실시간 조회** | `DATA_GO_KR_API_KEY` | 공공데이터포털 무료 키. 없으면 샘플/파일 모드로 테스트할 수 있습니다 |
| **허용 소스 전용 프록시** | `WEBSHARE_API_KEY` | 일반 직접 HTTPS 요청으로 동작합니다 (로그인·CAPTCHA 우회는 절대 하지 않습니다) |
| **고속 채점·초안 검수 (TypeSafe AI Jev)** | `TYPESAFE_API_KEY` (또는 `JEV_API_KEY`) | 로컬 결정론적 규칙 엔진으로 100% 동작합니다 |
| **음성 인식(STT) / OAuth 앱 연동** | `GROQ_API_KEY`, `COMPOSIO_CONSUMER_KEY` | 텍스트 기반 워크플로와 Obsidian 볼트만으로 정상 동작합니다 |

> **중요**: 모든 API 키와 비밀번호는 `setup.json`이나 `wizard.html`에 넣지 않고, 내 컴퓨터의 `~/.hermes-outbound/.env` 파일에만 저장합니다.
> 키 연결 상태는 `python3 outbound.py services status --config setup.json --home ~/.hermes-outbound`로 언제든 확인할 수 있습니다.

---

## 2. 1단계: 내 영업 직군에 맞게 초기 세팅하기

가장 편한 방법 하나를 골라 `setup.json`을 만드세요.

### 방법 1. 브라우저에서 클릭해서 만들기 (`wizard.html`)
1. 키트 폴더의 `wizard.html`을 더블클릭해 브라우저로 엽니다.
2. 10개 직군 프리셋 중 나와 가장 가까운 카드를 고릅니다:
   - `b2b-saas` (B2B SaaS · AI/데이터)
   - `hr-recruiting` (HR · 채용 · 교육 · 복지)
   - `manufacturing-smartfactory` (제조 · 스마트팩토리 · 장비)
   - `marketing-commerce` (마케팅 · 커머스 · 에이전시)
   - `logistics-trade` (물류 · 수출입 · SCM · 무역)
   - `cloud-security-it` (클라우드 · 보안 · IT 인프라)
   - `fintech-finance` (핀테크 · 재무/회계 · 법인금융)
   - `public-b2g` (공공조달 B2G · 정부지원)
   - `overseas-b2b-direct` (해외 B2B 엔드유저 직접 영업)
   - `overseas-distributor` (해외 대리점 · 총판 · 수입상 개척)
3. 회사 소개글이나 평소 보낸 영업 메일이 있다면 Step 1 안의 **"붙여넣기 → 자동 세팅"**을 눌러 자동 입력합니다.
4. 맨 아래 **`setup.json 생성 및 다운로드`**를 눌러 키트 폴더에 저장합니다.

### 방법 2. 우리 회사 브로셔 + 자사/경쟁사 홈페이지로 자동 세팅
```sh
python3 outbound.py profile bootstrap \
  --company-url https://company.example.com \
  --competitor-url https://competitor.example.com \
  --brochure ./회사소개서.pptx \
  --output setup.json \
  --insights ./Targeting-Insights.md \
  --sync --force
```
- **지원 브로셔 형식**: `.pptx`, `.docx`, `.pdf`, `.md`, `.txt`, `.html` + **이미지 브로셔(`.png`, `.jpg`, `.jpeg`, `.webp`)**
- **JS/SPA 웹사이트 지원**: 자사/경쟁사 홈페이지가 React/Next 등 클라이언트 렌더링 페이지인 경우, `~/.hermes-outbound/.env`에 `FIRECRAWL_API_KEY`가 있으면 자동으로 Firecrawl로 렌더링해 내용을 추출합니다.
- 자동으로 추천 직군 프리셋, 핵심 키워드, 기술스택, 경쟁사 차별화 포인트, 경쟁사 연락금지(DNC) 목록까지 뽑아 `Targeting-Insights.md`와 `setup.json`에 정리합니다.

### 방법 3. 내 개인 발신메일함으로 내 말투 학습시키기 (개인정보 미저장)
평소 내가 쓰는 인사말, 문단 호흡, 하십시오체/해요체 비율, CTA 스타일을 추출합니다. 고객 이메일·전화번호 등은 모두 익명화하며 원문 메일은 저장하지 않습니다.

```sh
# 1) 내 PC에 있는 Thunderbird / Apple Mail / 다운로드 .mbox/.eml 자동 찾기
python3 outbound.py profile style --discover

# 2) 발신함 파일 분석 후 적용 (Gmail Takeout .mbox, .eml 폴더, 텍스트/CSV 지원)
python3 outbound.py profile style --mbox ~/Downloads/Sent.mbox --config setup.json --apply
```
읽기 전용 IMAP(Gmail/Naver 등)을 쓸 때는 터미널 환경변수(`OUTBOUND_IMAP_USER`, `OUTBOUND_IMAP_PASSWORD`)를 지정한 뒤 `--imap-host imap.gmail.com`을 사용합니다.

---

## 3. 2단계: 설치 및 첫 샘플 실행 확인

먼저 외부 로그인이나 비용 없이 오프라인으로 설치와 결과물 흐름을 확인합니다.

```sh
# 전체 설치 + 샘플 실행 + Obsidian 볼트 생성 (오프라인)
python3 outbound.py setup --config setup.json --offline --no-launch
```

완료되면 **Obsidian**에서 `~/Documents/Hermes-GTM` 폴더를 "폴더를 볼트로 열기"로 여세요.
- `Dashboard.md`: 전체 실행 현황 요약
- `GTM/Pipeline.md`: 영업 파이프라인 표 (지금 콜 / 콜 예약 / 너처링 / 리서치 필요)
- `GTM/Accounts/<회사>.md`: 내가 `status`나 `## 사람 메모`를 수정해도 다음 실행 때 덮어쓰지 않고 보존됩니다.
- `Drafts/` · `Review/`: 3~4줄 담백한 초안 + `[발송 전 내 말로 바꿀 1줄 메모]`

초안 스타일만 빠르게 보고 싶을 때:
```sh
python3 outbound.py profile preview --config setup.json
```

---

## 4. 3단계: 실전 타깃 발굴 실행하기

### A. 국내 채용 공고 · 투자 뉴스 · 나라장터(G2B)
```sh
# 채용 공고 (원티드·사람인·잡코리아·점핏·ATS 멀티 보드 + 중복 병합)
python3 outbound.py run --config setup.json --scenario job_signal --source-mode live \
  --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM

# 투자 유치 기업 + 원티드 채용 현황 자동 보강
python3 outbound.py run --config setup.json --scenario funding_signal --source-mode live \
  --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM

# 나라장터(G2B) 입찰공고 (~/.hermes-outbound/.env에 DATA_GO_KR_API_KEY 필요)
python3 outbound.py run --config setup.json --scenario tender_watch --source-mode live \
  --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM

# 결과를 엑셀용 CSV로도 같이 뽑고 싶을 때 (수식 주입 방지 적용)
python3 outbound.py run --config setup.json --source-mode live --export-csv ./leads.csv \
  --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM
```

연락 금지 회사(기존 고객·경쟁사)나 관심 회사 ATS 보드 관리:
```sh
python3 outbound.py profile dnc --add "기존고객A" --add "경쟁사B"
python3 outbound.py profile ats --add "greeting:company-slug:관심회사"
```

> **이미지 채용공고(사람인·잡코리아) 인식 안내**
> 텍스트 대신 통이미지로 올라온 채용공고는 `src/core/web_extract.py`와 `sources.enrich_image_job()`을 통해
> 1) 로컬 무료 `tesseract`(`kor+eng`) → 2) `.env`의 `OPENAI_API_KEY`/`OPENROUTER_API_KEY` Vision API 순으로 자동 텍스트 추출을 시도합니다. 둘 다 없으면 이미지 URL을 그대로 보존하고 텍스트를 지어내지 않습니다.

### B. LinkedIn 아웃바운드 (ICP → Apify 소싱 또는 Sales Nav CSV → 워밍업/DM)
1. 먼저 ICP 기반 Boolean X-Ray 검색 쿼리와 Apify 입력 JSON을 확인합니다:
   ```sh
   python3 outbound.py linkedin xray --config setup.json
   ```
2. **Apify 공식 API로 LinkedIn 회사 → 의사결정자 소싱** (`~/.hermes-outbound/.env`에 `APIFY_TOKEN` 설정 필요):
   ```sh
   python3 outbound.py linkedin run \
     --config setup.json --home ~/.hermes-outbound --vault ~/Documents/Hermes-GTM \
     --apify-company-actor <owner/company-actor> \
     --apify-people-actor <owner/people-actor> \
     --max-companies 20 --max-people 40
   ```
3. 또는 **Sales Navigator CSV / Apify JSON 파일**로 바로 실행:
   ```sh
   python3 outbound.py linkedin run \
     --config setup.json --home ~/.hermes-outbound --vault ~/Documents/Hermes-GTM \
     --contacts-file ./sales-nav-export.csv
   ```
결과는 Obsidian `LinkedIn/Queue.md`와 담당자별 노트(3~6일 워밍업 체크리스트 + 300자 제한 검증된 연결 요청 + 1촌 DM + 팔로업)로 저장됩니다.

### C. 해외 B2B 엔드유저 직접 영업 & 해외 대리점·총판 발굴
해외 영업은 **최종 도입 기업 직접 영업(`--mode end_user`, 기본값)**과 **현지 대리점·총판 개척(`--mode distributor`)**을 선택해 실행합니다.

```sh
# 1) 해외 B2B 엔드유저 직접 영업 (미국·독일·일본 등 최종 고객사 발굴 + 현지 네이티브 초안)
python3 outbound.py overseas --mode end_user \
  --config setup.json --file ./overseas-targets.csv \
  --country US --country DE --country JP \
  --vault ~/Documents/Hermes-GTM

# 2) 해외 대리점·총판·수입상 발굴 (경쟁사 Where-to-Buy/Distributors 페이지 또는 전시회 참가사 CSV)
#    SPA(JS 렌더링) 페이지라도 FIRECRAWL_API_KEY가 있으면 자동 렌더링 fallback
python3 outbound.py overseas --mode distributor \
  --config setup.json \
  --distributor-url https://competitor.example.com/distributors \
  --country DE --country JP --competitor-brand "CompBrand" --cert CE \
  --vault ~/Documents/Hermes-GTM
```
- 국가 코드에 맞춰 **영어(`en`)·일본어(`ja`)·독일어(`de`)·한국어(`ko`)** 네이티브 초안을 자동 생성합니다.
- 결과 JSON에는 발굴된 해외 기업들의 의사결정자를 LinkedIn/Apify로 바로 찾을 수 있는 `linkedin_handoff`도 함께 포함됩니다.

---

## 5. 4단계: 발송 전 검수 · 답장 분석 · 미팅 · 도메인 점검

### 1~4차 멀티터치 시퀀스 생성 & 스팸어/가독성 점검
```sh
# 1~4차 시퀀스 생성 (각 회차별 스팸/분량 점수 자동 표시)
python3 outbound.py copy sequence --company "예시기업" --title "데이터 엔지니어" --config setup.json

# 내가 직접 쓴 메일 초안 검수 (스팸어·과장/훈수 표현·미치환 변수·길이 체크)
python3 outbound.py copy lint --subject "짧은 확인" --file ./my-draft.txt
```

### 답장 11라벨 분류 · 긍정 회신율 · 수신거부 자동 차단
```sh
python3 outbound.py replies \
  --input ./replies.csv --sent 300 --campaign "2026-Q2" \
  --apply-suppression --home ~/.hermes-outbound --vault ~/Documents/Hermes-GTM
```
- `관심 / 자료요청 / 담당자소개 / 질문 / 시기아님 / 부적합 / 항의 / 수신거부 / 부재중 / 바운스 / 기타`로 자동 분류합니다.
- `수신거부 · 바운스 · 항의`는 자동으로 `~/.hermes-outbound/do-not-contact.txt`에 등록되어 재발송 사고를 막습니다.
- 결과는 `GTM/Results.md`와 `GTM/LEARNINGS.md`에 누적됩니다.

### 미팅 전 1장 브리핑 · 미팅 후 팔로업 · 발신 도메인 헬스체크
```sh
# 미팅 전 1장 브리핑 (볼트 근거 + 회사 홈페이지 요약 + 핵심 질문 3개)
python3 outbound.py meeting prep --company "알파데이터" --attendee "김팀장" \
  --company-url https://company.example.com --vault ~/Documents/Hermes-GTM

# 미팅 메모 -> 합의된 다음 단계 & 담백한 리캡 메일 초안
python3 outbound.py meeting post --company "알파데이터" --attendee "김팀장" \
  --notes-file ./meeting-notes.txt --vault ~/Documents/Hermes-GTM

# 콜드메일 발송 전 도메인 SPF / DKIM / DMARC / MX 점검
python3 outbound.py health --domain example.com
```

---

## 6. 실전 영업 옵스 운영 (CRM Kanban · 볼트 감사 · G2B 차분 감시 · 데일리 브리핑)

매일 영업 파이프라인을 굴릴 때 생기는 오탐·중복·보드 불일치·초안/발송 혼동을 막아주는 운영 도구입니다.

### A. Obsidian Kanban 보드 동기화 & 볼트 무결성 자동 감사
- LinkedIn 소싱 시 개인 리드는 `LinkedIn/{회사명}/{이름}.md`에 저장되며, **초안 작성(`메시지상태: 미발송`, `연락횟수: 0`)과 실제 발송 이력이 엄격히 분리**됩니다.
- 공개 게시물이 없으면 상대 성향·문체를 추측하지 않고 사실 근거만 기록합니다.
```sh
# 1) 쉬운 한국어 영업 포지셔닝 · 경쟁사 판단 · 기록 기준 문서 4종 생성
python3 outbound.py crm knowledge --config setup.json --vault ~/Documents/Hermes-GTM

# 2) 실제 발송 후 단계 변경 + CRM Board.md 동시 동기화 (초안 수정만으로는 연락횟수 미증가)
python3 outbound.py crm stage --vault ~/Documents/Hermes-GTM \
  --note ~/Documents/Hermes-GTM/LinkedIn/예시기업/홍길동.md --to 컨택함 --mark-sent

# 3) 볼트 무결성 전체 감사 (YAML 오류 · 보드 불일치 · 중복 URL/ID · 깨진 위키링크 · 표 열 깨짐 · 예시 리드 혼입)
python3 outbound.py vault audit --vault ~/Documents/Hermes-GTM
```

### B. 나라장터(G2B) 발주계획 · 사전규격 · 입찰공고 기준선 차분 감시
발주계획(초기 선제 신호)과 실제 입찰공고를 구분하고, 카페/편의시설 같은 잡음 오탐을 자동 제외합니다.
```sh
# 1) 초기 기준선 저장 (--initialize)
python3 outbound.py g2b --keywords "의료후송,의료지원,비상대피" \
  --stages order_plan,prespec,bid_notice --context-keywords "해외,파견,귀환" \
  --initialize --vault ~/Documents/Hermes-GTM

# 2) 이후 매일 실행: 신규·변경 항목만 추출해 원장 갱신
python3 outbound.py g2b --keywords "의료후송,의료지원,비상대피" \
  --stages order_plan,prespec,bid_notice --context-keywords "해외,파견,귀환" \
  --vault ~/Documents/Hermes-GTM
```

### C. 경쟁사 역추적 마켓 인텔리전스 · 쉬운 한국어 문체 감사 · 데일리 브리핑
```sh
# 경쟁사 공개 사례 -> "돈을 쓴 문제" 역추적 -> 비슷한 타깃 큐(Lookalike-Queue.md) 생성
python3 outbound.py intel --input ./competitor-signals.csv --competitor "GlobalCorp" --vault ~/Documents/Hermes-GTM

# 영업 전략 문서·제안서의 어려운 컨설팅 표현 & 마크다운 표 열 깨짐 자동 감사
python3 outbound.py copy lint --mode doc --file ~/Documents/Hermes-GTM/Knowledge/영업\ 포지셔닝.md

# 오늘 현황 · 미발송 초안 · G2B · 경쟁사 신호 · 볼트 감사 데일리 브리핑
python3 outbound.py briefing --vault ~/Documents/Hermes-GTM --text

# 예약 실행 등록 직후 즉시 수동 검증까지 함께 실행
python3 outbound.py operations install --config setup.json --apply --verify
```

---

## 7. 선택 효율화: TypeSafe AI Jev 연결하기

리드가 많아지거나 AI 초안 비용을 줄이고 싶을 때만 선택해서 켭니다.

1. `~/.hermes-outbound/.env` 파일에 아래 한 줄을 추가합니다:
   ```ini
   TYPESAFE_API_KEY=발급받은_키
   ```
   (`JEV_API_KEY` 이름도 동일하게 인식합니다.)
2. `setup.json`에서 `"jev_enabled": true`(초안 검수까지 원하면 `"jev_qa_drafts": true`)로 바꿉니다.
3. 연결 확인:
   ```sh
   python3 outbound.py jev probe --home ~/.hermes-outbound
   ```
키가 없거나 네트워크 오류가 나면 자동으로 로컬 규칙 엔진으로 폴백하므로 작업이 멈추지 않습니다.

---

## 8. 자주 묻는 질문 (문제 해결)

- **일부 채용 사이트가 `blocked(403/429)`로 뜹니다.**
  - 클라우드 서버 IP나 과도한 요청은 사이트에서 차단할 수 있습니다. `jobs_partial_ok: true`가 켜져 있으면 성공한 보드 결과만 안전하게 유지합니다. 로그인/CAPTCHA 우회는 하지 않으며, 필요 시 CSV `file` 모드로 가져올 수 있습니다.
- **React/Next로 만든 회사 홈페이지가 빈 내용으로 나옵니다. 유료 Firecrawl이 꼭 필요한가요?**
  - 아닙니다! **무료 오픈소스 Crawl4AI**(`pip install crawl4ai && crawl4ai-setup` 또는 로컬 Docker `CRAWL4AI_BASE_URL=http://127.0.0.1:11235`)나 로컬 **Playwright**가 설치되어 있으면 유료 키 없이 1순위로 자동 사용합니다. `FIRECRAWL_API_KEY`는 로컬 브라우저 설치가 번거로울 때만 쓰는 선택 옵션입니다.
- **이미 수정한 Obsidian 노트가 덮어씌워질까 봐 걱정됩니다.**
  - `GTM/Accounts/`의 `status`와 `## 사람 메모`, `Review/` 노트, 그리고 이미 연락이 시작된 `LinkedIn/` 리드 노트는 사람 소유 영역으로 보호되어 재실행해도 덮어쓰지 않습니다.
- **설정을 잘못 건드렸거나 다시 확인하고 싶습니다.**
  - `python3 outbound.py validate --config setup.json`으로 설정 오류를 바로 확인할 수 있고, `wizard.html` 왼쪽의 **"기존 setup.json 불러오기"** 버튼으로 불러와 고칠 수 있습니다.
