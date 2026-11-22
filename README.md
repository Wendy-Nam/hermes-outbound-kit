# Hermes Outbound Kit

**채용 공고 · 투자 뉴스 · 나라장터 · LinkedIn · 해외 B2B 타깃**에서 영업 기회를 자동으로 찾고,
내 영업 스타일에 맞춘 **담백한 초안과 Obsidian CRM 보드**까지 정리해 주는 오픈소스 B2B 아웃바운드 키트입니다.

> **핵심 원칙 4가지**
> 1. **자동 발송 없음** — 모든 메일·DM 초안은 내가 직접 확인하고 보냅니다.
> 2. **비밀값 분리** — 모든 API 키·토큰·비밀번호는 `setup.json`이 아니라 로컬 `$HERMES_HOME/.env`에만 저장합니다.
> 3. **런타임 독립성** — **OMH(oh-my-hermes) · OmniRoute에 의존하지 않고** 순정 Hermes 단독으로 동작합니다(별도로 설치해 사용 중이어도 충돌하지 않습니다).
> 4. **추가 패키지 설치 불필요** — 핵심 도구는 Python 3.11+ 기본 라이브러리만으로 바로 돌아갑니다.

---

## 3분 만에 시작하기 (가장 쉬운 순서)

### 방법 A. 브라우저 화면으로 클릭해서 시작 (비개발자 권장)
1. 이 폴더의 [`wizard.html`](wizard.html)을 브라우저(크롬·사파리 등)로 엽니다.
2. 내 영업 직군 카드(10종 중 선택)를 누르거나, **우리 회사 소개글 / 내가 평소 보낸 영업 메일**을 붙여넣어 자동 세팅합니다.
3. 맨 아래 **`setup.json 생성 및 다운로드`**를 눌러 이 폴더에 저장합니다.
4. 터미널에서 아래 한 줄로 바로 샘플 결과를 만들어 봅니다 (API 키·계정 없이 오프라인 실행 가능):
   ```sh
   python3 outbound.py setup --config setup.json --offline --no-launch
   ```
5. 생성된 `~/Documents/Hermes-GTM` 폴더를 **Obsidian**에서 열면 `Dashboard.md`와 `GTM/Pipeline.md`를 바로 볼 수 있습니다.

### 방법 B. 터미널 대화형으로 바로 시작
```sh
python3 outbound.py start --offline
```
Mac에서는 `시작하기.command`, Windows에서는 `시작하기.bat`을 더블클릭해도 시작됩니다.

### 방법 C. 코딩 AI(Claude Code / Cursor 등)에게 맡기기
이 폴더를 열고 아래 문장을 그대로 붙여넣으세요:
> `agent-skill/hermes-outbound-setup/SKILL.md`를 읽고 필요한 질문만 받아서 내 영업 직군에 맞게 설치해 줘. API 키나 토큰은 채팅에 묻지 마.

---

## 이 키트로 할 수 있는 일

모든 명령은 루트의 단일 진입점 **`python3 outbound.py <명령>`** 하나로 실행합니다.

| 내가 하고 싶은 일 | 명령어 | 설명 |
|---|---|---|
| **내 영업 직군에 맞게 세팅** | `wizard.html`, `outbound.py profile` | 10개 업종 프리셋(SaaS·HR·제조·커머스·물류·보안·핀테크·공공·해외 B2B 엔드유저·해외 대리점) |
| **브로셔·홈페이지로 자동 세팅** | `outbound.py profile bootstrap` | 자사 브로셔(`.pptx/.docx/.pdf/.md/.png/.jpg`) + 자사/경쟁사 URL(JS 렌더링 지원) 분석 → 초기 타깃팅 전략·DNC 자동 생성 |
| **내 메일 말투 학습** | `outbound.py profile style` | 내 발신메일함(`.mbox/.eml`/읽기 전용 IMAP)에서 인사말·분량·화법만 익명 추출(개인정보 미저장) |
| **국내 공고·투자·입찰 발굴** | `outbound.py run`, `outbound.py g2b` | 원티드·사람인·잡코리아(이미지 OCR)·점핏·ATS·Platum/VentureSquare + **나라장터 발주계획/사전규격/입찰공고 기준선 차분 감시 & 잡음 제외** |
| **LinkedIn 담당자 소싱·CRM** | `outbound.py linkedin`, `outbound.py crm` | ICP → Apify/CSV 소싱 → **초안/연락이력 분리** · **Obsidian Kanban 보드(`CRM Board.md`) 자동 동기화** · **무결성 감사(`vault audit`)** |
| **해외 B2B 엔드유저 / 대리점 개척** | `outbound.py overseas` | 해외 최종 도입 기업(`--mode end_user`) & 현지 대리점(`--mode distributor`) 발굴·4축 채점 + 영/일/독/한 네이티브 초안 |
| **경쟁사 역추적 · 데일리 브리핑** | `outbound.py intel`, `outbound.py briefing` | 경쟁사 사례에서 돈 쓴 문제 역추적 → 비슷한 타깃 큐 + **오늘 현황·미발송 초안·G2B·감사 데일리 브리핑** |
| **멀티터치 시퀀스 & 쉬운 문체 검수** | `outbound.py copy` | 1~4차 시퀀스 생성 + 콜드메일 스팸어 린트 + **영업 전략문서 쉬운 한국어 문체·표 열 감사(`--mode doc`)** |
| **답장 분류 & 수신거부 자동 차단** | `outbound.py replies` | 답장 11종 분류, 긍정 회신율 계산, 수신거부/바운스 자동 DNC 등록, `LEARNINGS.md` 누적 |
| **미팅 브리핑 · 도메인 헬스체크** | `outbound.py meeting`, `outbound.py health` | 미팅 전 1장 브리핑, 미팅 후 리캡 초안, 발신 도메인 `MX / SPF / DKIM / DMARC` 점검 |
| **외부 API 서비스 & Jev 점검 (선택)** | `outbound.py services`, `outbound.py jev` | Crawl4AI(무료)/Firecrawl(선택)·Apify·Webshare·TypeSafe AI Jev·Groq·Composio 점검 |

---

## 자주 쓰는 명령어 한눈에 보기

자세한 단계별 사용법과 예시는 **[실전 사용 매뉴얼 (한국어)](docs/MANUAL.md)**를 보세요.

```sh
# 1) 직군 프리셋 확인 · 초기화 · 샘플 초안 미리보기
python3 outbound.py profile presets
python3 outbound.py profile init --preset manufacturing-smartfactory --output setup.json --sync --force
python3 outbound.py profile preview --config setup.json

# 2) 브로셔(PPTX/PDF/이미지 포함) + 자사/경쟁사 홈페이지 자동 분석
python3 outbound.py profile bootstrap --company-url https://company.example.com --competitor-url https://competitor.example.com --brochure ./brochure.pptx --output setup.json --insights ./Targeting-Insights.md --sync --force

# 3) 내 발신메일함 문체 분석 (개인정보 자동 제거)
python3 outbound.py profile style --discover
python3 outbound.py profile style --mbox ~/Downloads/Sent.mbox --config setup.json --apply

# 4) 국내 채용·투자 실행 & 나라장터 발주계획·사전규격·입찰공고 기준선 차분 감시
python3 outbound.py run --config setup.json --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM
python3 outbound.py g2b --keywords "의료후송,의료지원,비상대피" --stages order_plan,prespec,bid_notice --initialize --vault ~/Documents/Hermes-GTM

# 5) LinkedIn ICP -> 소싱 -> CRM Kanban 동기화 & 볼트 무결성 감사
python3 outbound.py linkedin xray --config setup.json
python3 outbound.py linkedin run --config setup.json --contacts-file ./sales-nav.csv --vault ~/Documents/Hermes-GTM
python3 outbound.py crm knowledge --config setup.json --vault ~/Documents/Hermes-GTM
python3 outbound.py vault audit --vault ~/Documents/Hermes-GTM

# 6) 해외 B2B 엔드유저 직접 영업 / 해외 대리점 발굴 / 경쟁사 역추적
python3 outbound.py overseas --mode end_user --config setup.json --file ./targets.csv --country US --country DE --country JP --vault ~/Documents/Hermes-GTM
python3 outbound.py overseas --mode distributor --config setup.json --distributor-url https://competitor.example.com/distributors --country DE --vault ~/Documents/Hermes-GTM
python3 outbound.py intel --input ./competitor-signals.csv --competitor "GlobalCorp" --vault ~/Documents/Hermes-GTM

# 7) 쉬운 한국어 문체 감사 · 1~4차 시퀀스 · 답장 분석 · 데일리 브리핑 · 도메인 점검
python3 outbound.py copy lint --mode doc --file ~/Documents/Hermes-GTM/Knowledge/영업\ 포지셔닝.md
python3 outbound.py copy sequence --company "예시기업" --title "데이터 엔지니어" --config setup.json
python3 outbound.py replies --input ./replies.csv --sent 300 --apply-suppression --home ~/.hermes-outbound --vault ~/Documents/Hermes-GTM
python3 outbound.py briefing --vault ~/Documents/Hermes-GTM --text
python3 outbound.py health --domain example.com
```

> Windows에서는 `python3` 대신 `py -3`을 사용합니다.

---

## 프로젝트 구조 (깔끔하게 정리된 계층 구조)

```text
hermes-outbound-kit/
├── outbound.py             # 통합 CLI 진입점 (모든 기능 한 줄 실행)
├── wizard.html             # 브라우저 설정 마법사 (클릭만으로 setup.json 생성)
├── setup.example.json      # 샘플 설정 파일
├── 시작하기.command / .bat  # Mac / Windows 더블클릭 실행기
├── src/
│   ├── core/               # 설정·수집기·Crawl4AI/OCR(web_extract)·G2B감시·CRM보드/감사·볼트·워크플로
│   ├── profile/            # 10종 프리셋·브로셔/웹 분석·발신함 문체 분석
│   ├── pipelines/          # LinkedIn·해외 B2B/대리점·경쟁사 인텔·데일리 브리핑·카피 가드·답장·미팅·Jev
│   └── setup/              # 설치기·Hermes 엔진·예약 실행(--verify)·원격 SSH 배포
├── pack/                   # 25개 Hermes 영업 스킬 & 10종 직군 프리셋 JSON
├── scripts/                # 배포 번들 생성 · 오프라인 스모크 · 개인정보 감사
├── docs/                   # 사용자 한국어 가이드 (내부 참고·감사 문서는 docs/reference/)
├── samples/                # 오프라인 테스트용 샘플 데이터
└── tests/                  # 자동화 단위 테스트
```

---

## API 키 · 무료 JS 렌더링(Crawl4AI) · 이미지 공고 인식 안내

외부 서비스 키는 **모두 선택 사항**이며, 사용할 서비스의 키만 로컬 **`~/.hermes-outbound/.env`**(Windows는 `%LOCALAPPDATA%\hermes-outbound\.env`)에 넣습니다.

| 기능 / 서비스 | 권장 설정 (무료 우선) | 역할 |
|---|---|---|
| **JS/SPA 웹사이트 렌더링** | **1순위 무료 오픈소스 Crawl4AI** (`pip install crawl4ai && crawl4ai-setup` 또는 로컬 Docker `CRAWL4AI_BASE_URL=http://127.0.0.1:11235`) → 2순위 로컬 Playwright → 3순위 선택 `FIRECRAWL_API_KEY` | React/Next/SPA 페이지가 빈 HTML로 올 때 유료 API 없이 무료 로컬 렌더링으로 우선 추출 |
| **이미지 공고 / 스캔 브로셔 인식** | **1순위 무료 로컬 `tesseract`** (`kor+eng`) → 2순위 선택 `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | 사람인·잡코리아 이미지 공고(`<img>`)와 `.png/.jpg/.webp` 브로셔 텍스트 자동 추출 (미설치 시 내용 지어내기 없음) |
| **LinkedIn 회사·담당자 소싱** | `APIFY_TOKEN` (선택) | Apify 공식 Actor API 실행 (없으면 Sales Nav CSV / X-Ray 무료 모드 사용) |
| **나라장터(G2B) 실시간 감시** | `DATA_GO_KR_API_KEY` (무료) | 공공데이터포털 무료 인증키 (발주계획·사전규격·입찰공고 기준선 차분 감시) |
| **허용 소스 전용 프록시** | `WEBSHARE_API_KEY` (선택) | 허용된 공개 출처 전용 전송(로그인·CAPTCHA 우회 금지) |
| **고속 채점·초안 검수** | `TYPESAFE_API_KEY` (선택) | 대량 사전 필터링·채점·답장 분류 가속(없으면 로컬 규칙 자동 폴백) |
| **음성 인식 / OAuth 앱 연결** | `GROQ_API_KEY`, `COMPOSIO_CONSUMER_KEY` (선택) | 선택 STT 및 최소권한 외부 앱 연결 |

- **전용 홈 폴더**: Mac/Linux `~/.hermes-outbound`, Windows `%LOCALAPPDATA%\hermes-outbound` (기존 설정과 내가 수정한 노트는 덮어쓰지 않습니다)
- **포함되지 않는 기능**: 이메일/DM 자동 발송, 로그인·CAPTCHA 우회, 무단 개인정보 수집.

---

## 상세 문서 안내

- **[실전 사용 매뉴얼 (처음 쓰는 분 필독)](docs/MANUAL.md)**
- [사전 준비 체크리스트](docs/PREPARE.md) · [Obsidian 볼트 구조](docs/OBSIDIAN.md)
- [포함된 25개 영업 스킬 목록](docs/SKILLS.md) · [시나리오별 실행 상세](docs/WORKFLOWS.md)
- [서버 설치 안내](docs/SERVER.md) · [선택 서비스 연결](docs/SERVICES.md)
- 내부 검증·감사 참고 문서: [공개 전 개인정보 점검](docs/reference/PRIVACY-RELEASE.md) · [검증 범위 안내](docs/reference/VALIDATION.md)
