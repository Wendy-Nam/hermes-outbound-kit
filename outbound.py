#!/usr/bin/env python3
"""Hermes Outbound Kit — 통합 CLI 진입점.

사용 예시:
  python3 outbound.py start                        # 대화형 초기 시작 (오프라인은 --offline)
  python3 outbound.py setup --config setup.json    # 전체 설치 & 첫 실행 (--offline 가능)
  python3 outbound.py profile presets              # 직군 프리셋 / init / bootstrap / style / preview
  python3 outbound.py run --config setup.json ...  # 국내 채용·투자·나라장터·해외 수집 -> Obsidian 볼트
  python3 outbound.py linkedin xray|run ...        # LinkedIn ICP -> Apify/CSV 소싱 -> 워밍업·DM
  python3 outbound.py overseas ...                 # 해외 B2B 엔드유저(--mode end_user) & 대리점(--mode distributor)
  python3 outbound.py copy lint|sequence ...       # 스팸어·가독성 린터 & 1~4차 멀티터치 시퀀스
  python3 outbound.py replies ...                  # 답장 11라벨 분류 · 긍정 회신율 · 자동 DNC
  python3 outbound.py meeting prep|post ...        # 미팅 전 1장 브리핑 · 미팅 후 리캡
  python3 outbound.py crm sync|stage|knowledge|audit ... # Obsidian Kanban 보드 동기화 · 볼트 무결성 감사
  python3 outbound.py g2b --keywords ...           # 나라장터 발주계획·사전규격·입찰공고 기준선 차분 감시
  python3 outbound.py intel --input ... --vault ... # 경쟁사 역추적 마켓 인텔리전스 원장 & 비슷한 타깃 큐
  python3 outbound.py briefing --vault ...         # 오늘 현황 · 미발송 초안 · G2B · 감사 데일리 브리핑
  python3 outbound.py env status|set ...           # .env API 키 안전 입력 & 무료 Crawl4AI/tesseract 진단
  python3 outbound.py services status ...          # 외부 API 키 서비스(Crawl4AI/Firecrawl/Apify/Webshare/Jev 등) 점검
  python3 outbound.py jev status|probe             # TypeSafe AI Jev 연결 점검
"""
from __future__ import annotations

import importlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src  # noqa: E402,F401  (registers src/* layers on sys.path)

COMMANDS: dict[str, tuple[str, list[str], str]] = {
    "start": ("start", [], "대화형 초기 설정 및 실행 (--offline 지원)"),
    "setup": ("installer", ["setup"], "전체 설치·샘플·볼트 자동 실행 (--offline 지원)"),
    "installer": ("installer", [], "단계별 설치 실행기 (plan/setup/resume/run/status/diagnose)"),
    "env": ("env_helper", [], ".env API 키 숨김 저장(set/unset) & 무료 Crawl4AI·tesseract 도구 진단(status)"),
    "kit": ("kit", [], "설정 검증·스킬 설치·모델·채널·진단 (validate/install/doctor/chat/gateway)"),
    "validate": ("kit", ["validate"], "setup.json 유효성 검사"),
    "install": ("kit", ["install"], "$HERMES_HOME에 26개 스킬·11종 프리셋 설치"),
    "doctor": ("kit", ["doctor"], "설치 환경 진단"),
    "profile": ("profile", [], "직군 프리셋·커스텀·브로셔 분석(bootstrap)·발신함 분석(style)·DNC·ATS"),
    "run": ("workflow", ["run"], "국내 채용·투자·나라장터·해외 파이프라인 실행 -> Obsidian 볼트"),
    "workflow": ("workflow", [], "워크플로 전체 명령 (run / draft-import)"),
    "sources": ("sources", [], "개별 공고·투자·조달·해외 소스 수집기"),
    "g2b": ("g2b_monitor", [], "나라장터 발주계획·사전규격·입찰공고 기준선 차분 감시 & 잡음 제외"),
    "lens": ("public_data_lens", [], "공공데이터 렌즈(Public Data Lens) 무료無인증 MCP 연결 & 9.6만 데이터셋·활용계획(plan-data) 탐색"),
    "linkedin": ("linkedin_outbound", [], "LinkedIn ICP -> Apify 회사·담당자 소싱 -> 워밍업·300자 DM"),
    "overseas": ("distributor_finder", [], "해외 B2B 엔드유저(--mode end_user) & 대리점(--mode distributor) 발굴"),
    "intel": ("market_intel", [], "경쟁사 역추적 마켓 인텔리전스 원장 & 비슷한 타깃 발굴 큐"),
    "crm": ("crm_board", [], "Obsidian Kanban 보드(CRM Board.md) 동기화 · 단계변경 · 전략문서 · 볼트 무결성 감사"),
    "briefing": ("daily_briefing", [], "오늘 리드·미발송 초안·G2B·경쟁사 신호·볼트 감사 데일리 브리핑"),
    "copy": ("copy_guard", [], "스팸어·쉬운 한국어 문서 문체 린터(lint --mode doc) & 1~4차 멀티터치 시퀀스"),
    "draft": ("_cold_outreach_draft", [], "범용 콜드메일·DM 일괄 초안 생성(generate) & 공개 연락 창구 수집(contacts)"),
    "review": ("review_panel", [], "개인화 초안·근거 원문 링크 교차검증 단일 HTML 패널 생성"),
    "replies": ("reply_tracker", [], "답장 11라벨 분류 · 긍정 회신율 · 자동 DNC 차단 · LEARNINGS 누적"),
    "meeting": ("meeting_and_health", [], "미팅 전 1장 브리핑(prep) · 미팅 후 리캡/Plaud 녹음 전사(post --audio-file)"),
    "transcribe": ("audio_transcribe", [], "Plaud·미팅 녹음(.mp3/.m4a/.wav) 무료 Groq Whisper 한국어 전사"),
    "health": ("meeting_and_health", ["health"], "발신 도메인 MX / SPF / DKIM / DMARC 헬스체크"),
    "jev": ("jev_client", [], "TypeSafe AI Jev 고속 채점·검수 연결 확인 (status/probe)"),
    "services": ("services", [], "선택 외부 서비스(Firecrawl/Apify/Webshare/Jev/Groq/Composio) 상태 점검"),
    "vault": ("vault_flow", [], "Obsidian 볼트 초기화·동기화·검토 상태 관리"),
    "sync": ("vault_sync", [], "원격 서버 볼트 Markdown 읽기 전용 SSH 동기화 (plan/pull/status)"),
    "server": ("server_access", [], "Linux 원격 서버 SSH 접속·배포 도우미"),
    "operations": ("operations", [], "정기 예약 실행(cron/launchd/Task Scheduler) 관리 및 즉시 검증"),
    "docs": ("docs_support", [], "공식 Hermes 문서 버전·도움말 조회 (version/sync/query/help)"),
    "bot": ("test_bot", [], "소유자 전용 Telegram 봇 연결 점검 (plan/configure/check)"),
}


def _print_help() -> None:
    print("Hermes Outbound Kit — 통합 명령어 도구\n")
    print("사용법: python3 outbound.py <명령> [옵션...]\n")
    print("주요 명령:")
    for cmd, (_mod, _prefix, desc) in COMMANDS.items():
        print(f"  {cmd:<12} {desc}")
    print("\n각 명령의 세부 옵션은 `python3 outbound.py <명령> --help`로 확인하세요.")
    print("자세한 한국어 사용법은 docs/MANUAL.md를 참고하세요.")


def _run_cold_outreach_draft(rest: list[str]) -> int:
    import importlib.util
    scripts_dir = ROOT / "pack" / "skills" / "cold-outreach-draft" / "scripts"
    if not rest or rest[0] in ("-h", "--help", "help"):
        print("사용법: python3 outbound.py draft <generate|contacts> [옵션...]\n")
        print("  generate   프로필 JSON + 리드 CSV -> 콜드메일·DM 초안 생성 (+ --copy-guard / --use-jev / --html)")
        print("  contacts   리드 홈페이지 공개 연락 창구 수집 (이메일 자동 수집 금지, SSRF/TLS 안전)")
        return 0
    sub, sub_rest = rest[0], rest[1:]
    script_map = {"generate": scripts_dir / "gen_drafts.py", "contacts": scripts_dir / "collect_contacts.py"}
    target = script_map.get(sub)
    if target is None or not target.is_file():
        print(f"알 수 없는 draft 하위 명령입니다: {sub} (generate 또는 contacts 사용)", file=sys.stderr)
        return 2
    spec = importlib.util.spec_from_file_location(f"hermes_cold_draft_{sub}", target)
    if spec is None or spec.loader is None:
        return 1
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return int(mod.main(sub_rest) or 0)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        _print_help()
        return 0
    cmd, rest = args[0], args[1:]
    if cmd == "smoke":
        sys.path.insert(0, str(ROOT / "scripts"))
        mod = importlib.import_module("local_smoke")
        return int(mod.main(rest) or 0)
    if cmd == "audit":
        sys.path.insert(0, str(ROOT / "scripts"))
        mod = importlib.import_module("privacy_audit")
        return int(mod.main(rest) or 0)
    if cmd == "bundle":
        import runpy
        runpy.run_path(str(ROOT / "scripts" / "build_bundle.py"), run_name="__main__")
        return 0
    if cmd == "draft":
        return _run_cold_outreach_draft(rest)

    if cmd == "vault" and rest and rest[0] == "audit":
        mod = importlib.import_module("crm_board")
        return int(mod.main(["audit", *rest[1:]]) or 0)

    entry = COMMANDS.get(cmd)
    if not entry:
        print(f"알 수 없는 명령입니다: {cmd}\n", file=sys.stderr)
        _print_help()
        return 2
    mod_name, prefix, _desc = entry
    mod = importlib.import_module(mod_name)
    if hasattr(mod, "main"):
        import inspect
        forwarded = prefix + rest
        sig = inspect.signature(mod.main)
        if len(sig.parameters) == 0:
            prev_argv = sys.argv
            sys.argv = [f"outbound.py {cmd}", *forwarded]
            try:
                rc = mod.main()
            finally:
                sys.argv = prev_argv
        else:
            rc = mod.main(forwarded)
        return int(rc) if isinstance(rc, int) else 0
    print(f"모듈 {mod_name}에 main()이 없습니다.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
