#!/usr/bin/env python3
"""Obsidian CRM Board (6-stage Kanban) sync, plain-Korean strategy Knowledge docs,
and zero-dependency (pure Python) Vault & CRM integrity auditor.

Key operational guarantees:
1. Draft creation NEVER mutates contact history (첫연락일 / 최근연락일 / 연락횟수 remain empty/0).
2. Lead stage changes always update BOTH note frontmatter AND CRM Board.md in sync.
3. Sample/example leads live strictly under Templates/Examples/ and never pollute live CRM counts.
4. `audit_vault()` checks YAML frontmatter, Kanban sync, duplicate LinkedIn URLs/handles,
   broken [[wiki-links]], Markdown table column consistency, dummy lead contamination,
   and unsent-draft contact-history anomalies — without requiring PyYAML.
"""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

CRM_STAGES: tuple[str, ...] = ("소싱됨", "컨택함", "회신옴", "미팅예약", "검증완료", "제외")
DUMMY_MARKERS = ("jane cooper", "acme corp", "example.com/in/jane", "샘플담당자")

_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
_LINKEDIN_HANDLE_RE = re.compile(r"linkedin\.com/in/([^/?#\s\"']+)", re.I)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"심볼릭 링크에는 쓰지 않습니다: {path}")
    fd, staged = tempfile.mkstemp(prefix=".crm-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    """Pure-Python YAML frontmatter parser with strict syntax validation (no PyYAML required)."""
    errors: list[str] = []
    if not text.startswith("---"):
        return {}, text, errors
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, errors
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        errors.append("YAML frontmatter가 '---'로 닫히지 않았습니다.")
        return {}, text, errors

    meta: dict[str, Any] = {}
    current_list_key: str | None = None
    for lineno, raw in enumerate(lines[1:end_idx], start=2):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key is not None:
            item = stripped[2:].strip().strip('"').strip("'")
            meta.setdefault(current_list_key, []).append(item)
            continue
        if ":" not in raw:
            errors.append(f"frontmatter {lineno}행: 'key: value' 형식이 아닙니다 ({stripped[:40]})")
            continue
        key, val_raw = raw.split(":", 1)
        key = key.strip()
        if not key or any(c.isspace() for c in key):
            errors.append(f"frontmatter {lineno}행: 잘못된 키 이름({key})")
            continue
        val = val_raw.strip()
        current_list_key = None
        if val == "":
            meta[key] = ""
            current_list_key = key
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta[key] = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()] if inner else []
        elif val in ("true", "True"):
            meta[key] = True
        elif val in ("false", "False"):
            meta[key] = False
        elif re.fullmatch(r"-?\d+", val):
            meta[key] = int(val)
        elif (val.startswith('"') and not val.endswith('"')) or (val.startswith("'") and not val.endswith("'")):
            errors.append(f"frontmatter {lineno}행: 따옴표가 닫히지 않았습니다 ({key})")
            meta[key] = val.strip('"').strip("'")
        else:
            meta[key] = val.strip('"').strip("'")

    body = "\n".join(lines[end_idx + 1 :])
    return meta, body, errors


def _format_yaml_val(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        escaped = [json.dumps(str(v), ensure_ascii=False) for v in value]
        return "[" + ", ".join(escaped) + "]"
    return json.dumps(str(value if value is not None else ""), ensure_ascii=False)


def render_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {_format_yaml_val(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _iter_live_lead_notes(vault: Path) -> list[Path]:
    """Iterate real LinkedIn CRM lead notes (excludes Queue.md and Templates/Examples)."""
    li_dir = vault / "LinkedIn"
    if not li_dir.is_dir():
        return []
    notes: list[Path] = []
    for path in sorted(li_dir.rglob("*.md")):
        if path.name in ("Queue.md", "README.md", "CRM Board.md", "CRM Dashboard.md"):
            continue
        if "Templates" in path.parts or "Examples" in path.parts:
            continue
        notes.append(path)
    return notes


def _lead_rel_link(vault: Path, path: Path) -> str:
    rel = path.relative_to(vault).as_posix()
    return rel[:-3] if rel.endswith(".md") else rel


def sync_crm_board(vault_dir: str | Path) -> dict[str, Any]:
    """Synchronize Obsidian Kanban CRM Board.md and CRM Dashboard.md from live lead notes."""
    vault = Path(vault_dir).expanduser().absolute()
    vault.mkdir(parents=True, exist_ok=True)

    by_stage: dict[str, list[dict[str, Any]]] = {stage: [] for stage in CRM_STAGES}
    all_leads: list[dict[str, Any]] = []

    for note in _iter_live_lead_notes(vault):
        text = note.read_text(encoding="utf-8", errors="replace")
        meta, _body, _errs = parse_frontmatter(text)
        stage = str(meta.get("단계") or meta.get("stage") or "소싱됨").strip()
        if stage not in by_stage:
            stage = "소싱됨"
        name = str(meta.get("name") or note.stem).strip()
        company = str(meta.get("company") or note.parent.name).strip()
        score = meta.get("score", "")
        msg_state = str(meta.get("메시지상태") or "미발송").strip()
        rel = _lead_rel_link(vault, note)
        card = {
            "rel": rel,
            "name": name,
            "company": company,
            "score": score,
            "stage": stage,
            "msg_state": msg_state,
            "personalization": str(meta.get("개인화상태") or "초안작성").strip(),
            "contacts_count": int(meta.get("연락횟수") or 0) if str(meta.get("연락횟수") or "0").isdigit() else 0,
        }
        by_stage[stage].append(card)
        all_leads.append(card)

    # Write Obsidian Kanban board (CRM Board.md)
    board_lines = [
        "---",
        "kanban-plugin: basic",
        "---",
        "",
    ]
    for stage in CRM_STAGES:
        board_lines.append(f"## {stage}")
        board_lines.append("")
        for card in by_stage[stage]:
            badge = f" ({card['score']}점)" if card["score"] != "" else ""
            board_lines.append(f"- [ ] [[{card['rel']}|{card['name']} · {card['company']}{badge}]]")
        board_lines.append("")
    board_lines.extend([
        "%% kanban:settings",
        '```',
        '{"kanban-plugin":"basic"}',
        '```',
        "%%",
        "",
    ])
    board_path = vault / "CRM Board.md"
    _atomic_write(board_path, "\n".join(board_lines))

    # Write CRM Dashboard.md (Dataview + static summary so it works with or without Dataview)
    stage_summary = " | ".join(f"{s} {len(by_stage[s])}명" for s in CRM_STAGES)
    unsent = sum(1 for c in all_leads if c["msg_state"] == "미발송")
    sent_total = sum(c["contacts_count"] for c in all_leads)
    dash_md = (
        "# CRM Dashboard\n\n"
        f"- **실사용 리드**: {len(all_leads)}명 ({stage_summary})\n"
        f"- **초안 대기(미발송)**: {unsent}명 · **실제 발송 누적**: {sent_total}건\n"
        "- **Kanban 보드**: [[CRM Board]] · **운영 원칙**: [[Knowledge/개인화 메시지와 연락 이력 기록 기준]]\n\n"
        "## 단계별 현황 (Dataview)\n"
        "```dataview\n"
        "TABLE company AS \"회사\", title AS \"직함\", score AS \"ICP\", 단계, 개인화상태, 메시지상태, 연락횟수\n"
        "FROM \"LinkedIn\"\n"
        "WHERE file.name != \"Queue\" AND !contains(file.path, \"Templates\")\n"
        "SORT score DESC\n"
        "```\n"
    )
    dash_path = vault / "CRM Dashboard.md"
    _atomic_write(dash_path, dash_md)
    return {
        "board": str(board_path),
        "dashboard": str(dash_path),
        "live_leads": len(all_leads),
        "stage_counts": {s: len(by_stage[s]) for s in CRM_STAGES},
    }


def update_lead_stage(
    note_path: str | Path,
    new_stage: str,
    *,
    vault_dir: str | Path,
    mark_sent: bool = False,
    channel_note: str = "LinkedIn 메시지 발송",
    date_str: str = "",
) -> dict[str, Any]:
    """Update lead frontmatter stage and sync CRM Board.md atomically.

    Draft edits never mutate contact history; only explicit `mark_sent=True` increments 연락횟수.
    """
    if new_stage not in CRM_STAGES:
        raise ValueError(f"지원하는 단계는 {', '.join(CRM_STAGES)} 중 하나입니다: {new_stage}")
    target = Path(note_path).expanduser().absolute()
    if not target.is_file() or target.is_symlink():
        raise ValueError(f"리드 노트를 찾을 수 없습니다: {target}")
    text = target.read_text(encoding="utf-8")
    meta, body, errs = parse_frontmatter(text)
    if errs:
        raise ValueError("기존 frontmatter 오류: " + "; ".join(errs))

    meta["단계"] = new_stage
    today = date_str.strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if mark_sent:
        meta["메시지상태"] = "발송됨" if new_stage != "회신옴" else "회신옴"
        if not str(meta.get("첫연락일") or "").strip():
            meta["첫연락일"] = today
        meta["최근연락일"] = today
        prev_cnt = int(meta.get("연락횟수") or 0) if str(meta.get("연락횟수") or "0").isdigit() else 0
        meta["연락횟수"] = prev_cnt + 1
        history_line = f"- {today}: {channel_note} (단계: {new_stage})"
        if "## 연락 이력" in body:
            body = body.rstrip() + "\n" + history_line + "\n"
        else:
            body = body.rstrip() + "\n\n## 연락 이력\n\n" + history_line + "\n"

    updated = render_frontmatter(meta) + "\n" + body.lstrip("\n")
    _atomic_write(target, updated)
    board_info = sync_crm_board(vault_dir)
    return {
        "note": str(target),
        "stage": new_stage,
        "mark_sent": mark_sent,
        "contacts_count": meta.get("연락횟수", 0),
        "board": board_info,
    }


def ensure_knowledge_docs(vault_dir: str | Path, config: dict[str, Any] | None = None, *, force: bool = False) -> dict[str, Any]:
    """Generate plain-Korean strategy Knowledge docs and isolated Templates/Examples in the vault."""
    vault = Path(vault_dir).expanduser().absolute()
    cfg = config or {}
    product = str(cfg.get("product") or "우리 제품·서비스").strip()
    customer = str(cfg.get("customer") or "목표 고객 기업").strip()
    end_user = str(cfg.get("end_user_persona") or "실제 서비스를 사용하는 현장·실무 이용자").strip()
    buyer = str(cfg.get("buyer_persona") or "예산·계약·도입을 결정하는 본사 담당 팀장/임원").strip()
    misconception = str(cfg.get("common_misconception") or "기존에 쓰는 서비스·도구와 같다고 오해하는 지점").strip()
    reality = str(cfg.get("reality_differentiator") or cfg.get("value_proposition") or "실제 현장에서 해결하는 구체적인 업무 공백").strip()
    partial_entry = str(cfg.get("partial_entry_offer") or "전체 교체 대신 특정 팀·국가·프로젝트부터 작은 시험 운영으로 시작").strip()
    dnc = cfg.get("do_not_contact") or []
    competitors_line = ", ".join(str(x) for x in dnc[:6]) if dnc else "(브로셔·웹 분석 또는 직접 입력)"

    docs: dict[Path, str] = {
        vault / "Knowledge" / "영업 포지셔닝.md": (
            "# 영업 포지셔닝\n\n"
            "> 기존 제품이나 대안을 일률적으로 부정하지 않고, 실제 업무에서 누가 어떤 단계를 책임지는지 확인합니다.\n\n"
            "## 실제 제공 가능한 서비스\n"
            f"- **제품·서비스**: {product}\n"
            f"- **핵심 해결 가치**: {reality}\n\n"
            "## 실제 사용자와 구매 의사결정자 구분\n"
            f"- **실제 이용자(엔드유저)**: {end_user}\n"
            f"- **구매 의사결정자**: {buyer}\n"
            "- 현장 이용자의 불편만 이야기하지 말고, 본사 의사결정자가 책임지는 위험·비용·운영 부담으로 연결합니다.\n\n"
            "## 고객이 자주 오해하는 점과 실제 차이\n"
            f"- **자주 나오는 오해**: {misconception}\n"
            f"- **실제 차이**: {reality}\n\n"
            "## 기존 업체가 있을 때의 진입 방식 (부분 보완)\n"
            f"- {partial_entry}\n"
            "- 전면 교체를 먼저 요구하지 않고, 기존 계약이 비어 있는 지역·인원·업무 단계부터 확인합니다.\n"
        ),
        vault / "Knowledge" / "경쟁사 비교와 영업 판단.md": (
            "# 경쟁사 비교와 영업 판단\n\n"
            f"- **주요 비교 대상**: {competitors_line}\n\n"
            "## 경쟁사 자료를 쓰는 순서\n"
            "1. 경쟁사 고객이 어떤 문제 때문에 비용을 썼는지 확인합니다.\n"
            "2. 경쟁사 고객을 그대로 빼앗으려 하기보다, 같은 문제를 가진 비슷한 기업을 찾습니다.\n"
            "3. 기존 계약이 지원하지 않는 지역·인원·프로젝트 공백이 있는지 확인합니다.\n"
            "4. 전체 교체 대신 작은 시험 운영(부분 보완)으로 먼저 제안합니다.\n\n"
            "## 피해야 할 상황 · 승산이 낮은 상황\n"
            "- 다년 장기 계약이 막 시작됐고, 현재 운영상 공백이나 불만이 전혀 없는 경우\n"
            "- 구매 권한이 없는 실무자에게만 단독 접근하고 본사 결정권자 확인이 없는 경우\n\n"
            "## 시도해볼 만한 경우\n"
            "- 신규 해외 거점·프로젝트·인원이 늘어나 기존 계약 범위를 벗어난 경우\n"
            "- 실제 사고·장애·긴급 상황에서 현지 실행이나 한국 인계 담당자가 모호한 경우\n\n"
            "## 고객에게 확인할 질문\n"
            "- \"현재 계약으로 모든 지역·인원·긴급 상황이 빠짐없이 처리되고 있나요?\"\n"
            "- \"실제 문제가 생겼을 때 현지 조율부터 본사 보고까지 어느 담당자가 직접 움직이나요?\"\n\n"
            "## 아직 확인해야 할 내용\n"
            "- 공개 자료에 없는 경쟁사의 실제 단가, 응답 시간, 계약 해지 조건은 미팅에서 직접 확인합니다.\n"
        ),
        vault / "Knowledge" / "먼저 공략할 고객과 피할 고객.md": (
            "# 먼저 공략할 고객과 피할 고객\n\n"
            "## 먼저 공략할 고객 유형\n"
            f"- **핵심 타깃 기업**: {customer}\n"
            f"- **예상 담당자**: {buyer}\n"
            "- 최근 채용 공고·투자·해외 진출·나라장터 발주계획처럼 변화 신호가 공개 자료로 확인된 기업\n\n"
            "## 피해야 할 고객 조건\n"
            "- 연락 금지(DNC) 목록에 등록된 기존 고객·경쟁사·수신거부 기업\n"
            "- 공개 근거 없이 추측으로만 대상에 올린 기업\n"
            "- 실제 의사결정 라인과 예산 소유자가 확인되지 않는 단순 문의처\n\n"
            "## 접근 가능성 점검 기준\n"
            "| 항목 | 확인 질문 | 기록 위치 |\n"
            "|---|---|---|\n"
            "| 공개 근거 | 최근 90일 내 공개 기사·공고·발주계획이 있는가 | 리드 노트 `공개 근거` |\n"
            "| 예상 담당자 | 현장 실무자 외 본사 의사결정자를 찾았는가 | 리드 노트 `직함` |\n"
            "| 진입 범위 | 작은 시험 운영으로 시작할 접점이 있는가 | 리드 노트 `제안할 서비스` |\n"
        ),
        vault / "Knowledge" / "개인화 메시지와 연락 이력 기록 기준.md": (
            "# 개인화 메시지와 연락 이력 기록 기준\n\n"
            "## 핵심 원칙\n"
            "1. **초안 작성과 실제 연락을 엄격히 분리합니다.**\n"
            "   - 메시지 초안을 써도 `메시지상태`는 `미발송`, `연락횟수`는 `0`, `첫연락일·최근연락일`은 비워 둡니다.\n"
            "2. **공개 근거만 개인화에 사용합니다.**\n"
            "   - 공개 게시물이 없거나 적으면 상대의 성향·문체를 추정하지 않습니다.\n"
            "3. **사용자 승인 전에는 어떤 연결 요청이나 메시지도 발송하지 않습니다.**\n"
            "4. **리드 단계 변경 시 노트 속성과 [[CRM Board]] 카드를 항상 함께 갱신합니다.**\n\n"
            "## 표준 리드 속성\n"
            "| 속성 | 허용 값 | 설명 |\n"
            "|---|---|---|\n"
            "| `단계` | 소싱됨 / 컨택함 / 회신옴 / 미팅예약 / 검증완료 / 제외 | CRM 6단계 |\n"
            "| `개인화상태` | 미작성 / 초안작성 / 검토완료 | 초안 준비 여부 |\n"
            "| `메시지상태` | 미발송 / 발송됨 / 회신옴 | 실제 발송 여부 |\n"
            "| `연락횟수` | 0 이상 정수 | 실제 발송했을 때만 증가 |\n"
        ),
        vault / "Templates" / "Examples" / "LinkedIn Profile Example.md": (
            "---\n"
            'name: "예시 담당자"\n'
            'company: "예시기업"\n'
            'title: "안전기획팀장"\n'
            'tier: "A"\n'
            "score: 85\n"
            '단계: "소싱됨"\n'
            '개인화상태: "초안작성"\n'
            '메시지상태: "미발송"\n'
            '첫연락일: ""\n'
            '최근연락일: ""\n'
            '다음연락일: ""\n'
            "연락횟수: 0\n"
            'linkedin_url: "https://www.linkedin.com/in/example-profile"\n'
            "automatic_send: false\n"
            "---\n\n"
            "# 예시 담당자 · 예시기업 (템플릿 예시)\n\n"
            "> 이 파일은 `Templates/Examples/`에 격리된 예시입니다. 실사용 리드 집계와 CRM 보드에는 포함되지 않습니다.\n"
        ),
    }

    written: list[str] = []
    preserved: list[str] = []
    for path, content in docs.items():
        if path.exists() and not force:
            preserved.append(str(path))
            continue
        _atomic_write(path, content)
        written.append(str(path))
    return {"written": written, "preserved": preserved}


def _check_markdown_tables(text: str, rel_path: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    lines = text.splitlines()
    in_code = False
    table_cols: int | None = None
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            table_cols = None
            continue
        if in_code:
            continue
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            # Count unescaped pipes
            cells = re.split(r"(?<!\\)\|", stripped[1:-1])
            cols = len(cells)
            if table_cols is None:
                table_cols = cols
            elif cols != table_cols:
                issues.append({
                    "type": "table_column_mismatch",
                    "file": rel_path,
                    "line": idx,
                    "detail": f"표 열 개수 불일치 (기대 {table_cols}열, 실제 {cols}열)",
                })
        else:
            table_cols = None
    return issues


def _parse_kanban_board(board_path: Path) -> dict[str, str]:
    """Return mapping of normalized link target -> Kanban stage header."""
    mapping: dict[str, str] = {}
    if not board_path.is_file():
        return mapping
    current_stage = ""
    for line in board_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            current_stage = line[3:].strip()
            continue
        if current_stage in CRM_STAGES and line.lstrip().startswith("- ["):
            m = _WIKILINK_RE.search(line)
            if m:
                target = m.group(1).split("|", 1)[0].rstrip("\\").split("#", 1)[0].strip()
                mapping[target] = current_stage
    return mapping


def audit_vault(vault_dir: str | Path) -> dict[str, Any]:
    """Run comprehensive zero-dependency CRM & Obsidian Vault integrity audit."""
    vault = Path(vault_dir).expanduser().absolute()
    if not vault.is_dir():
        raise ValueError(f"볼트 디렉터리를 찾을 수 없습니다: {vault}")

    issues: list[dict[str, Any]] = []
    all_md = sorted(p for p in vault.rglob("*.md") if ".trash" not in p.parts)

    # Index valid link targets (both full relative stem and bare basename)
    rel_stems: set[str] = set()
    basenames: set[str] = set()
    for p in all_md:
        rel = _lead_rel_link(vault, p)
        rel_stems.add(rel)
        basenames.add(p.stem)

    yaml_errors = 0
    table_errors = 0
    broken_links = 0
    checked_links = 0

    for p in all_md:
        rel = p.relative_to(vault).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        _meta, body, fm_errs = parse_frontmatter(text)
        for err in fm_errs:
            yaml_errors += 1
            issues.append({"type": "yaml_error", "file": rel, "detail": err})

        t_issues = _check_markdown_tables(text, rel)
        table_errors += len(t_issues)
        issues.extend(t_issues)

        # Check [[wiki-links]] outside fenced code blocks
        in_code = False
        for lineno, line in enumerate(body.splitlines(), start=1):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            for m in _WIKILINK_RE.finditer(line):
                raw_target = m.group(1).split("|", 1)[0].rstrip("\\").split("#", 1)[0].strip()
                if not raw_target:
                    continue
                checked_links += 1
                clean_target = raw_target[:-3] if raw_target.endswith(".md") else raw_target
                if clean_target not in rel_stems and clean_target not in basenames:
                    broken_links += 1
                    issues.append({
                        "type": "broken_wikilink",
                        "file": rel,
                        "line": lineno,
                        "detail": f"대상 노트가 없습니다: [[{raw_target}]]",
                    })

    # Live CRM lead checks
    live_leads = _iter_live_lead_notes(vault)
    board_map = _parse_kanban_board(vault / "CRM Board.md")
    url_seen: dict[str, str] = {}
    handle_seen: dict[str, str] = {}
    board_mismatches = 0
    dup_urls = 0
    dup_handles = 0
    contact_anomalies = 0
    dummy_contaminations = 0
    live_rels: set[str] = set()

    for note in live_leads:
        rel = note.relative_to(vault).as_posix()
        rel_stem = _lead_rel_link(vault, note)
        live_rels.add(rel_stem)
        text = note.read_text(encoding="utf-8", errors="replace")
        meta, _body, _errs = parse_frontmatter(text)

        # Dummy lead contamination check
        lowered = f"{rel} {meta.get('name', '')} {meta.get('company', '')} {meta.get('linkedin_url', '')}".lower()
        if any(marker in lowered for marker in DUMMY_MARKERS):
            dummy_contaminations += 1
            issues.append({
                "type": "dummy_lead_in_live_crm",
                "file": rel,
                "detail": "예시 리드가 실사용 LinkedIn 폴더에 섞여 있습니다. Templates/Examples/로 옮기세요.",
            })

        # Duplicate LinkedIn URL & handle check
        li_url = str(meta.get("linkedin_url") or "").strip().rstrip("/").lower()
        if li_url:
            if li_url in url_seen:
                dup_urls += 1
                issues.append({
                    "type": "duplicate_linkedin_url",
                    "file": rel,
                    "detail": f"중복 LinkedIn URL (기존: {url_seen[li_url]})",
                })
            else:
                url_seen[li_url] = rel
            hm = _LINKEDIN_HANDLE_RE.search(li_url)
            if hm:
                handle = hm.group(1).lower()
                if handle in handle_seen and handle_seen[handle] != rel:
                    dup_handles += 1
                    issues.append({
                        "type": "duplicate_linkedin_handle",
                        "file": rel,
                        "detail": f"중복 LinkedIn 아이디 '{handle}' (기존: {handle_seen[handle]})",
                    })
                else:
                    handle_seen[handle] = rel

        # Draft vs contact history sanity check
        msg_state = str(meta.get("메시지상태") or "미발송").strip()
        cnt = int(meta.get("연락횟수") or 0) if str(meta.get("연락횟수") or "0").isdigit() else 0
        first_dt = str(meta.get("첫연락일") or "").strip()
        if msg_state == "미발송" and (cnt > 0 or first_dt):
            contact_anomalies += 1
            issues.append({
                "type": "unsent_draft_has_contact_history",
                "file": rel,
                "detail": f"메시지상태가 '미발송'인데 연락횟수({cnt}) 또는 첫연락일({first_dt})이 기록되어 있습니다.",
            })

        # Board vs frontmatter sync check
        if (vault / "CRM Board.md").is_file():
            stage = str(meta.get("단계") or "소싱됨").strip()
            board_stage = board_map.get(rel_stem)
            if board_stage is None:
                board_mismatches += 1
                issues.append({
                    "type": "missing_on_crm_board",
                    "file": rel,
                    "detail": f"리드가 CRM Board.md에 없습니다 (frontmatter 단계: {stage}). `outbound.py crm sync`를 실행하세요.",
                })
            elif board_stage != stage:
                board_mismatches += 1
                issues.append({
                    "type": "crm_board_stage_mismatch",
                    "file": rel,
                    "detail": f"단계 불일치: 노트({stage}) != CRM Board({board_stage})",
                })

    # Extra orphan cards on CRM Board
    if (vault / "CRM Board.md").is_file():
        for card_target, card_stage in board_map.items():
            if card_target not in live_rels:
                board_mismatches += 1
                issues.append({
                    "type": "orphan_crm_board_card",
                    "file": "CRM Board.md",
                    "detail": f"CRM Board '{card_stage}' 열의 [[{card_target}]]에 해당하는 리드 노트가 없습니다.",
                })

    return {
        "status": "ok" if not issues else "issues_found",
        "vault": str(vault),
        "summary": {
            "markdown_files": len(all_md),
            "live_crm_leads": len(live_leads),
            "crm_board_cards": len(board_map),
            "yaml_errors": yaml_errors,
            "board_mismatches": board_mismatches,
            "duplicate_linkedin_urls": dup_urls,
            "duplicate_linkedin_handles": dup_handles,
            "checked_wikilinks": checked_links,
            "broken_wikilinks": broken_links,
            "table_errors": table_errors,
            "contact_history_anomalies": contact_anomalies,
            "dummy_contaminations": dummy_contaminations,
            "total_issues": len(issues),
        },
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Obsidian CRM Board 동기화 · 전략 지식 생성 · 볼트 무결성 감사")
    sub = parser.add_subparsers(dest="action", required=True)

    p_sync = sub.add_parser("sync", help="리드 노트의 단계를 기준으로 CRM Board.md와 CRM Dashboard.md 동기화")
    p_sync.add_argument("--vault", required=True)

    p_stage = sub.add_parser("stage", help="특정 리드의 단계 변경 (+ 선택적으로 실제 발송 이력 기록) 및 보드 동시 갱신")
    p_stage.add_argument("--vault", required=True)
    p_stage.add_argument("--note", required=True)
    p_stage.add_argument("--to", required=True, choices=CRM_STAGES)
    p_stage.add_argument("--mark-sent", action="store_true", help="실제 발송을 완료한 경우에만 연락횟수/연락일 기록")
    p_stage.add_argument("--note-text", default="LinkedIn 메시지 발송")

    p_know = sub.add_parser("knowledge", help="쉬운 한국어 영업 포지셔닝·경쟁사 판단·기록 기준 Knowledge 문서 생성")
    p_know.add_argument("--vault", required=True)
    p_know.add_argument("--config", default="")
    p_know.add_argument("--force", action="store_true")

    p_audit = sub.add_parser("audit", help="볼트 전체 YAML·Kanban 동기화·중복 URL/ID·깨진 위키링크·표 열 오류 감사")
    p_audit.add_argument("--vault", required=True)

    args = parser.parse_args(argv)
    if args.action == "sync":
        out = sync_crm_board(args.vault)
    elif args.action == "stage":
        out = update_lead_stage(args.note, args.to, vault_dir=args.vault, mark_sent=args.mark_sent, channel_note=args.note_text)
    elif args.action == "knowledge":
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8-sig")) if args.config else {}
        out = ensure_knowledge_docs(args.vault, cfg, force=args.force)
    else:
        out = audit_vault(args.vault)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("status", "ok") != "issues_found" else 1


if __name__ == "__main__":
    raise SystemExit(main())
