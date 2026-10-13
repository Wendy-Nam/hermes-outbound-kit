"""Obsidian 볼트에 GTM 계정·초안 노트를 쓰는 공용 모듈(표준 라이브러리만).

볼트 안 위치: GTM/Accounts/<회사>.md, GTM/Drafts/<회사>.md, GTM/Pipeline.md
- 노트 머리말(Obsidian 속성)의 status는 사람이 Obsidian에서 바꾸는 값이다. 다시 채점해도 덮지 않는다.
- <!-- user-notes:start --> ~ <!-- user-notes:end --> 사이의 사람 메모는 보존한다.
- 이 모듈의 표식이 없는 같은 이름 파일은 덮어쓰지 않는다.

볼트 경로 결정 순서: --vault → OUTBOUND_VAULT → $HERMES_HOME/outbound-profile.json의 vault_path
(vault_mode가 none이 아닐 때) → $HERMES_HOME/vault(키트 설치 때 생성) → 없으면 None.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

MARK = "<!-- hermes-outbound:gtm:v1 -->"
USER_START = "<!-- user-notes:start -->"
USER_END = "<!-- user-notes:end -->"
STAGES = ["발굴", "접촉", "응답", "미팅", "제안", "계약", "보류", "실패"]


def resolve_vault(explicit=None):
    if explicit:
        return Path(explicit).expanduser().absolute()
    if os.environ.get("OUTBOUND_VAULT"):
        return Path(os.environ["OUTBOUND_VAULT"]).expanduser().absolute()
    home = os.environ.get("HERMES_HOME")
    if not home:
        return None
    try:
        profile = json.loads(Path(home, "outbound-profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        profile = {}
    if profile.get("vault_path") and profile.get("vault_mode", "none") != "none":
        path = Path(profile["vault_path"]).expanduser()
        return (path if path.is_absolute() else Path.home() / path).absolute()
    default = Path(home, "vault")
    return default.absolute() if default.is_dir() else None


def slug(name):
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "-", (name or "").strip()).strip("-")
    return text[:60] or "unknown"


def key(name):
    return re.sub(r"[^가-힣a-z0-9]", "", (name or "").lower())


def _atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise SystemExit(f"❌ 링크 경로에는 쓰지 않습니다: {path}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _parse_value(raw):
    raw = raw.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw.strip("'\"")               # Obsidian 속성 편집기는 따옴표 없이 쓴다


def read_note(path: Path):
    """(frontmatter dict, user notes text, machine-owned 여부). 없으면 ({}, "", True)."""
    if not path.exists():
        return {}, "", True
    text = path.read_text(encoding="utf-8")
    meta = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line and not line.startswith(" "):
                    k, _, v = line.partition(":")
                    meta[k.strip()] = _parse_value(v)
    start, stop = text.find(USER_START), text.find(USER_END)
    notes = text[start + len(USER_START):stop].strip("\n") if start != -1 and stop > start else ""
    return meta, notes, MARK in text


def write_note(path: Path, meta: dict, body: str, notes: str):
    head = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
    _atomic(path, f"---\n{head}\n---\n{MARK}\n{body.rstrip()}\n\n{USER_START}\n{notes}\n{USER_END}\n")


class VaultLedger:
    """account_crm.py의 JSON 장부와 같은 dict 인터페이스를 볼트 노트로 제공한다."""

    def __init__(self, vault: Path):
        self.root = vault / "GTM"
        self.accounts = self.root / "Accounts"

    def load(self):
        led = {}
        if self.accounts.is_dir():
            for path in sorted(self.accounts.glob("*.md")):
                meta, notes, owned = read_note(path)
                if not owned or not meta.get("company"):
                    continue
                rec = {k: v for k, v in meta.items() if k not in ("tags", "updated")}
                rec["notes"] = [l[2:] for l in notes.splitlines() if l.startswith("- ")]
                rec["_notes_raw"] = notes            # 사람이 쓴 자유 형식 메모도 그대로 보존
                rec["_path"] = str(path)
                led[key(meta["company"])] = rec
        return led

    def save(self, led):
        for rec in led.values():
            path = Path(rec.get("_path") or self.accounts / f"{slug(rec['company'])}.md")
            if path.exists() and not read_note(path)[2]:
                print(f"⚠️  사람이 만든 같은 이름 노트가 있어 건너뜁니다: {path}")
                continue
            meta = {"company": rec["company"], "status": rec.get("status") or "발굴",
                    "action": rec.get("action"), "fit": rec.get("fit"), "urgency": rec.get("urgency"),
                    "contacted_at": rec.get("contacted_at") or "",
                    "discovered": rec.get("discovered") or date.today().isoformat(),
                    "updated": date.today().isoformat(), "tags": ["gtm-account"]}
            notes = rec.get("_notes_raw")
            if notes is None:
                notes = "\n".join(f"- {n}" for n in rec.get("notes") or [])
            write_note(path, meta, account_body(rec), notes)
            rec["_path"] = str(path)
        self.write_pipeline(led)

    def write_pipeline(self, led):
        path = self.root / "Pipeline.md"
        if path.exists() and not read_note(path)[2]:
            return
        lines = ["# GTM 파이프라인", "",
                 "상태는 각 계정 노트의 `status` 속성을 Obsidian에서 바꾸면 됩니다. 다시 채점해도 유지됩니다.", ""]
        recent = sorted((r for r in led.values() if str(r.get("discovered") or date.today().isoformat())
                         >= (date.today() - timedelta(days=7)).isoformat()), key=lambda r: r["company"])
        if recent:
            lines.append(f"## 최근 7일 새로 발굴 ({len(recent)})")
            lines += [f"- [[GTM/Accounts/{slug(r['company'])}|{r['company']}]] · {r.get('action') or ''}" for r in recent]
            lines.append("")
        for stage in STAGES:
            recs = [r for r in led.values() if (r.get("status") or "발굴") == stage]
            if not recs:
                continue
            lines.append(f"## {stage} ({len(recs)})")
            for r in sorted(recs, key=lambda r: -((r.get("fit") or 0) + (r.get("urgency") or 0))):
                fit = "—" if r.get("fit") is None else r["fit"]
                urg = "—" if r.get("urgency") is None else r["urgency"]
                lines.append(f"- [[GTM/Accounts/{slug(r['company'])}|{r['company']}]] · {r.get('action') or ''}"
                             f" · 적합 {fit} · 긴급 {urg}")
            lines.append("")
        write_note(path, {"tags": ["gtm-pipeline"], "updated": date.today().isoformat()},
                   "\n".join(lines), read_note(path)[1])


def account_body(rec):
    sig = rec.get("signals") or {}
    missing = (rec.get("fit_missing") or []) + (rec.get("urgency_missing") or [])
    lines = [f"# {rec['company']}", "",
             "## 판정 (채점 때마다 자동 갱신)",
             f"- 판정: {rec.get('action') or '미채점'}",
             f"- 적합도: {'—' if rec.get('fit') is None else rec['fit']} · 긴급도: "
             f"{'—' if rec.get('urgency') is None else rec['urgency']}"]
    if missing:
        lines.append(f"- 아직 모르는 항목: {', '.join(missing)} → `prospect-research`로 근거를 채우고 다시 채점")
    lines += ["", "## 신호"]
    if sig.get("funding"):
        lines.append(f"- 투자 유치: {sig['funding']}")
    if sig.get("roles"):
        lines.append(f"- 채용 중인 직무: {', '.join(sig['roles'][:10])}")
    if not (sig.get("funding") or sig.get("roles")):
        lines.append("- (수집된 신호 없음)")
    lines += ["", "## 근거"]
    evidence = rec.get("evidence") or {}
    lines += [f"- {k}: {v}" for k, v in evidence.items()] or ["- (근거 URL 없음)"]
    for url in sig.get("sources") or []:
        if url not in evidence.values():
            lines.append(f"- 출처: {url}")
    lines += ["", f"초안: [[GTM/Drafts/{slug(rec['company'])}]]", "", "## 사람 메모"]
    return "\n".join(lines)


def write_draft(vault: Path, company: str, action: str, draft: str, evidence: dict):
    path = vault / "GTM" / "Drafts" / f"{slug(company)}.md"
    meta, notes, owned = read_note(path)
    if not owned:
        print(f"⚠️  사람이 만든 같은 이름 노트가 있어 건너뜁니다: {path}")
        return None
    body = [f"# 초안 — {company}", "",
            "> 규칙 기반 초안입니다. 근거를 열어 확인하고 사람이 직접 발송합니다. 자동 발송되지 않습니다.", "",
            draft, "", "## 근거"]
    body += [f"- {k}: {v}" for k, v in (evidence or {}).items()] or ["- (근거 URL 없음)"]
    body += ["", f"계정: [[GTM/Accounts/{slug(company)}]]", "", "## 사람 메모"]
    write_note(path, {"company": company, "action": action, "review": meta.get("review", "pending"),
                      "updated": date.today().isoformat(), "tags": ["gtm-draft"]}, "\n".join(body), notes)
    return path
