# 선택 외부 서비스 & API 키 연결 안내

모든 외부 서비스는 **선택 사항**입니다. 유료 API 키 없이도 기본 수집·채점·초안·Obsidian 볼트·무료 로컬 도구(Crawl4AI, tesseract)로 충분히 동작합니다.

## 1. 가장 쉬운 API 키 관리 (`python3 outbound.py env`)

숨김 파일(`.env`)을 직접 열 필요 없이 터미널에서 안전하게 키를 등록하고 무료 도구 설치 상태를 확인할 수 있습니다.

```sh
# 현재 설정된 키 상태(값은 비공개) + 무료 Crawl4AI · Playwright · tesseract 설치 진단
python3 outbound.py env status --home ~/.hermes-outbound

# 원하는 키만 숨김 입력으로 ~/.hermes-outbound/.env (0600 권한)에 안전 저장
python3 outbound.py env set --key DATA_GO_KR_API_KEY --home ~/.hermes-outbound
python3 outbound.py env set --key GROQ_API_KEY --home ~/.hermes-outbound
python3 outbound.py env set --key APIFY_TOKEN --home ~/.hermes-outbound

# 키 삭제
python3 outbound.py env unset --key APIFY_TOKEN --home ~/.hermes-outbound
```

## 2. 지원하는 외부 서비스 & 무료 대안

| 서비스 / 도구 | 환경변수 (`.env`) | 비용 | 용도 |
|---|---|---|---|
| **공공데이터 렌즈 (Public Data Lens)** | 무인증 (`X-Datanav-No-Log: 1` 자동 전송) | 무료 오픈소스 | 공공데이터포털 9.6만 개 목록·컬럼 탐색 및 활용 계획(`outbound.py lens plan-data/search/columns`) |
| **Crawl4AI (권장 1순위)** | `CRAWL4AI_BASE_URL` (또는 로컬 `crwl` 설치) | 무료 오픈소스 | React/Next/SPA 웹사이트 JS 렌더링 |
| **tesseract OCR (권장 1순위)** | 로컬 바이너리 설치 | 무료 오픈소스 | 이미지 채용공고·스캔 브로셔 텍스트 추출 |
| **나라장터(G2B)** | `DATA_GO_KR_API_KEY` | 무료 (공공데이터포털) | 발주계획·사전규격·입찰공고 3단계 차분 감시 |
| **Groq Whisper (Plaud/미팅 전사)** | `GROQ_API_KEY` | 무료 티어 제공 | Plaud·미팅 녹음(`.mp3/.m4a/.wav`) 한국어 전사 → 미팅 리캡 (`outbound.py transcribe` / `meeting post --audio-file`) |
| **Apify** | `APIFY_TOKEN` | 선택 유료 | LinkedIn 회사·담당자 Actor 소싱 (없으면 Sales Nav CSV / X-Ray 무료 모드) |
| **TypeSafe AI Jev** | `TYPESAFE_API_KEY` | 선택 유료 | 대량 사전 필터링·채점·초안 검수 고속화 (없으면 로컬 규칙 자동 폴백) |
| **Firecrawl** | `FIRECRAWL_API_KEY` | 선택 유료 | 로컬 Crawl4AI/Playwright 없이 SPA 렌더링이 필요할 때 |
| **OpenAI / OpenRouter Vision** | `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | 선택 유료 | 로컬 tesseract가 없을 때 이미지 OCR 폴백 |
| **Webshare** | `WEBSHARE_API_KEY` | 선택 유료 | 허용된 단일 공개 출처 전용 프록시 (로그인·CAPTCHA 우회 금지) |
| **Composio** | `COMPOSIO_CONSUMER_KEY` | 선택 유료 | 최소권한 OAuth 외부 앱 연결(MCP) |

## 3. 서비스별 인증 프로브 (`python3 outbound.py services`)

`setup.json`의 `services` 목록에 선택한 서비스에 대해 읽기 전용 인증 확인을 실행할 수 있습니다.

```sh
python3 outbound.py services plan --config setup.json --home ~/.hermes-outbound
python3 outbound.py services status --config setup.json --home ~/.hermes-outbound
python3 outbound.py services connect --config setup.json --home ~/.hermes-outbound
python3 outbound.py services check --config setup.json --home ~/.hermes-outbound
```

- 모든 키는 `setup.json`, `wizard.html`, Obsidian 볼트, 배포 ZIP에 절대 저장하지 않습니다.
- 인증 통과(`auth_valid: true`)는 키 형식과 계정 확인을 뜻하며, 자동 발송이나 유료 Actor 자동 실행을 허용하지 않습니다.
