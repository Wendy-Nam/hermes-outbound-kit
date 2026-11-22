#!/usr/bin/env python3
"""Deterministic, Markdown-only Obsidian workflow for outbound evidence.

This runner never sends messages and never claims its draft template is AI-generated.
Human-owned Inbox and Review notes are create-only. Generated notes carry a marker and
preserve the text inside their user-notes block across reconciliations.
"""
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
VAULT_MARKER = ".hermes-outbound-vault.json"
STATE = ".hermes-outbound/state.json"
MACHINE_MARK = "<!-- hermes-outbound:machine-owned:v1 -->"
USER_START = "<!-- user-notes:start -->"
USER_END = "<!-- user-notes:end -->"
SOURCE_STATES = {"ok", "empty", "blocked", "failed", "invalid_response"}
RECORD_TYPES = {"job_posting", "funding_signal", "procurement", "overseas_partner", "news", "other"}
DECISIONS = {"pending", "approved", "rejected"}
MAX_INPUT = 8 * 1024 * 1024


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _slug(value: str, limit: int = 36) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value.strip().lower()).strip("-")
    return (text or "record")[:limit].rstrip("-")


def _safe_text(value: object, field: str, limit: int = 4000, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field}: 문자열이어야 합니다.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field}: 값이 필요합니다.")
    if len(value) > limit or any(ord(c) < 32 and c not in "\t" for c in value):
        raise ValueError(f"{field}: 허용 길이 또는 문자 범위를 벗어났습니다.")
    return value


def _safe_multiline(value: object, field: str, limit: int = 20000, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field}: 문자열이어야 합니다.")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if required and not value:
        raise ValueError(f"{field}: 값이 필요합니다.")
    if len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{field}: 허용 길이 또는 문자 범위를 벗어났습니다.")
    return value


def _url(value: object, field: str) -> str:
    value = _safe_text(value, field, 2000, required=True)
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
        raise ValueError(f"{field}: 공개 http(s) URL이 필요합니다.")
    return value


def _path(path: str | Path, *, existing_file: bool = False) -> Path:
    candidate = Path(path).expanduser().absolute()
    if candidate.is_symlink():
        raise ValueError(f"심볼릭 링크 경로는 사용할 수 없습니다: {candidate}")
    if existing_file:
        if not candidate.is_file() or candidate.stat().st_size > MAX_INPUT:
            raise ValueError("입력은 8MiB 이하의 일반 파일이어야 합니다.")
    return candidate


def _assert_managed_path(vault: Path, target: Path) -> None:
    try:
        target.relative_to(vault)
    except ValueError:
        raise ValueError("볼트 밖 경로는 쓸 수 없습니다.") from None
    current = target
    while current != vault:
        if current.exists() and current.is_symlink():
            raise ValueError(f"관리 경로의 심볼릭 링크를 거부했습니다: {current}")
        current = current.parent
    if vault.exists() and vault.is_symlink():
        raise ValueError("볼트가 심볼릭 링크입니다.")


def _atomic(path: Path, text: str) -> bool:
    if path.is_symlink():
        raise ValueError(f"심볼릭 링크 파일을 갱신하지 않습니다: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return False
    fd, temporary = tempfile.mkstemp(prefix=".vault-flow-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def _create_human(path: Path, text: str) -> bool:
    """Create a human-owned note once. Existing content is never read-modify-written."""
    if path.is_symlink():
        raise ValueError(f"사람 소유 노트가 심볼릭 링크입니다: {path}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"노트 경로가 일반 파일이 아닙니다: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return True


def _user_notes(old: str) -> str:
    start, end = old.find(USER_START), old.find(USER_END)
    if start < 0 or end < 0 or end < start:
        return ""
    return old[start + len(USER_START):end].strip("\n")


def _machine_note(path: Path, generated: str) -> bool:
    """Reconcile a generated note while preserving its explicit custom-text block."""
    notes = ""
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"생성 노트 경로를 안전하게 갱신할 수 없습니다: {path}")
        old = path.read_text(encoding="utf-8")
        if MACHINE_MARK not in old:
            raise ValueError(f"사람이 만든 파일을 덮어쓰지 않습니다: {path}")
        notes = _user_notes(old)
    text = (MACHINE_MARK + "\n" + generated.rstrip() + "\n\n" + USER_START + "\n" +
            notes + ("\n" if notes else "") + USER_END + "\n")
    return _atomic(path, text)


def _vault(vault: str | Path, require_initialized: bool = True) -> Path:
    root = _path(vault)
    if require_initialized:
        marker = root / VAULT_MARKER
        if not marker.is_file() or marker.is_symlink():
            raise ValueError("초기화된 Hermes Outbound 볼트가 아닙니다. 먼저 init을 실행하세요.")
    return root


def init_vault(vault: str | Path, brief: str | None = None) -> Path:
    root = _vault(vault, require_initialized=False)
    if root.exists() and not root.is_dir():
        raise ValueError("볼트 경로가 디렉터리가 아닙니다.")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("Inbox", "Accounts", "Evidence", "Scores", "Drafts", "Review", "Runs", ".hermes-outbound"):
        target = root / name
        _assert_managed_path(root, target)
        if target.exists() and (target.is_symlink() or not target.is_dir()):
            raise ValueError(f"볼트 디렉터리 충돌: {target}")
        target.mkdir(exist_ok=True)
    for target in (root / VAULT_MARKER, root / STATE, root / "Dashboard.md", root / "Inbox/Brief.md"):
        _assert_managed_path(root, target)
    _atomic(root / VAULT_MARKER, json.dumps({"schema_version": 1, "kind": "hermes-outbound-vault"},
                                            ensure_ascii=False, indent=2) + "\n")
    brief_text = (brief if brief is not None else
                  (ROOT / "pack/vault/Inbox/Brief.md").read_text(encoding="utf-8"))
    _create_human(root / "Inbox/Brief.md", _safe_multiline(brief_text, "brief", 20000, required=True) + "\n")
    if not (root / STATE).exists():
        _atomic(root / STATE, json.dumps({"schema_version": 1, "runs": {}, "accounts": {}},
                                         ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _render_dashboard(root, {"schema_version": 1, "runs": {}, "accounts": {}})
    return root


def _load_envelope(path: str | Path | None) -> tuple[dict, str]:
    source = _path(path or ROOT / "pack/vault/seed/normalized-records.json", existing_file=True)
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"입력 JSON을 읽을 수 없습니다: {exc.msg}") from None
    if not isinstance(raw, dict) or raw.get("status") not in SOURCE_STATES:
        raise ValueError("입력은 status/source/records/errors를 가진 source envelope여야 합니다.")
    envelope_source = _safe_text(raw.get("source"), "source", 200, required=True)
    records = raw.get("records")
    errors = raw.get("errors", [])
    if not isinstance(records, list) or not isinstance(errors, list):
        raise ValueError("records와 errors는 배열이어야 합니다.")
    safe_errors = [_safe_text(x, "errors[]", 1000) for x in errors]
    normalized = {"status": raw["status"], "source": envelope_source,
                  "records": [_normalize_record(r, envelope_source) for r in records],
                  "errors": safe_errors}
    if raw["status"] != "ok" and records:
        raise ValueError("ok가 아닌 source envelope은 records를 포함할 수 없습니다.")
    return normalized, str(source)


# Plain, honest 1-line context openers — no fake flattery, no lecturing, easy to read on mobile.
_TEMPLATE_HOOKS = {
    "ko": {
        "job_posting": "「{title}」 공고 보고 짧게 연락드립니다.",
        "funding_signal": "「{title}」 기사 보고 짧게 연락드립니다.",
        "procurement": "「{title}」 공고 보고 문의드립니다.",
        "overseas_partner": "「{title}」 관련해서 짧게 여쭤보고 싶습니다.",
    },
    "en": {
        "job_posting": "Saw your {title} posting and wanted to reach out briefly.",
        "funding_signal": "Saw the news on {title} — quick note.",
        "procurement": "Saw the {title} notice and wanted to check one thing.",
        "overseas_partner": "Came across {title} — quick question on Korea.",
    },
}


def _josa(word: str, with_final: str, without_final: str) -> str:
    last = word.rstrip()[-1:] if word.strip() else ""
    if "가" <= last <= "힣":
        return word + (with_final if (ord(last) - 0xAC00) % 28 else without_final)
    return f"{word}{with_final}({without_final})"


def _apply_style_placeholders(pattern: str, company: str) -> str:
    out = pattern.replace("{회사}", company or "귀사").replace("{담당자}", "담당자")
    out = out.replace("{name}", f"{company} team" if company else "there")
    return out.strip()


def _template_draft(record: dict, product: str, customer: str, language: str,
                    profile: dict | None = None) -> str:
    profile = profile or {}
    lang = "en" if language.casefold().startswith("en") else "ko"
    hooks = _TEMPLATE_HOOKS[lang]
    opener = hooks.get(record["record_type"], hooks["procurement"])
    preset_hooks = profile.get("preset_hooks") if isinstance(profile.get("preset_hooks"), dict) else {}
    custom_hook = preset_hooks.get(record["record_type"]) if lang == "ko" else None
    wstyle = profile.get("writing_style") if isinstance(profile.get("writing_style"), dict) else {}
    wpat = wstyle.get("patterns") if isinstance(wstyle.get("patterns"), dict) else {}
    wstruct = wstyle.get("structure") if isinstance(wstyle.get("structure"), dict) else {}
    use_bullets = float(wstruct.get("bullet_usage_rate") or 0.0) >= 0.35
    use_bracket_subj = any("말머리" in str(p) for p in (wstruct.get("subject_patterns") or []))

    title = record["title"]
    company = record.get("company") or record.get("company_candidate") or ""
    tone = (profile.get("outreach_tone") or wstyle.get("detected_tone") or "consultative").strip()
    channel = (profile.get("outreach_channel") or "email").strip()
    value_prop = (profile.get("value_proposition") or "").strip()
    proof = (profile.get("proof_points") or "").strip()
    sender_name = (profile.get("sender_name") or "").strip()
    sender_company = (profile.get("sender_company") or "").strip()
    sender_role = (profile.get("sender_role") or "").strip()
    sender_contact = (profile.get("sender_contact") or "").strip()
    sender_cta = (profile.get("sender_cta") or wpat.get("preferred_cta") or "").strip()
    stack = record.get("stack") or []

    if lang == "en":
        greeting = (
            _apply_style_placeholders(wpat["preferred_greeting"], company)
            if wpat.get("preferred_greeting") and lang == wstyle.get("language")
            else (f"Hi {company} team," if company else "Hi,")
        )
        cta = sender_cta or "Is this on your list right now, or not a priority?"
        val = value_prop or f"We work on {product}."
        sig_parts = [p for p in (sender_name, sender_role, sender_company, sender_contact) if p]
        sign = "\n" + " · ".join(sig_parts) if sig_parts else ""
        if channel == "linkedin":
            return f"[LinkedIn DM]\n{greeting}\n{opener.format(title=title)}\n{val}\n{cta}{sign}"
        if channel == "call":
            return (f"[Call Opener]\n- {sender_name or 'Hi'}, {sender_company or ''}\n"
                    f"- {opener.format(title=title)}\n- {val}\n- {cta}")
        closing = wpat.get("preferred_closing") if (wpat.get("preferred_closing") and lang == wstyle.get("language")) else "Thanks,"
        return (f"Subject: {title}\n\n{greeting}\n\n"
                f"{opener.format(title=title)}\n\n"
                f"{val}\n\n{cta}\n\n{closing}{sign}")

    # Korean — plain, short, 1 idea per line, zero cheesy sales pitch
    reason_line = (
        custom_hook.format(title=title)
        if isinstance(custom_hook, str) and "{title}" in custom_hook
        else opener.format(title=title)
    )
    default_cta = "지금 우선순위에 있는 주제인지, 아니면 해당 없으신지만 짧게 알려주셔도 됩니다."
    cta = sender_cta or default_cta

    intro_self = ""
    if sender_company and sender_name:
        role_bit = f" {sender_role}" if sender_role else ""
        intro_self = f"{sender_company} {sender_name}{role_bit}입니다."
    elif sender_name:
        intro_self = f"{sender_name}입니다."

    sig_parts = [p for p in (sender_name, sender_role, sender_company, sender_contact) if p]
    sign = ("\n" + " · ".join(sig_parts)) if sig_parts else ""
    plain_what = value_prop or f"{product} 일을 하고 있습니다"
    if not plain_what.endswith((".", "다", "요", "?")):
        plain_what += "."

    if channel == "linkedin":
        who = f"{company} 담당자님" if company else "담당자님"
        lines = [f"[LinkedIn DM]", f"안녕하세요 {who}, {intro_self}".strip(), reason_line, plain_what, cta]
        return "\n".join(l for l in lines if l) + sign

    if channel == "call":
        return "\n".join([
            "[통화 메모 · 20초]",
            f"- 인사: 안녕하세요, {intro_self or '잠깐 여쭤볼 게 있어 전화드렸습니다.'}",
            f"- 이유: {reason_line}",
            f"- 요점: {plain_what}",
            f"- 확인: {cta}",
        ])

    if wpat.get("preferred_greeting") and wstyle.get("language", "ko") == "ko":
        greeting = _apply_style_placeholders(wpat["preferred_greeting"], company)
    elif tone == "formal":
        greeting = f"안녕하십니까, {company} 담당자님." if company else "안녕하십니까."
    else:
        greeting = f"안녕하세요, {company} 담당자님." if company else "안녕하세요."
    if intro_self:
        greeting = f"{greeting} {intro_self}"

    closing = (
        wpat["preferred_closing"]
        if wpat.get("preferred_closing") and wstyle.get("language", "ko") == "ko"
        else "감사합니다."
    )

    short_title = title[:26] + ("…" if len(title) > 26 else "")
    if use_bracket_subj and company:
        subject = f"[{company}] {short_title}"
    elif company:
        subject = f"{company} {short_title} 관련"
    else:
        subject = f"{short_title} 관련"

    body_lines = [reason_line]
    if use_bullets:
        body_lines.append("")
        body_lines.append(f"- 하는 일: {product}")
        body_lines.append(f"- 핵심: {plain_what}")
        if proof:
            body_lines.append(f"- 참고: {proof}")
    else:
        body_lines.append("")
        body_lines.append(plain_what)
        if proof:
            body_lines.append(proof + ("" if proof.endswith((".", "다", "요", "?")) else "."))

    context_hints = []
    if stack:
        context_hints.append(f"스택/키워드: {', '.join(stack[:5])}")
    if record.get("location"):
        context_hints.append(f"위치: {record['location']}")
    memo_block = (
        "\n\n---\n[발송 전 내 말로 바꿀 1줄 메모]\n"
        + "\n".join(f"- {h}" for h in context_hints)
        + "\n- 위 근거 링크를 30초 보고, 상대 회사에만 해당하는 진짜 한 문장만 넣으세요."
    ) if context_hints else ""

    return (f"제목: {subject}\n\n{greeting}\n\n"
            + "\n".join(body_lines)
            + f"\n\n{cta}\n\n{closing}{sign}{memo_block}")


def _normalize_record(raw: object, envelope_source: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("각 record는 객체여야 합니다.")
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("record.evidence 객체가 필요합니다.")
    record_type = _safe_text(raw.get("record_type"), "record_type", 40, required=True)
    if record_type not in RECORD_TYPES:
        raise ValueError(f"지원하지 않는 record_type: {record_type}")
    source = _safe_text(raw.get("source") or envelope_source, "record.source", 200, required=True)
    source_id = _safe_text(raw.get("source_id"), "source_id", 500, required=True)
    company = _safe_text(raw.get("company"), "company", 300)
    candidate = _safe_text(raw.get("company_candidate"), "company_candidate", 300)
    title = _safe_text(raw.get("title"), "title", 1000, required=True)
    url = _url(raw.get("url"), "url")
    ev_source = _safe_text(evidence.get("source"), "evidence.source", 200, required=True)
    ev_url = _url(evidence.get("url"), "evidence.url")
    ev_source_id = _safe_text(evidence.get("source_id"), "evidence.source_id", 500, required=True)
    if ev_source != source or ev_source_id != source_id or ev_url != url:
        raise ValueError("evidence의 source/source_id/url은 record와 일치해야 합니다.")
    raw_hash = _safe_text(evidence.get("raw_sha256"), "evidence.raw_sha256", 64, required=True)
    if not re.fullmatch(r"[a-fA-F0-9]{64}", raw_hash):
        raise ValueError("evidence.raw_sha256는 64자리 SHA-256이어야 합니다.")
    stack = raw.get("stack")
    if stack is not None and (not isinstance(stack, list) or any(not isinstance(x, str) for x in stack)):
        raise ValueError("stack은 문자열 배열 또는 null이어야 합니다.")
    if stack is not None:
        stack = [_safe_text(x, "stack[]", 200, required=True) for x in stack]
    return {
        "schema_version": _safe_text(str(raw.get("schema_version", "1")), "schema_version", 40, required=True),
        "record_type": record_type, "source": source, "source_id": source_id,
        "company": company or None, "company_candidate": candidate,
        "company_confidence": raw.get("company_confidence"), "title": title, "url": url,
        "published_at": _safe_text(raw.get("published_at"), "published_at", 80),
        "stack": stack, "location": _safe_text(raw.get("location"), "location", 500),
        "description": _safe_text(raw.get("description"), "description", 4000),
        "evidence": {"source": ev_source, "url": ev_url, "source_id": ev_source_id,
                     "retrieved_at": _safe_text(evidence.get("retrieved_at"), "evidence.retrieved_at", 80),
                     "raw_sha256": raw_hash.lower()},
    }


def _read_state(root: Path) -> dict:
    path = root / STATE
    if path.is_symlink() or not path.is_file():
        raise ValueError("볼트 상태 파일을 안전하게 읽을 수 없습니다.")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != 1 or not isinstance(state.get("accounts"), dict):
        raise ValueError("볼트 상태 파일 형식이 잘못되었습니다.")
    return state


def _review(path: Path, draft_hash: str) -> tuple[str, str]:
    if not path.exists():
        return "pending", "review_note_missing"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Review 노트를 안전하게 읽을 수 없습니다: {path}")
    text = path.read_text(encoding="utf-8")
    decision_match = re.search(r"(?m)^decision:\s*(pending|approved|rejected)\s*$", text)
    hash_match = re.search(r"(?m)^approved_draft_hash:\s*['\"]?([a-f0-9]*)['\"]?\s*$", text)
    decision = decision_match.group(1) if decision_match else "pending"
    approved_hash = hash_match.group(1) if hash_match else ""
    if decision == "approved" and approved_hash != draft_hash:
        return "invalidated", "draft_hash_changed_or_missing"
    return decision, "hash_matches" if decision == "approved" else decision


def _review_template(account_id: str, company: str, draft_hash: str) -> str:
    return f"""---
account_id: {account_id}
decision: pending
approved_draft_hash: ""
---
# 검토 — {company}

이 노트는 사람이 관리하며 러너가 덮어쓰지 않습니다.

1. `[[Drafts/{account_id}]]`의 근거·표현·수신 대상을 확인합니다.
2. 승인하려면 `decision: approved`로 바꾸고 Draft 노트의 `draft_content_hash`를 `approved_draft_hash`에 복사합니다.
3. 초안이 바뀌면 해시가 달라져 승인이 자동 무효화됩니다. 거절은 `decision: rejected`로 기록합니다.

생성 당시 초안 해시: `{draft_hash}`

## 사람 메모

- 실제 발송은 자동으로 실행되지 않습니다.
"""


def _account_id(record: dict) -> str:
    company = record["company"]
    return "acct-" + _slug(company) + "-" + _digest({"company": company.casefold()})[:10]


def _evidence_id(record: dict) -> str:
    return "ev-" + _digest({"source": record["source"], "source_id": record["source_id"]})[:14]


def _next_task(stage: str, review_state: str = "") -> str:
    if stage == "identity_blocked": return "회사 후보를 확인하고 source record의 company를 확정"
    if stage == "evidence": return "출처가 완전한지 확인"
    if stage == "score": return "점수 근거를 검토"
    if stage == "draft": return "초안 생성 상태 확인"
    if review_state == "pending": return "Review에서 초안을 검토하고 결정"
    if review_state == "invalidated": return "변경된 초안을 다시 검토하고 새 해시로 승인"
    if review_state == "rejected": return "거절 사유를 기록하거나 초안 조건 수정"
    if review_state == "approved": return "승인 완료; 자동 발송 없음"
    return "입력과 상태 확인"


def _load_gtm_vault():
    """Import pack/skills/account-crm/scripts/gtm_vault.py lazily without polluting sys.path permanently."""
    module_path = ROOT / "pack" / "skills" / "account-crm" / "scripts" / "gtm_vault.py"
    if not module_path.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("hermes_outbound_gtm_vault", module_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sync_gtm_crm(root: Path, crm_rows: list[dict], draft_rows: list[dict]) -> dict:
    """Sync workflow outputs into GTM/Accounts, GTM/Drafts, and GTM/Pipeline.md preserving human edits."""
    gtm = _load_gtm_vault()
    if gtm is None or not crm_rows:
        return {"synced": False, "accounts": 0, "drafts": 0}
    ledger = gtm.VaultLedger(root)
    existing = ledger.load()
    data_fields = ("company", "action", "fit", "urgency", "fit_missing", "urgency_missing", "signals", "evidence")
    added = updated = 0
    for row in crm_rows:
        k = gtm.key(row.get("company", ""))
        if not k:
            continue
        if k in existing:
            for f in data_fields:
                if f in row:
                    existing[k][f] = row[f]
            updated += 1
        else:
            rec = {f: row.get(f) for f in data_fields}
            rec["status"] = "발굴"
            rec["notes"] = []
            rec["contacted_at"] = ""
            existing[k] = rec
            added += 1
    ledger.save(existing)
    draft_count = 0
    for d in draft_rows:
        path = gtm.write_draft(root, d["company"], d["action"], d["draft"], d["evidence"])
        if path:
            draft_count += 1
    return {"synced": True, "added": added, "updated": updated, "drafts": draft_count}


def run_flow(vault: str | Path, input_path: str | Path | None = None, *,
             profile: dict | None = None, drafts: dict | None = None,
             scores: dict | None = None, run_id: str | None = None,
             sync_gtm: bool = True) -> dict:
    root = _vault(vault)
    envelope, input_name = _load_envelope(input_path)
    input_digest = _digest(envelope)
    run_id = run_id or "run-" + input_digest[:14]
    if not re.fullmatch(r"run-[a-zA-Z0-9._-]{6,80}", run_id):
        raise ValueError("run_id 형식이 잘못되었습니다.")
    profile = profile or {}
    drafts = drafts or {}
    scores = scores or {}
    state = _read_state(root)
    seen_records = state.setdefault("seen_records", {})
    diff_counts = {"new": 0, "changed": 0, "unchanged": 0}
    result = {"run_id": run_id, "source": envelope["source"], "source_status": envelope["status"],
              "errors": envelope["errors"], "input_digest": input_digest, "input": input_name,
              "accounts": [], "diff": diff_counts, "completed": False}
    crm_rows: list[dict] = []
    crm_drafts: list[dict] = []

    if envelope["status"] == "ok":
        for record in envelope["records"]:
            ev = record["evidence"]
            prev_hash = seen_records.get(record["source_id"])
            if prev_hash is None:
                diff_status = "new"
            elif prev_hash != ev["raw_sha256"]:
                diff_status = "changed"
            else:
                diff_status = "unchanged"
            diff_counts[diff_status] += 1
            seen_records[record["source_id"]] = ev["raw_sha256"]

            if not record["company"]:
                result["accounts"].append({"source_id": record["source_id"], "company_candidate": record["company_candidate"],
                                            "diff": diff_status, "stage": "identity_blocked",
                                            "next_task": _next_task("identity_blocked")})
                continue
            account_id, evidence_id = _account_id(record), _evidence_id(record)
            account_path = root / f"Accounts/{account_id}.md"
            evidence_path = root / f"Evidence/{evidence_id}.md"
            score_path = root / f"Scores/{account_id}.md"
            draft_path = root / f"Drafts/{account_id}.md"
            review_path = root / f"Review/{account_id}.md"
            for target in (account_path, evidence_path, score_path, draft_path, review_path):
                _assert_managed_path(root, target)
            stack = ", ".join(record["stack"] or []) or "미확인"
            previous = state["accounts"].get(account_id, {})
            evidence_ids = list(dict.fromkeys([*previous.get("evidence_ids", []), evidence_id]))
            evidence_links = "\n".join(f"  - [[Evidence/{item}]]" for item in evidence_ids)
            _machine_note(account_path, f"""# Account — {record['company']}

- account_id: `{account_id}`
- 회사 식별 신뢰도: `{record['company_confidence']}`
- 위치: {record.get('location') or '미확인'}
- 기술 스택: {stack}
- 전체 근거 ({len(evidence_ids)}건):
{evidence_links}
- 점수: [[Scores/{account_id}]]
- 초안: [[Drafts/{account_id}]]
- 사람 검토: [[Review/{account_id}]]
""")
            desc_line = f"\n- 요약/JD: {record['description']}" if record.get("description") else ""
            _machine_note(evidence_path, f"""# Evidence — {record['company']}

- evidence_id: `{evidence_id}`
- 유형: `{record['record_type']}`
- 변경 상태: `{diff_status}`
- 제목: {record['title']}{desc_line}
- source: `{ev['source']}`
- source_id: `{ev['source_id']}`
- 원문: {ev['url']}
- 게시 시각: `{record['published_at'] or '미확인'}`
- 수집 시각: `{ev['retrieved_at'] or '미확인'}`
- raw_sha256: `{ev['raw_sha256']}`

이 노트는 출처가 있는 사실 후보를 보관합니다. 채용공고나 투자 소식은 구매 예산의 증명이 아닙니다.
""")
            coverage_fields = [record["company"], record["title"], record["url"], record["published_at"],
                               ev["source"], ev["source_id"], ev["retrieved_at"], ev["raw_sha256"]]
            coverage = round(sum(bool(x) for x in coverage_fields) / len(coverage_fields) * 100)
            score = scores.get(record["source_id"], {})
            fit = score.get("fit", "unknown")
            urgency = score.get("urgency", "unknown")
            fit_score = score.get("fit_score")
            urgency_score = score.get("urgency_score")
            action = score.get("action") or "리서치 필요"
            fit_missing = score.get("fit_missing") or []
            urgency_missing = score.get("urgency_missing") or []
            rationale = _safe_text(score.get("rationale"), "score.rationale", 2000) or "프로필 기반 점수 없음"
            fit_score_str = "미산출(리서치 필요)" if fit_score is None else f"{fit_score}/100"
            urg_score_str = "미산출(리서치 필요)" if urgency_score is None else f"{urgency_score}/100"
            missing_all = fit_missing + urgency_missing
            missing_line = f"\n- 미확인 축: {', '.join(missing_all)}" if missing_all else ""
            _machine_note(score_path, f"""# Evidence score — {record['company']}

- account_id: `{account_id}`
- 권장 액션: **{action}**
- 적합도 점수 (Fit): `{fit_score_str}` (profile_fit: `{fit}`)
- 긴급도 점수 (Urgency): `{urg_score_str}` (urgency: `{urgency}`)
- 근거 충족률 (evidence_coverage): `{coverage}%`{missing_line}
- 근거 설명: {rationale}
- signal_type: `{record['record_type']}`
- 전체 근거 수: `{len(evidence_ids)}`

모르는 축은 감점하지 않고 분모에서 제외합니다. 실제 연락 전 Inbox 브리프와 사람 검토가 필요합니다.
""")
            supplied = drafts.get(record["source_id"])
            if supplied:
                mode = _safe_text(supplied.get("mode"), "draft.mode", 20, required=True)
                body = _safe_multiline(supplied.get("body"), "draft.body", 12000, required=True)
                draft_body = f"> `{mode}` 모드 초안입니다. 자동 발송되지 않습니다.\n\n{body}"
                raw_draft_text = body
            else:
                product = _safe_text(profile.get("product"), "profile.product", 1000) or "저희 제안"
                customer = _safe_text(profile.get("customer"), "profile.customer", 1000) or "해당 조직"
                language = _safe_text(profile.get("draft_language"), "profile.draft_language", 40) or "ko"
                raw_draft_text = _template_draft(record, product, customer, language, profile=profile)
                draft_body = f"""> 규칙 기반 초안 템플릿입니다. 실제 AI 생성 결과가 아니며 자동 발송되지 않습니다. 언어: `{language}`

{raw_draft_text}

> 검토 전 확인: 회사 동일성, 원문 최신성, 가설이 실제 상황과 맞는지, 실제 수신 대상, 과장 표현 여부."""
            draft_hash = hashlib.sha256(draft_body.encode("utf-8")).hexdigest()
            _machine_note(draft_path, f"""# Draft template — {record['company']}

- account_id: `{account_id}`
- 권장 액션: `{action}`
- draft_content_hash: `{draft_hash}`
- 전체 근거: {', '.join(f'[[Evidence/{item}]]' for item in evidence_ids)}
- 검토: [[Review/{account_id}]]

{draft_body}
""")
            _create_human(review_path, _review_template(account_id, record["company"], draft_hash))
            review_state, review_reason = _review(review_path, draft_hash)
            account_state = {"account_id": account_id, "company": record["company"],
                             "source_id": record["source_id"], "evidence_id": evidence_id,
                             "evidence_ids": evidence_ids, "diff": diff_status,
                             "action": action, "fit_score": fit_score, "urgency_score": urgency_score,
                             "draft_hash": draft_hash, "review": review_state, "review_reason": review_reason,
                             "stage": "review", "next_task": _next_task("review", review_state)}
            state["accounts"][account_id] = account_state
            result["accounts"].append(account_state)

            crm_signals = dict(score.get("signals") or {})
            if record["record_type"] == "job_posting":
                crm_signals.setdefault("roles", [record["title"]])
            elif record["record_type"] == "funding_signal":
                crm_signals.setdefault("funding", record["title"])
            crm_signals.setdefault("sources", [ev["url"]])
            crm_evidence = dict(score.get("evidence") or {record["record_type"]: ev["url"]})
            crm_rows.append({
                "company": record["company"],
                "action": action,
                "fit": fit_score,
                "urgency": urgency_score,
                "fit_missing": fit_missing,
                "urgency_missing": urgency_missing,
                "signals": crm_signals,
                "evidence": crm_evidence,
            })
            crm_drafts.append({
                "company": record["company"],
                "action": action,
                "draft": raw_draft_text,
                "evidence": crm_evidence,
            })

        result["completed"] = bool(result["accounts"]) and all(
            x.get("review") == "approved" for x in result["accounts"] if x.get("account_id")) and not any(
                x.get("stage") == "identity_blocked" for x in result["accounts"])
    # empty is a successful source observation, not a completed outbound workflow.
    result["outcome"] = ("completed" if result["completed"] else "empty" if envelope["status"] == "empty"
                         else "blocked" if envelope["status"] in {"blocked", "failed", "invalid_response"}
                         else "review_required")
    if sync_gtm and crm_rows:
        result["gtm_sync"] = _sync_gtm_crm(root, crm_rows, crm_drafts)
    inbox_path = root / f"Inbox/{run_id}-source.md"
    _assert_managed_path(root, inbox_path)
    _machine_note(inbox_path, _inbox_receipt(result))
    result["inbox_note"] = f"Inbox/{run_id}-source"
    state.setdefault("runs", {})[run_id] = result
    receipt = _run_receipt(result)
    receipt_path, state_path = root / f"Runs/{run_id}.md", root / STATE
    _assert_managed_path(root, receipt_path); _assert_managed_path(root, state_path)
    _machine_note(receipt_path, receipt)
    _atomic(state_path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _render_dashboard(root, state)
    return result


def _run_receipt(result: dict) -> str:
    diff = result.get("diff") or {}
    diff_line = f"- 변경 추적: 신규 `{diff.get('new', 0)}` · 변경 `{diff.get('changed', 0)}` · 동일 `{diff.get('unchanged', 0)}`"
    lines = [f"# Run — {result['run_id']}", "", f"- source: `{result['source']}`",
             f"- source_status: `{result['source_status']}`", f"- outcome: `{result['outcome']}`",
             diff_line,
             f"- input_digest: `{result['input_digest']}`", f"- Inbox: [[{result.get('inbox_note', '')}]]",
             "", "## 단계 결과", ""]
    if result["errors"]:
        lines += ["### Source errors", ""] + [f"- {e}" for e in result["errors"]] + [""]
    if not result["accounts"]:
        lines.append("- 처리된 account 없음. `empty`와 source 실패는 서로 다른 상태로 보존됩니다.")
    for item in result["accounts"]:
        if item.get("account_id"):
            aid = item["account_id"]
            badge = f"[{item.get('diff', 'new')}] {item.get('action', '')}".strip()
            lines.append(f"- ({badge}) [[Accounts/{aid}|{item['company']}]] → [[Evidence/{item['evidence_id']}|Evidence]] → "
                         f"[[Scores/{aid}|Score]] → [[Drafts/{aid}|Draft]] → [[Review/{aid}|Review]] "
                         f"— `{item['review']}`; 다음: {item['next_task']}")
        else:
            lines.append(f"- `{item['source_id']}` 회사 식별 보류 — 다음: {item['next_task']}")
    lines += ["", "자동 발송은 수행되지 않았습니다."]
    return "\n".join(lines)


def _inbox_receipt(result: dict) -> str:
    """Machine-owned staging note; the human Brief and Review notes remain untouched."""
    lines = [f"# Source intake — {result['run_id']}", "", f"- source: `{result['source']}`",
             f"- status: `{result['source_status']}`", f"- input_digest: `{result['input_digest']}`", ""]
    if result["errors"]:
        lines += ["## Source errors", ""] + [f"- {item}" for item in result["errors"]] + [""]
    lines += ["## Records and gate", ""]
    if not result["accounts"]:
        lines.append("- record 없음. empty와 source 실패 상태는 Runs receipt에서 구분합니다.")
    for item in result["accounts"]:
        if item.get("account_id"):
            lines.append(f"- `{item['source_id'] if 'source_id' in item else item['evidence_id']}` → "
                         f"[[Accounts/{item['account_id']}|{item['company']}]]")
        else:
            candidate = item.get("company_candidate") or "후보명 없음"
            lines.append(f"- `{item['source_id']}` · 후보 `{candidate}` · **차단:** {item['next_task']}")
    return "\n".join(lines)


def _render_dashboard(root: Path, state: dict) -> None:
    accounts = list(state.get("accounts", {}).values())
    runs = list(state.get("runs", {}).values())
    lines = ["# Hermes Outbound Dashboard", "", "[[Inbox/Brief|1. Inbox 브리프]] → 2. Accounts → 3. Evidence → "
             "4. Scores → 5. Drafts → 6. Review → 7. Runs", "",
             "> Core Obsidian 기능만 사용합니다. 초안은 자동 발송되지 않습니다.", "",
             f"- Accounts: {len(accounts)}", f"- Runs: {len(runs)}", "", "## 계정별 산출물과 다음 작업", ""]
    if not accounts:
        lines.append("- 아직 계정이 없습니다. `vault_flow.py run`으로 합성 fixture 또는 정규화 source envelope을 처리하세요.")
    for item in sorted(accounts, key=lambda x: (x.get("company", ""), x.get("account_id", ""))):
        aid = item["account_id"]
        lines.append(f"- [[Accounts/{aid}|{item['company']}]] · [[Evidence/{item['evidence_id']}|Evidence]] · "
                     f"[[Scores/{aid}|Score]] · [[Drafts/{aid}|Draft]] · [[Review/{aid}|Review]] "
                     f"— 상태 `{item['review']}` — **다음:** {item['next_task']}")
    lines += ["", "## Runs", ""]
    if not runs:
        lines.append("- 아직 실행 receipt가 없습니다.")
    for run in sorted(runs, key=lambda x: x["run_id"]):
        lines.append(f"- [[{run.get('inbox_note', 'Inbox/Brief')}|Inbox]] → [[Runs/{run['run_id']}|{run['run_id']}]] "
                     f"— source `{run['source_status']}` / outcome `{run['outcome']}`")
        for item in run.get("accounts", []):
            if item.get("stage") == "identity_blocked":
                lines.append(f"  - 후보 `{item.get('company_candidate') or '이름 없음'}` — **다음:** {item['next_task']}")
    dashboard = root / "Dashboard.md"
    _assert_managed_path(root, dashboard)
    _machine_note(dashboard, "\n".join(lines))


def status(vault: str | Path) -> dict:
    root = _vault(vault)
    state = _read_state(root)
    counts = {name: 0 for name in ("pending", "approved", "rejected", "invalidated")}
    accounts = []
    for item in state.get("accounts", {}).values():
        review_state, reason = _review(root / f"Review/{item['account_id']}.md", item["draft_hash"])
        counts[review_state] = counts.get(review_state, 0) + 1
        accounts.append({**item, "review": review_state, "review_reason": reason,
                         "next_task": _next_task("review", review_state)})
    return {"vault": str(root), "runs": len(state.get("runs", {})), "accounts": len(accounts),
            "reviews": counts, "items": sorted(accounts, key=lambda x: x["account_id"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes outbound Obsidian workflow runner")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("init", "status", "run"):
        command = sub.add_parser(name)
        command.add_argument("--vault", required=True)
        if name == "run":
            command.add_argument("--input", help="normalized source envelope JSON; 생략하면 합성 fixture")
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            root = init_vault(args.vault)
            print(f"볼트 초기화 완료: {root}")
        elif args.action == "run":
            result = run_flow(args.vault, args.input)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(status(args.vault), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
