# Hermes Outbound Kit

**채용 공고 · 투자 뉴스 · 나라장터 · LinkedIn · 해외 B2B 타깃**에서 영업 기회를 자동으로 찾고,
내 영업 스타일에 맞춘 **담백한 초안과 Obsidian CRM 보드**까지 정리해 주는 오픈소스 B2B 아웃바운드 키트입니다.

> **핵심 원칙 3가지**
> 1. **자동 발송 없음** — 모든 메일·DM 초안은 내가 직접 확인하고 보냅니다.
> 2. **비밀값 분리** — API 키·토큰·비밀번호는 설정 파일(`setup.json`)에 절대 저장하지 않습니다.
> 3. **추가 패키지 설치 불필요** — 핵심 도구는 Python 3.11+ 기본 라이브러리만으로 바로 돌아갑니다.

---

## 3분 만에 시작하기 (가장 쉬운 순서)

### 방법 A. 브라우저 화면으로 클릭해서 시작 (비개발자 권장)
1. 이 폴더의 [`wizard.html`](wizard.html)을 브라우저(크롬·사파리 등)로 엽니다.
2. 내 영업 직군 카드(10종 중 선택)를 누르거나, **우리 회사 소개글 / 내가 평소 보낸 영업 메일**을 붙여넣어 자동 세팅합니다.
3. 맨 아래 **`setup.json 생성 및 다운로드`**를 눌러 이 폴더에 저장합니다.
4. 터미널에서 아래 한 줄로 바로 샘플 결과를 만들어 봅니다 (API 키·계정 없이 오프라인 실행 가능):
   ```sh
   python3 installer.py setup --config setup.json --offline --no-launch
   ```
5. 생성된 `~/Documents/Hermes-GTM` 폴더를 **Obsidian**에서 열면 `Dashboard.md`와 `GTM/Pipeline.md`를 바로 볼 수 있습니다.

### 방법 B. 터미널 대화형으로 바로 시작
```sh
python3 start.py --offline
```
Mac에서는 `시작하기.command`, Windows에서는 `시작하기.bat`을 더블클릭해도 시작됩니다.

### 방법 C. 코딩 AI(Claude Code / Cursor 등)에게 맡기기
이 폴더를 열고 아래 문장을 그대로 붙여넣으세요:
> `agent-skill/hermes-outbound-setup/SKILL.md`를 읽고 필요한 질문만 받아서 내 영업 직군에 맞게 설치해 줘. API 키나 토큰은 채팅에 묻지 마.

---

## 이 키트로 할 수 있는 일

| 내가 하고 싶은 일 | 쓰는 도구 | 설명 |
|---|---|---|
| **내 영업 직군에 맞게 세팅** | `wizard.html`, `profile.py` | 10개 업종 프리셋(SaaS·HR·제조·커머스·물류·보안·핀테크·공공·해외 B2B 엔드유저·해외 대리점) |
| **브로셔·홈페이지로 자동 세팅** | `profile.py bootstrap` | 자사 브로셔(`.pptx/.docx/.pdf/.md`) + 자사/경쟁사 URL 분석 → 초기 타깃팅 전략·경쟁사 DNC 자동 생성 |
| **내 메일 말투 학습** | `profile.py style` | 내 발신메일함(`.mbox/.eml`/읽기 전용 IMAP)에서 인사말·분량·화법만 익명 추출(개인정보 미저장) |
| **국내 공고·투자·입찰 발굴** | `workflow.py` | 원티드(상세 JD)·사람인·잡코리아·점핏·ATS(Greenhouse/Lever/Ashby/Greeting)·Platum/VentureSquare·나라장터(G2B) |
| **LinkedIn 담당자 소싱·DM** | `linkedin_outbound.py` | ICP 정의 → Boolean X-Ray & Apify 공식 API로 회사/담당자 소싱 → 워밍업 플랜 + 300자 연결요청·DM |
| **해외 B2B 엔드유저 / 대리점 개척** | `distributor_finder.py` | 해외 최종 도입 기업(`--mode end_user`) & 현지 대리점(`--mode distributor`) 발굴·4축 채점 + 영/일/독/한 네이티브 초안 |
| **멀티터치 시퀀스 & 스팸 검수** | `copy_guard.py` | 1~4차 팔로업 시퀀스 생성 + 스팸 금지어·상투어·분량·미치환 변수 자동 점검 |
| **답장 분류 & 수신거부 자동 차단** | `reply_tracker.py` | 답장 11종 분류, 긍정 회신율 계산, 수신거부/바운스 자동 DNC 등록, `LEARNINGS.md` 누적 |
| **미팅 브리핑 · 도메인 헬스체크** | `meeting_and_health.py` | 미팅 전 1장 브리핑, 미팅 후 리캡 초안, 발신 도메인 `MX / SPF / DKIM / DMARC` 점검 |
| **고속 채점·검수 효율화 (선택)** | `jev_client.py` | `TYPESAFE_API_KEY`(또는 `JEV_API_KEY`)가 있으면 대량 사전 필터·채점·답장 분류 가속(없으면 로컬 규칙 자동 사용) |

---

## 자주 쓰는 명령어 한눈에 보기

자세한 단계별 사용법과 예시는 **[실전 사용 매뉴얼 (한국어)](docs/MANUAL.md)**를 보세요.

```sh
# 1) 직군 프리셋 확인 · 초기화 · 샘플 초안 미리보기
python3 profile.py presets
python3 profile.py init --preset manufacturing-smartfactory --output setup.json --sync --force
python3 profile.py preview --config setup.json

# 2) 브로셔 + 자사/경쟁사 홈페이지 자동 분석
python3 profile.py bootstrap --company-url https://company.example.com --competitor-url https://competitor.example.com --brochure ./brochure.pptx --output setup.json --insights ./Targeting-Insights.md --sync --force

# 3) 내 발신메일함 문체 분석 (개인정보 자동 제거)
python3 profile.py style --discover
python3 profile.py style --mbox ~/Downloads/Sent.mbox --config setup.json --apply

# 4) 국내 채용·투자·나라장터 실행 -> Obsidian 볼트 생성
python3 workflow.py run --config setup.json --home ~/.hermes-outbound --output ./output --vault ~/Documents/Hermes-GTM

# 5) LinkedIn ICP -> Apify 회사·담당자 소싱 (또는 Sales Nav CSV)
python3 linkedin_outbound.py xray --config setup.json
python3 linkedin_outbound.py run --config setup.json --contacts-file ./sales-nav.csv --vault ~/Documents/Hermes-GTM

# 6) 해외 B2B 엔드유저 직접 영업 / 해외 대리점 발굴
python3 distributor_finder.py --mode end_user --config setup.json --file ./targets.csv --country US --country DE --country JP --vault ~/Documents/Hermes-GTM
python3 distributor_finder.py --mode distributor --config setup.json --distributor-url https://competitor.example.com/distributors --country DE --vault ~/Documents/Hermes-GTM

# 7) 1~4차 시퀀스 · 답장 분석 · 미팅 브리핑 · 발신 도메인 점검
python3 copy_guard.py sequence --company "예시기업" --title "데이터 엔지니어" --config setup.json
python3 reply_tracker.py --input ./replies.csv --sent 300 --apply-suppression --home ~/.hermes-outbound --vault ~/Documents/Hermes-GTM
python3 meeting_and_health.py prep --company "예시기업" --vault ~/Documents/Hermes-GTM
python3 meeting_and_health.py health --domain example.com
```

> Windows에서는 `python3` 대신 `py -3`을 사용합니다.

---

## 설치 위치 및 안전한 파일 관리

- **전용 홈 폴더**: Mac/Linux `~/.hermes-outbound`, Windows `%LOCALAPPDATA%\hermes-outbound` (설치 시 기존 설정과 내가 수정한 노트는 덮어쓰지 않습니다)
- **비밀값 저장 위치**: API 키(`TYPESAFE_API_KEY`, `APIFY_TOKEN`, `DATA_GO_KR_API_KEY` 등)와 봇 토큰은 로컬 `$HERMES_HOME/.env`에만 저장합니다.
- **포함되지 않는 기능**: 이메일/DM 자동 발송, 로그인·CAPTCHA 우회, 무단 개인정보 수집.

---

## 상세 문서 안내

- **[실전 사용 매뉴얼 (처음 쓰는 분 필독)](docs/MANUAL.md)**
- [사전 준비 체크리스트](docs/PREPARE.md) · [Obsidian 볼트 구조](docs/OBSIDIAN.md)
- [포함된 25개 영업 스킬 목록](docs/SKILLS.md) · [시나리오별 실행 상세](docs/WORKFLOWS.md)
- [서버 설치 안내](docs/SERVER.md) · [선택 서비스 연결](docs/SERVICES.md) · [공개 전 개인정보 점검](docs/PRIVACY-RELEASE.md)
- [검증 범위 안내](VALIDATION.md)
