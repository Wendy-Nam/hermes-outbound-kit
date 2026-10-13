# 포함된 스킬과 출처

키트를 설치하면 `pack/skills/`의 스킬이 모두 사용자 Hermes home에 복사됩니다. 스킬 안의 스크립트는
Python 표준 라이브러리만 쓰므로 추가 설치가 필요 없습니다. 모든 스킬은 **공개 근거만 사용하고,
모르는 값은 미상으로 남기며, 초안까지만 만들고 발송하지 않는다**는 규칙을 따릅니다.

## 단계별 스킬

| 단계 | 스킬 | 스크립트 | 비고 |
|---|---|---|---|
| 타깃 정의 | `gtm-icp-brief` | — | ICP 필수·가점·제외 조건 |
| 계정 발굴 | `lead-prospecting` | `lead_scorer.py` | 도입사례 → 경쟁사·생태계 확장 → BANT → 제안 개요 |
| 계정 발굴 | `funding-signal-search` | `funding_search.py` | Platum 투자 기사(공개 WordPress API) |
| 채용 신호 | `wanted-search`, `kr-search`, `ats-search` | 각 1개 | 원티드·사람인·잡코리아·Greenhouse/Lever/Ashby |
| 채용 신호 | `hiring-signal-enrich` | `hiring_enrich.py` | 계정 후보별 원티드 공고 수·직무 |
| 채용 신호 | `sales-job-sourcing` | — | 키트 `workflow.py` 수집 흐름 안내 |
| 뉴스·공개 신호 | `naver-news-search` | — | 제3자 k-skill 공개 프록시 경유(아래 참고) |
| 뉴스·공개 신호 | `news-monitoring-briefing`, `buying-signals`, `korean-public-research`, `overseas-partner-research` | — | |
| 리서치 | `prospect-research`, `web-reader` | — | 사람·회사 공개 정보, 본문 추출(Jina Reader) |
| 우선순위 | `outbound-scoring` | `account_score.py`, `signals_to_accounts.py` | 적합도×긴급도(투자·채용·임원 발언·행사·경쟁사), 커버리지 미달이면 "리서치 필요" |
| 초안 | `evidence-to-outreach`, `signal-outreach-draft`, `linkedin-cold-messaging` | `signal_outreach.py` | 초안만, 사람 검토 후 직접 발송 |
| 문체 | `korean-humanizer` | — | 번역체·AI 상투어 교정 |
| 검수 | `gtm-list-qa`, `gtm-copy-qa` | — | |
| 추적 | `account-crm` | `account_crm.py` | 발굴→접촉→응답→미팅→제안→계약, 사람이 바꾼 상태·메모는 덮지 않음 |

## 사용자 설정 파일 (스킬 폴더 밖에 둡니다)

스킬 폴더 파일을 직접 고치면 키트를 다시 설치할 때 "기존 변경 보존"으로 멈춥니다. 개인 값은 Hermes home에 둡니다.

| 파일 | 용도 | 시작 방법 |
|---|---|---|
| `$HERMES_HOME/sales-profile.json` | `outbound-scoring` 채점 기준 | `skills/outbound-scoring/sales-profile.json` 복사 후 업종·기술스택 밴드 수정 |
| `$HERMES_HOME/sender-profile.json` | `signal-outreach-draft` 발신자 정보 | `skills/signal-outreach-draft/profile.example.json` 복사 후 작성 |
| `$HERMES_HOME/gtm/accounts.json` | `account-crm` 장부 | 처음 `--ingest` 때 자동 생성 |

이 파일들에는 연락처·영업 데이터가 들어가므로 공유하거나 커밋하지 않습니다.

## 외부 서비스로 나가는 데이터

- `web-reader`: 읽을 URL이 Jina Reader(`r.jina.ai`)로 전달됩니다. 토큰이 들어간 링크는 넣지 않습니다.
- `naver-news-search`: 검색어가 k-skill 프로젝트의 공개 프록시로 전달됩니다. 이 키트가 운영하지 않으므로
  가용성이 보장되지 않습니다. 고객 내부 정보나 개인 이름은 검색어로 쓰지 않습니다.
- 채용·투자 스크립트는 각 사이트의 공개 API·페이지만 조회합니다. 일부 사이트는 클라우드 서버 IP를
  차단합니다. 조회가 실패하면 "0건"이 아니라 실패로 보고합니다. 차단 우회는 하지 않습니다.

## 출처와 라이선스

| 스킬 | 출처 | 라이선스 | 변경 |
|---|---|---|---|
| `outbound-scoring`, `lead-prospecting` | 작성자 개인 Hermes 구성의 세일즈 스킬 | MIT (이 키트) | 개인 메타데이터 제거, 설정을 YAML → JSON(표준 라이브러리), 사용자 설정 경로 추가 |
| `prospect-research`, `linkedin-cold-messaging`, `news-monitoring-briefing` | 작성자 개인 Hermes 구성(Hermes Agent 기반 스킬) | MIT | 실제 인물 예시 익명화, 관련 스킬 링크 정리 |
| `korean-humanizer`, `naver-news-search` | k-skill 공개 스킬(작성자 구성 경유) | MIT, 영어 패턴은 blader/humanizer MIT (`references/humanizer-LICENSE`) | 경로·실제 회사 예시 정리, 제3자 프록시 고지 추가 |
| `funding-signal-search`, `hiring-signal-enrich`, `signal-outreach-draft`, `account-crm` | 작성자의 투자 기업 발굴 키트 | MIT, Copyright (c) 2026 Wendy Nam | 헤드헌팅 BD용을 GTM 계정 발굴용으로 재구성: 채점은 `outbound-scoring`으로 통합, 초안은 내 제품 소개로, CRM은 계정 파이프라인으로 |
| `wanted-search`, `kr-search`, `ats-search`, `web-reader` | `Wendy-Nam/hermes-job-hunt-for-korean` | MIT, Copyright (c) 2026 Wendy Nam | 구직자용 기본 필터(주니어만)를 영업용 전체 직급으로, 조회 실패를 0건과 구분 |

옮기지 않은 것: 개인 브랜딩 글쓰기 스킬, 개인 서버 전용 경로에 묶인 스킬, 일상·메신저·미디어 스킬,
메모리·볼트·프로필 데이터, 구직자용 이력서·자기소개서·면접 스킬(필요하면 `hermes-job-hunt-for-korean`을
별도로 설치합니다), 개인 커스텀 OMH 3.0 플러그인(키트는 공개 OMH 2.0.5를 설치합니다).
`competitor-news-monitor`, `grounded-citations`는 Hermes에 기본 포함되어 있어 따로 넣지 않았습니다.
