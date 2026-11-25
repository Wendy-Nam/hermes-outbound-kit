# Hermes Outbound Kit — Agent Guardrails (`AGENTS.md`)

이 저장소를 사용하는 모든 AI 에이전트(Hermes, Claude Code, Cursor 등)는 아웃바운드 리서치·타깃팅·초안 작성 전에 아래 5가지 하드 규칙을 반드시 지킨다.

## 1. 근거 URL 없는 가짜 타깃 금지
- 머릿속 기억이나 검색 요약만으로 타깃 기업·기관 10곳을 꾸며내지 않는다.
- 모든 리드는 `python3 outbound.py run`, `outbound.py g2b`, `outbound.py linkedin`, 또는 공개 웹 검색에서 확인한 **실제 원문 URL(`evidence_url`)**과 함께 제시한다.
- URL이 없는 후보는 초안 생성 대상에서 제외한다.

## 2. 한국어 콜드메일·DM 작성 전 필독 규칙
- 초안을 한 줄이라도 쓰기 전에 반드시 [`pack/skills/cold-outreach-draft/references/writing-rules.md`](pack/skills/cold-outreach-draft/references/writing-rules.md)를 읽는다.
- 금지 표현(`귀사`, `귀 기관`, `당사`, `저희`, `혁신`, `가능하실지요?`, `[공고/교육 프로그램명]` 같은 미치환 자리표시, 훈수·단정, 3줄짜리 뭉친 문단)을 쓰지 않는다.
- 대량 초안이나 교차검증 패널이 필요하면 직접 텍스트를 지어내지 말고 `python3 outbound.py draft generate --copy-guard --html <경로>`로 생성한다.

## 3. 발송 전 자동 검수 필수
- 사용자에게 초안을 보여 주기 전에 `python3 outbound.py copy lint --subject "..." --text "..."` (또는 `--copy-guard`)로 스팸어·높임 주어·자리표시·DM 300자 제한을 통과시킨다.
- 윤문 시 [`pack/skills/korean-humanizer/SKILL.md`](pack/skills/korean-humanizer/SKILL.md)의 **아웃바운드·사용자 말투 보존 모드**를 따른다.

## 4. 이력 과장 및 비공식 행사 오해 금지
- 수신자·공고 주제에 신빙성 있는 공식 경력·실무 사실만 선택해 쓴다(Proof-to-Buyer Fit).
- 커뮤니티 세미나나 특정 기업 오피스를 대관해 열린 비공식 행사를 해당 기업 공식 출강·파트너처럼 오해받게 쓰지 않는다.

## 5. 자동 발송 · 비밀값 유출 · 무단 수집 금지
- 이메일·DM 자동 발송은 금지한다. 모든 결과는 사람이 교차검증 HTML 패널 또는 Obsidian 볼트에서 검토 후 직접 발송한다.
- API 키·토큰은 `setup.json`이나 채팅에 넣지 않고 로컬 `$HERMES_HOME/.env`에만 저장한다.
- 이메일 주소 프로그램 자동 수집(정보통신망법 제50조의2) 및 로그인·CAPTCHA 우회를 금지한다.
