# Hermes Outbound Kit 실전 사용 매뉴얼

이 문서는 개발 지식이 없어도 **설치 → 내 영업 스타일 세팅 → 타깃 발굴 → 초안 검토 → 답장·미팅 관리**까지 한 번에 따라 할 수 있도록 정리한 한국어 사용 설명서입니다.

---

## 1. 시작 전 준비물

- **필수**: Python 3.11 이상 (`python3 --version`으로 확인, Windows는 `py -3 --version`)
- **권장**: [Obsidian](https://obsidian.md) (결과 파이프라인과 초안을 한눈에 보고 수정할 때 사용)
- **선택 (나중에 필요할 때만)**:
  - AI 모델 연결: OpenAI / Anthropic / Google / OpenRouter 등 (없어도 규칙 기반 초안으로 100% 동작)
  - `APIFY_TOKEN`: LinkedIn 회사·담당자를 Apify로 자동 소싱할 때
  - `DATA_GO_KR_API_KEY`: 나라장터(G2B) 입찰공고를 실시간 조회할 때 (공공데이터포털 무료 키)
  - `TYPESAFE_API_KEY` (또는 `JEV_API_KEY`): 대량 리드 사전 필터링·채점·답장 분류를 고속 처리할 때

> **중요**: 모든 API 키와 비밀번호는 `setup.json`이 아니라 내 컴퓨터의 `~/.hermes-outbound/.env` 파일에만 넣습니다.

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
python3 profile.py bootstrap \
  --company-url https://company.example.com \
  --competitor-url https://competitor.example.com \
  --brochure ./회사소개서.pptx \
  --output setup.json \
  --insights ./Targeting-Insights.md \
  --sync --force
```
- 지원 파일: `.pptx`, `.docx`, `.pdf`, `.md`, `.txt`, `.html`
- 자동으로 추천 직군 프리셋, 핵심 키워드, 기술스택, 경쟁사 차별화 포인트, 경쟁사 연락금지(DNC) 목록까지 뽑아 `Targeting-Insights.md`와 `setup.json`에 정리합니다.

### 방법 3. 내 개인 발신메일함으로 내 말투 학습시키기 (개인정보 미저장)
평소 내가 쓰는 인사말, 문단 호흡, 하십시오체/해요체 비율, CTA 스타일을 추출합니다. 고객 이메일·전화번호 등은 모두 익명화하며 원문 메일은 저장하지 않습니다.

```sh
# 1) 내 PC에 있는 Thunderbird / Apple Mail / 다운로드 .mbox/.eml 자동 찾기
python3 profile.py style --discover

# 2) 발신함 파일 분석 후 적용 (Gmail Takeout .mbox, .eml 폴더, 텍스트/CSV 지원)
python3 profile.py style --mbox ~/Downloads/Sent.mbox --config setup.json --apply
```
읽기 전용 IMAP(Gmail/Naver 등)을 쓸 때는 터미널 환경변수(`OUTBOUND_IMAP_USER`, `OUTBOUND_IMAP_PASSWORD`)를 지정한 뒤 `--imap-host imap.gmail.com`을 사용합니다.

---

## 3. 2단계: 설치 및 첫 샘플 실행 확인

먼저 외부 로그인이나 비용 없이 오프라인으로 설치와 결과물 흐름을 확인합니다.

```sh
# 전체 설치 + 샘플 실행 + Obsidian 볼트 생성 (오프라인)
python3 installer.py setup --config setup.json --offline --no-launch
```

완료되면 **Obsidian**에서 `~/Documents/Hermes-GTM` 폴더를 "폴더를 볼트로 열기"로 여세요.
- `Dashboard.md`: 전체 실행 현황 요약
- `GTM/Pipeline.md`: 영업 파이프라인 표 (지금 콜 / 콜 예약 / 너처링 / 리서치 필요)
- `GTM/Accounts/<회사>.md`: 내가 `status`나 `## 사람 메모`를 수정해도 다음 실행 때 덮어쓰지 않고 보존됩니다.
- `Drafts/` · `Review/`: 3~4줄 담백한 초안 + `[발송 전 내 말로 바꿀 1줄 메모]`

초안 스타일만 빠르게 보고 싶을 때:
```sh
python3 profile.py preview --config setup.json
```

---

## 4. 3단계: 실전 타깃 발굴 실행하기

### A. 국내 채용 공고 · 투자 뉴스 · 나라장터(G2B)
```sh
# 채용 공고 (원티드·사람인·잡코리아·점핏·ATS 멀티 보드 + 중복 병합)
python3 workflow.py run --config setup.json --scenario job_signal --source-mode live \
  --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM

# 투자 유치 기업 + 원티드 채용 현황 자동 보강
python3 workflow.py run --config setup.json --scenario funding_signal --source-mode live \
  --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM

# 나라장터(G2B) 입찰공고 (~/.hermes-outbound/.env에 DATA_GO_KR_API_KEY 필요)
python3 workflow.py run --config setup.json --scenario tender_watch --source-mode live \
  --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM

# 결과를 엑셀용 CSV로도 같이 뽑고 싶을 때 (수식 주입 방지 적용)
python3 workflow.py run --config setup.json --source-mode live --export-csv ./leads.csv \
  --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM
```

연락 금지 회사(기존 고객·경쟁사)나 관심 회사 ATS 보드 관리:
```sh
python3 profile.py dnc --add "기존고객A" --add "경쟁사B"
python3 profile.py ats --add "greeting:company-slug:관심회사"
```

### B. LinkedIn 아웃바운드 (ICP → Apify 소싱 또는 Sales Nav CSV → 워밍업/DM)
1. 먼저 ICP 기반 Boolean X-Ray 검색 쿼리와 Apify 입력 JSON을 확인합니다:
   ```sh
   python3 linkedin_outbound.py xray --config setup.json
   ```
2. **Apify 공식 API로 LinkedIn 회사 → 의사결정자 소싱** (`~/.hermes-outbound/.env`에 `APIFY_TOKEN` 설정 필요):
   ```sh
   python3 linkedin_outbound.py run \
     --config setup.json --home ~/.hermes-outbound --vault ~/Documents/Hermes-GTM \
     --apify-company-actor <owner/company-actor> \
     --apify-people-actor <owner/people-actor> \
     --max-companies 20 --max-people 40
   ```
3. 또는 **Sales Navigator CSV / Apify JSON 파일**로 바로 실행:
   ```sh
   python3 linkedin_outbound.py run \
     --config setup.json --home ~/.hermes-outbound --vault ~/Documents/Hermes-GTM \
     --contacts-file ./sales-nav-export.csv
   ```
결과는 Obsidian `LinkedIn/Queue.md`와 담당자별 노트(3~6일 워밍업 체크리스트 + 300자 제한 검증된 연결 요청 + 1촌 DM + 팔로업)로 저장됩니다.

### C. 해외 B2B 엔드유저 직접 영업 & 해외 대리점·총판 발굴
해외 영업은 **최종 도입 기업 직접 영업(`--mode end_user`, 기본값)**과 **현지 대리점·총판 개척(`--mode distributor`)**을 선택해 실행합니다.

```sh
# 1) 해외 B2B 엔드유저 직접 영업 (미국·독일·일본 등 최종 고객사 발굴 + 현지 네이티브 초안)
python3 distributor_finder.py --mode end_user \
  --config setup.json --file ./overseas-targets.csv \
  --country US --country DE --country JP \
  --vault ~/Documents/Hermes-GTM

# 2) 해외 대리점·총판·수입상 발굴 (경쟁사 Where-to-Buy/Distributors 페이지 또는 전시회 참가사 CSV)
python3 distributor_finder.py --mode distributor \
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
python3 copy_guard.py sequence --company "예시기업" --title "데이터 엔지니어" --config setup.json

# 내가 직접 쓴 메일 초안 검수 (스팸어·과장/훈수 표현·미치환 변수·길이 체크)
python3 copy_guard.py lint --subject "짧은 확인" --file ./my-draft.txt
```

### 답장 11라벨 분류 · 긍정 회신율 · 수신거부 자동 차단
```sh
python3 reply_tracker.py \
  --input ./replies.csv --sent 300 --campaign "2026-Q2" \
  --apply-suppression --home ~/.hermes-outbound --vault ~/Documents/Hermes-GTM
```
- `관심 / 자료요청 / 담당자소개 / 질문 / 시기아님 / 부적합 / 항의 / 수신거부 / 부재중 / 바운스 / 기타`로 자동 분류합니다.
- `수신거부 · 바운스 · 항의`는 자동으로 `~/.hermes-outbound/do-not-contact.txt`에 등록되어 재발송 사고를 막습니다.
- 결과는 `GTM/Results.md`와 `GTM/LEARNINGS.md`에 누적됩니다.

### 미팅 전 1장 브리핑 · 미팅 후 팔로업 · 발신 도메인 헬스체크
```sh
# 미팅 전 1장 브리핑 (볼트 근거 + 회사 홈페이지 요약 + 핵심 질문 3개)
python3 meeting_and_health.py prep --company "알파데이터" --attendee "김팀장" \
  --company-url https://company.example.com --vault ~/Documents/Hermes-GTM

# 미팅 메모 -> 합의된 다음 단계 & 담백한 리캡 메일 초안
python3 meeting_and_health.py post --company "알파데이터" --attendee "김팀장" \
  --notes-file ./meeting-notes.txt --vault ~/Documents/Hermes-GTM

# 콜드메일 발송 전 도메인 SPF / DKIM / DMARC / MX 점검
python3 meeting_and_health.py health --domain example.com
```

---

## 6. 선택 효율화: TypeSafe AI Jev 연결하기

리드가 많아지거나 AI 초안 비용을 줄이고 싶을 때만 선택해서 켭니다.

1. `~/.hermes-outbound/.env` 파일에 아래 한 줄을 추가합니다:
   ```ini
   TYPESAFE_API_KEY=발급받은_키
   ```
   (`JEV_API_KEY` 이름도 동일하게 인식합니다.)
2. `setup.json`에서 `"jev_enabled": true`(초안 검수까지 원하면 `"jev_qa_drafts": true`)로 바꿉니다.
3. 연결 확인:
   ```sh
   python3 jev_client.py probe --home ~/.hermes-outbound
   ```
키가 없거나 네트워크 오류가 나면 자동으로 로컬 규칙 엔진으로 폴백하므로 작업이 멈추지 않습니다.

---

## 7. 자주 묻는 질문 (문제 해결)

- **일부 채용 사이트가 `blocked(403/429)`로 뜹니다.**
  - 클라우드 서버 IP나 과도한 요청은 사이트에서 차단할 수 있습니다. `jobs_partial_ok: true`가 켜져 있으면 성공한 보드 결과만 안전하게 유지합니다. 로그인/CAPTCHA 우회는 하지 않으며, 필요 시 CSV `file` 모드로 가져올 수 있습니다.
- **이미 수정한 Obsidian 노트가 덮어씌워질까 봐 걱정됩니다.**
  - `GTM/Accounts/`의 `status`와 `## 사람 메모`, `Review/` 노트는 사람 소유 영역으로 보호되어 재실행해도 덮어쓰지 않습니다.
- **설정을 잘못 건드렸거나 다시 확인하고 싶습니다.**
  - `python3 kit.py validate --config setup.json`으로 설정 오류를 바로 확인할 수 있고, `wizard.html` 왼쪽의 **"기존 setup.json 불러오기"** 버튼으로 불러와 고칠 수 있습니다.
