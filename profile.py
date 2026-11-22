#!/usr/bin/env python3
"""Unified sales profile & preset customization CLI for Hermes Outbound Kit.

Helps sales reps across diverse industries customize their outbound kit in
seconds—either from a role/industry preset or interactively—and syncs one
single source of truth (`setup.json`) into `$HERMES_HOME` (`outbound-profile.json`,
`sales-profile.json`, `sender-profile.json`, `do-not-contact.txt`, `ats-targets.json`).

Usage:
    python3 profile.py presets
    python3 profile.py init --preset manufacturing-smartfactory --output setup.json
    python3 profile.py customize --config setup.json --home ~/.hermes-outbound
    python3 profile.py sync --config setup.json --home ~/.hermes-outbound [--force]
    python3 profile.py preview --config setup.json
    python3 profile.py dnc --home ~/.hermes-outbound --add "경쟁사A" --add "기존고객B"
    python3 profile.py ats --home ~/.hermes-outbound --add greenhouse:myboard:"회사명"
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

import kit
import paths
import profile_presets
import sources
import vault_flow
import workflow


ROOT = Path(__file__).resolve().parent


def _atomic_write(path: Path, text: str, *, private: bool = True) -> None:
    path = path.expanduser().absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError(f"심볼릭 링크 경로에는 쓰지 않습니다: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".profile-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if private and os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_or_preserve(path: Path, text: str, *, force: bool = False, private: bool = True) -> str:
    if path.exists() and not force:
        if path.read_text(encoding="utf-8") == text:
            return "unchanged"
        return "preserved_existing"
    _atomic_write(path, text, private=private)
    return "updated" if path.exists() else "created"


def sync_profile_to_home(config: dict[str, Any], home: str | Path, *, force: bool = False) -> dict[str, str]:
    """Compile and sync setup.json into $HERMES_HOME runtime profile files."""
    validated = kit.validate(config)
    home_path = Path(home).expanduser().absolute()
    if any(p.is_symlink() for p in (home_path, *home_path.parents)):
        raise ValueError("설치 홈 경로에 심볼릭 링크가 있습니다.")
    home_path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(home_path, 0o700)

    results: dict[str, str] = {}

    # 1. outbound-profile.json
    results["outbound-profile.json"] = _write_or_preserve(
        home_path / "outbound-profile.json",
        json.dumps(validated, ensure_ascii=False, indent=2) + "\n",
        force=force,
    )

    # 2. sales-profile.json (compiled Fit x Urgency rules)
    compiled = profile_presets.compile_sales_profile(validated, home_path)
    results["sales-profile.json"] = _write_or_preserve(
        home_path / "sales-profile.json",
        json.dumps(compiled, ensure_ascii=False, indent=2) + "\n",
        force=force,
    )

    # 3. sender-profile.json
    sender = {
        "name": validated.get("sender_name") or "",
        "company": validated.get("sender_company") or "",
        "role": validated.get("sender_role") or "",
        "contact": validated.get("sender_contact") or "",
        "cta": validated.get("sender_cta") or "",
        "tone": validated.get("outreach_tone") or "consultative",
        "channel": validated.get("outreach_channel") or "email",
        "value_proposition": validated.get("value_proposition") or "",
        "proof_points": validated.get("proof_points") or "",
    }
    if any(sender[k] for k in ("name", "company", "contact", "cta", "value_proposition")):
        results["sender-profile.json"] = _write_or_preserve(
            home_path / "sender-profile.json",
            json.dumps(sender, ensure_ascii=False, indent=2) + "\n",
            force=force,
        )

    # 4. do-not-contact.txt (additive merge if existing)
    dnc_items = [x.strip() for x in (validated.get("do_not_contact") or []) if isinstance(x, str) and x.strip()]
    dnc_path = home_path / "do-not-contact.txt"
    if dnc_items:
        existing_lines: list[str] = []
        if dnc_path.is_file() and not force:
            existing_lines = [
                line.strip() for line in dnc_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        merged = list(dict.fromkeys([*existing_lines, *dnc_items]))
        text = "# 연락 금지(Do-Not-Contact) 회사 목록 — 한 줄에 한 회사\n" + "\n".join(merged) + "\n"
        _atomic_write(dnc_path, text, private=True)
        results["do-not-contact.txt"] = f"synced ({len(merged)} companies)"

    # 5. ats-targets.json (create if missing)
    ats_path = home_path / "ats-targets.json"
    default_ats = ROOT / "pack" / "skills" / "ats-search" / "data" / "ats-targets.json"
    if not ats_path.exists() and default_ats.is_file():
        _atomic_write(ats_path, default_ats.read_text(encoding="utf-8"), private=True)
        results["ats-targets.json"] = "seeded"

    return results


def preview_profile(config: dict[str, Any], home: str | Path | None = None) -> dict[str, Any]:
    """Run an offline preview showing how sample accounts score and draft with this profile."""
    validated = kit.validate(config)
    now = sources.utc_now()
    sample_records = [
        {
            "schema_version": sources.SCHEMA_VERSION,
            "record_type": "job_posting",
            "source": "preview-sample",
            "source_id": "preview-job-1",
            "company": "예시성장기업",
            "company_candidate": "예시성장기업",
            "company_confidence": "provided",
            "title": (profile_presets.split_terms(validated.get("job_keywords") or validated.get("jobs_query") or "영업 매니저")[0] + " 채용"),
            "description": f"{validated.get('customer', '')} 관련 {validated.get('keywords', '')} 업무 담당",
            "url": "https://example.com/jobs/preview-1",
            "published_at": now,
            "stack": sources.extract_tech_stack(f"{validated.get('keywords', '')} {validated.get('job_keywords', '')}"),
            "location": (profile_presets.split_terms(validated.get("region") or "서울")[0]),
            "evidence": sources.evidence("preview-sample", "preview-job-1", "https://example.com/jobs/preview-1", now, {"id": 1}),
        },
        {
            "schema_version": sources.SCHEMA_VERSION,
            "record_type": "funding_signal",
            "source": "preview-sample",
            "source_id": "preview-funding-2",
            "company": "예시벤처스랩",
            "company_candidate": "예시벤처스랩",
            "company_confidence": "provided",
            "title": f"예시벤처스랩, 시리즈 B 120억 투자 유치 ({validated.get('keywords', '').split(',')[0].strip() or '사업 확장'})",
            "description": validated.get("customer", ""),
            "url": "https://example.com/funding/preview-2",
            "published_at": now,
            "round_candidate": "시리즈 B",
            "amount_candidate": "120억",
            "sector_candidate": (profile_presets.split_terms(validated.get("keywords") or "B2B")[0]),
            "stack": sources.extract_tech_stack(validated.get("keywords", "")),
            "location": "서울",
            "evidence": sources.evidence("preview-sample", "preview-funding-2", "https://example.com/funding/preview-2", now, {"id": 2}),
        },
    ]
    scores = workflow.score_records(sample_records, validated, home=home)
    home_path = Path(home).expanduser().absolute() if home else (ROOT / ".nonexistent-home")
    draft_profile = workflow._build_draft_profile(validated, home_path)
    previews = []
    for rec in sample_records:
        draft_text = vault_flow._template_draft(
            rec, validated["product"], validated["customer"],
            validated.get("draft_language", "ko"), profile=draft_profile,
        )
        sc = scores[rec["source_id"]]
        previews.append({
            "company": rec["company"],
            "signal": rec["title"],
            "action": sc["action"],
            "fit_score": sc["fit_score"],
            "urgency_score": sc["urgency_score"],
            "rationale": sc["rationale"],
            "draft": draft_text,
        })
    return {
        "preset": validated.get("sales_preset") or "custom",
        "tone": draft_profile.get("outreach_tone") or "consultative",
        "channel": draft_profile.get("outreach_channel") or "email",
        "previews": previews,
    }


def _prompt(label: str, current: str = "") -> str:
    hint = f" [{current}]" if current else ""
    val = input(f"{label}{hint}: ").strip()
    return val if val else current


def interactive_customize(config_path: Path, home: Path) -> dict[str, Any]:
    """Guided interactive profile customizer for any sales rep."""
    if config_path.is_file():
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        print(f"기존 설정을 불러왔습니다: {config_path}")
    else:
        presets = profile_presets.list_presets(home)
        print("\n=== 직군/업종 프리셋을 선택하세요 ===")
        for idx, p in enumerate(presets, 1):
            print(f"  {idx}. [{p['id']}] {p['name']} — {p['tagline']}")
        print("  0. [custom] 직접 입력")
        raw = input("번호 또는 프리셋 ID [1]: ").strip() or "1"
        if raw == "0" or raw == "custom":
            data = profile_presets.apply_preset_to_config(presets[0]["id"], {"sales_preset": "custom"}, home=home)
        elif raw.isdigit() and 1 <= int(raw) <= len(presets):
            data = profile_presets.apply_preset_to_config(presets[int(raw) - 1]["id"], home=home)
        else:
            data = profile_presets.apply_preset_to_config(raw, home=home)

    print("\n--- 1. 제품 · 고객 · 제안 가치 (Enter로 기존값 유지) ---")
    data["campaign_name"] = _prompt("캠페인 이름", data.get("campaign_name", "첫 아웃바운드 캠페인"))
    data["product"] = _prompt("제안하는 제품·서비스", data.get("product", ""))
    data["customer"] = _prompt("찾고 싶은 고객사(ICP)", data.get("customer", ""))
    data["value_proposition"] = _prompt("핵심 가치제안(1문장)", data.get("value_proposition", ""))
    data["proof_points"] = _prompt("검증된 강점/제안 포인트(선택)", data.get("proof_points", ""))

    print("\n--- 2. 공고·신호 검색 키워드 & 채용 보드 ---")
    data["keywords"] = _prompt("공통 업종/관심 키워드 (쉼표 구분)", data.get("keywords", ""))
    data["job_keywords"] = _prompt("채용 직무·기술 키워드 (쉼표 구분)", data.get("job_keywords", ""))
    data["jobs_query"] = _prompt("채용 사이트 검색어 (쉼표로 복수 지정 가능)", data.get("jobs_query", ""))
    cur_boards = ",".join(data.get("jobs_providers") or ["wanted", "saramin"])
    raw_boards = _prompt("채용 보드 (wanted,saramin,jobkorea,jumpit,ats_batch)", cur_boards)
    allowed_boards = {"wanted", "saramin", "jobkorea", "jumpit", "ats", "ats_batch", "greeting"}
    data["jobs_providers"] = [b.strip().lower() for b in raw_boards.split(",") if b.strip().lower() in allowed_boards] or ["wanted", "saramin"]
    data["region"] = _prompt("관심 지역", data.get("region", "대한민국"))
    data["exclude_keywords"] = _prompt("제외 키워드", data.get("exclude_keywords", "인턴, 아르바이트"))

    print("\n--- 3. 발신자 정보 & 아웃리치 스타일 ---")
    data["sender_name"] = _prompt("발신자 이름", data.get("sender_name", ""))
    data["sender_company"] = _prompt("발신자 소속 회사", data.get("sender_company", ""))
    data["sender_role"] = _prompt("발신자 직함 (예: Enterprise AE)", data.get("sender_role", ""))
    data["sender_contact"] = _prompt("발신자 연락처/이메일", data.get("sender_contact", ""))
    data["outreach_tone"] = _prompt("문체 (formal/consultative/concise/friendly)", data.get("outreach_tone", "consultative"))
    data["outreach_channel"] = _prompt("주요 채널 (email/linkedin/call)", data.get("outreach_channel", "email"))
    data["sender_cta"] = _prompt("기본 CTA 문구", data.get("sender_cta", ""))

    cur_dnc = ", ".join(data.get("do_not_contact") or [])
    raw_dnc = _prompt("연락 금지(DNC) 회사 목록 (쉼표 구분, 선택)", cur_dnc)
    data["do_not_contact"] = [x.strip() for x in raw_dnc.split(",") if x.strip()]

    validated = kit.validate(data)
    _atomic_write(config_path, json.dumps(validated, ensure_ascii=False, indent=2) + "\n", private=True)
    synced = sync_profile_to_home(validated, home, force=True)
    print(f"\n저장 완료: {config_path}")
    print("홈 동기화 결과:", json.dumps(synced, ensure_ascii=False))
    return validated


def manage_dnc(home: Path, add: list[str], remove: list[str]) -> list[str]:
    dnc_path = home / "do-not-contact.txt"
    existing: list[str] = []
    if dnc_path.is_file():
        existing = [
            line.strip() for line in dnc_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    remove_keys = {sources._norm_company_key(x) for x in remove}
    merged = [x for x in existing if sources._norm_company_key(x) not in remove_keys]
    seen = {sources._norm_company_key(x) for x in merged}
    for item in add:
        cleaned = item.strip()
        if cleaned and sources._norm_company_key(cleaned) not in seen:
            seen.add(sources._norm_company_key(cleaned))
            merged.append(cleaned)
    if add or remove:
        header = "# 연락 금지(Do-Not-Contact) 회사 목록 — 한 줄에 한 회사\n"
        _atomic_write(dnc_path, header + "\n".join(merged) + "\n", private=True)
    return merged


def manage_ats_targets(home: Path, add_specs: list[str], remove_tokens: list[str]) -> list[dict[str, str]]:
    ats_path = home / "ats-targets.json"
    if ats_path.is_file():
        targets = json.loads(ats_path.read_text(encoding="utf-8-sig"))
    else:
        default_src = ROOT / "pack" / "skills" / "ats-search" / "data" / "ats-targets.json"
        targets = json.loads(default_src.read_text(encoding="utf-8-sig")) if default_src.is_file() else []
    if remove_tokens:
        rem = {t.strip().lower() for t in remove_tokens}
        targets = [t for t in targets if str(t.get("token", "")).lower() not in rem and str(t.get("company", "")).lower() not in rem]
    for spec in add_specs:
        parts = spec.split(":", 2)
        if len(parts) < 2:
            raise ValueError(f"ATS 추가 형식은 'provider:token:회사명' 이어야 합니다: {spec}")
        provider = parts[0].strip().lower()
        token = parts[1].strip()
        company = parts[2].strip() if len(parts) == 3 and parts[2].strip() else token
        if provider not in sources.ATS_URLS:
            raise ValueError(f"지원하지 않는 ATS provider: {provider} (가능: {', '.join(sources.ATS_URLS)})")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", token):
            raise ValueError(f"올바르지 않은 board token: {token}")
        targets = [t for t in targets if not (t.get("ats") == provider and t.get("token") == token)]
        targets.append({"company": company, "ats": provider, "token": token})
    if add_specs or remove_tokens:
        _atomic_write(ats_path, json.dumps(targets, ensure_ascii=False, indent=2) + "\n", private=True)
    return targets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="다양한 영업 직군용 프로필·프리셋 커스텀 도구")
    sub = ap.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("presets", help="사용 가능한 영업 직군·업종 프리셋 목록 보기")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--home")

    p_init = sub.add_parser("init", help="프리셋 기반으로 setup.json 생성")
    p_init.add_argument("--preset", required=True, help="프리셋 ID (presets 명령으로 확인)")
    p_init.add_argument("--output", default=str(ROOT / "setup.json"))
    p_init.add_argument("--home")
    p_init.add_argument("--product")
    p_init.add_argument("--customer")
    p_init.add_argument("--keywords")
    p_init.add_argument("--job-keywords")
    p_init.add_argument("--jobs-query")
    p_init.add_argument("--region")
    p_init.add_argument("--sender-name")
    p_init.add_argument("--sender-company")
    p_init.add_argument("--sender-role")
    p_init.add_argument("--sender-contact")
    p_init.add_argument("--tone", choices=profile_presets.VALID_TONES)
    p_init.add_argument("--channel", choices=profile_presets.VALID_CHANNELS)
    p_init.add_argument("--source-mode", choices=("sample", "file", "live"))
    p_init.add_argument("--force", action="store_true", help="기존 setup.json 덮어쓰기 허용")
    p_init.add_argument("--sync", action="store_true", help="생성 직후 --home에 즉시 동기화")

    p_cust = sub.add_parser("customize", help="대화형으로 프로필·키워드·발신자·톤·DNC 수정")
    p_cust.add_argument("--config", default=str(ROOT / "setup.json"))
    p_cust.add_argument("--home")

    p_sync = sub.add_parser("sync", help="setup.json을 $HERMES_HOME(채점·발신자·DNC)에 반영")
    p_sync.add_argument("--config", default=str(ROOT / "setup.json"))
    p_sync.add_argument("--home")
    p_sync.add_argument("--force", action="store_true", help="기존 sales-profile.json 등 갱신")

    p_prev = sub.add_parser("preview", help="현재 프로필로 샘플 채점·초안 미리보기")
    p_prev.add_argument("--config", default=str(ROOT / "setup.json"))
    p_prev.add_argument("--home")
    p_prev.add_argument("--json", action="store_true")

    p_dnc = sub.add_parser("dnc", help="연락 금지(Do-Not-Contact) 회사 목록 조회/추가/삭제")
    p_dnc.add_argument("--home")
    p_dnc.add_argument("--add", action="append", default=[])
    p_dnc.add_argument("--remove", action="append", default=[])

    p_ats = sub.add_parser("ats", help="멀티 ATS 대상 회사(Greenhouse/Lever/Ashby/Greeting) 관리")
    p_ats.add_argument("--home")
    p_ats.add_argument("--add", action="append", default=[], help="provider:token:회사명 (예: greeting:myco:우리타깃)")
    p_ats.add_argument("--remove", action="append", default=[], help="제거할 token 또는 회사명")

    p_boot = sub.add_parser("bootstrap", help="브로셔·자사/경쟁사 홈페이지 분석으로 초기 타깃팅 인사이트 및 setup.json 자동 생성")
    p_boot.add_argument("--company-url", action="append", default=[], help="자사/제품 홈페이지 URL (복수 가능)")
    p_boot.add_argument("--competitor-url", action="append", default=[], help="경쟁사 홈페이지 URL (복수 가능)")
    p_boot.add_argument("--brochure", action="append", default=[], help="자사 브로셔 파일 (.md/.txt/.html/.docx/.pptx/.pdf)")
    p_boot.add_argument("--competitor-brochure", action="append", default=[], help="경쟁사 공개 자료 파일")
    p_boot.add_argument("--text", default="", help="직접 전달할 제품/브로셔 요약 텍스트")
    p_boot.add_argument("--max-subpages", type=int, default=2)
    p_boot.add_argument("--output", default=str(ROOT / "setup.json"))
    p_boot.add_argument("--insights", help="마크다운 타깃팅 인사이트 저장 경로")
    p_boot.add_argument("--home")
    p_boot.add_argument("--sync", action="store_true", help="추출 결과를 --home에 즉시 동기화")
    p_boot.add_argument("--force", action="store_true", help="기존 파일 덮어쓰기 허용")
    p_boot.add_argument("--use-hermes", action="store_true", help="설치된 Hermes LLM으로 심화 인사이트 추가")
    p_boot.add_argument("--use-jev", action="store_true", help="TYPESAFE_API_KEY(JEV_API_KEY)가 있으면 Jev로 프리셋/톤 보정")
    p_boot.add_argument("--json", action="store_true")

    p_style = sub.add_parser("style", help="개인 발신메일함 구조·톤앤매너 분석 및 writing-style.json 반영")
    p_style.add_argument("--discover", action="store_true", help="로컬 PC의 발신함(.mbox/.eml/Thunderbird/Apple Mail) 자동 탐색")
    p_style.add_argument("--mbox", help="로컬 .mbox 발신함 파일 경로")
    p_style.add_argument("--eml", help=".eml/.emlx 파일 또는 폴더 경로")
    p_style.add_argument("--samples", help="발신 메일 텍스트/마크다운/JSON/CSV 파일 경로")
    p_style.add_argument("--imap-host", help="읽기 전용 IMAP 서버 (예: imap.gmail.com)")
    p_style.add_argument("--imap-port", type=int, default=993)
    p_style.add_argument("--imap-mailbox", default="", help="발신함 폴더명 (생략 시 Sent/보낸편지함 자동 탐색)")
    p_style.add_argument("--limit", type=int, default=30)
    p_style.add_argument("--include-replies", action="store_true")
    p_style.add_argument("--home")
    p_style.add_argument("--config", help="감지된 톤/CTA 힌트를 반영할 setup.json 경로")
    p_style.add_argument("--apply", action="store_true", help="분석 결과를 --home/writing-style.json(및 --config)에 저장")
    p_style.add_argument("--report", help="마크다운 리포트 저장 경로")
    p_style.add_argument("--use-jev", action="store_true", help="TYPESAFE_API_KEY(JEV_API_KEY)가 있으면 Jev 톤 보정")
    p_style.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    home = paths.normalize_home(getattr(args, "home", None))
    try:
        if args.command == "style":
            import style_analyzer
            fwd: list[str] = []
            if args.discover:
                fwd.append("--discover")
            if args.mbox:
                fwd += ["--mbox", args.mbox]
            if args.eml:
                fwd += ["--eml", args.eml]
            if args.samples:
                fwd += ["--samples", args.samples]
            if args.imap_host:
                fwd += ["--imap-host", args.imap_host, "--imap-port", str(args.imap_port)]
                if args.imap_mailbox:
                    fwd += ["--imap-mailbox", args.imap_mailbox]
            fwd += ["--limit", str(args.limit), "--home", str(home)]
            if args.include_replies:
                fwd.append("--include-replies")
            if args.config:
                fwd += ["--config", args.config]
            if args.apply:
                fwd.append("--apply")
            if args.report:
                fwd += ["--report", args.report]
            if args.use_jev:
                fwd.append("--use-jev")
            if args.json:
                fwd.append("--json")
            return style_analyzer.main(fwd)

        if args.command == "bootstrap":
            import profile_bootstrap
            if not (args.company_url or args.brochure or args.text.strip()):
                ap.error("bootstrap에는 --company-url, --brochure, --text 중 하나 이상이 필요합니다.")
            res = profile_bootstrap.bootstrap_profile(
                company_urls=args.company_url,
                competitor_urls=args.competitor_url,
                brochures=args.brochure,
                competitor_brochures=args.competitor_brochure,
                inline_text=args.text,
                home=home,
                max_subpages=args.max_subpages,
                use_hermes=args.use_hermes,
                use_jev=args.use_jev,
            )
            out_path = Path(args.output).expanduser().absolute()
            if out_path.exists() and not args.force:
                raise ValueError(f"이미 파일이 있습니다: {out_path} (--force로 덮어쓰기 가능)")
            _atomic_write(out_path, json.dumps(res["config"], ensure_ascii=False, indent=2) + "\n", private=True)
            if args.insights:
                _atomic_write(Path(args.insights).expanduser().absolute(), res["insights_markdown"], private=False)
            if args.sync:
                res["synced"] = sync_profile_to_home(res["config"], home, force=args.force)
            if args.json:
                print(json.dumps({k: v for k, v in res.items() if k != "insights_markdown"}, ensure_ascii=False, indent=2))
            else:
                print(res["insights_markdown"])
                print(f"\nsetup.json 저장 완료: {out_path}")
            return 0

        if args.command == "presets":
            items = profile_presets.list_presets(home)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
                return 0
            print(f"사용 가능한 영업 직군 프리셋 ({len(items)}종):\n")
            for p in items:
                boards = ", ".join(p.get("default_jobs_providers") or [])
                print(f"- {p['id']:<28} {p['name']}")
                print(f"    설명: {p['tagline']}")
                print(f"    기본 시나리오: {p.get('default_scenario')} | 권장 채용보드: {boards}\n")
            return 0

        if args.command == "init":
            overrides = {
                "product": args.product,
                "customer": args.customer,
                "keywords": args.keywords,
                "job_keywords": args.job_keywords,
                "jobs_query": args.jobs_query,
                "region": args.region,
                "sender_name": args.sender_name,
                "sender_company": args.sender_company,
                "sender_role": args.sender_role,
                "sender_contact": args.sender_contact,
                "outreach_tone": args.tone,
                "outreach_channel": args.channel,
                "source_mode": args.source_mode,
            }
            data = profile_presets.apply_preset_to_config(args.preset, overrides, home=home)
            validated = kit.validate(data)
            out_path = Path(args.output).expanduser().absolute()
            if out_path.exists() and not args.force:
                raise ValueError(f"이미 파일이 있습니다: {out_path} (덮어쓰려면 --force 사용)")
            _atomic_write(out_path, json.dumps(validated, ensure_ascii=False, indent=2) + "\n", private=True)
            result: dict[str, Any] = {"status": "created", "config": str(out_path), "preset": args.preset}
            if args.sync:
                result["synced"] = sync_profile_to_home(validated, home, force=args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "customize":
            interactive_customize(Path(args.config).expanduser().absolute(), home)
            return 0

        if args.command == "sync":
            data = kit.load(args.config)
            synced = sync_profile_to_home(data, home, force=args.force)
            print(json.dumps({"status": "synced", "home": str(home), "files": synced}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "preview":
            data = kit.load(args.config)
            res = preview_profile(data, home=home)
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
                return 0
            print(f"=== 프로필 미리보기 (프리셋: {res['preset']} / 톤: {res['tone']} / 채널: {res['channel']}) ===\n")
            for idx, item in enumerate(res["previews"], 1):
                print(f"[{idx}] {item['company']} — {item['action']} (적합 {item['fit_score']} / 긴급 {item['urgency_score']})")
                print(f"    신호: {item['signal']}")
                print(f"    근거: {item['rationale']}\n")
                print(item["draft"])
                print("\n" + "─" * 60 + "\n")
            return 0

        if args.command == "dnc":
            items = manage_dnc(home, args.add, args.remove)
            print(json.dumps({"home": str(home), "count": len(items), "do_not_contact": items}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "ats":
            targets = manage_ats_targets(home, args.add, args.remove)
            print(json.dumps({"home": str(home), "count": len(targets), "targets": targets}, ensure_ascii=False, indent=2))
            return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
