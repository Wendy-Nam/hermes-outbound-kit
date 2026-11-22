#!/usr/bin/env python3
"""Personal Sent-Mailbox Email Structure & Tone-and-Manner Analyzer.

Analyzes a sales rep's own previously sent emails (from local .mbox, .eml/.emlx
folders, JSON/CSV/TXT exports, or explicit read-only IMAP) to extract writing
structure, formality, greeting/closing/CTA patterns, and signature style.

Privacy contract:
- Never modifies or deletes mailbox items (IMAP uses readonly=True).
- Never saves raw customer emails, recipient addresses, or phone numbers into
  writing-style.json or setup.json; all extracted templates are PII-redacted.
"""
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
from collections import Counter
import csv
import email
from email import policy
from email.header import decode_header
import getpass
import imaplib
import json
import mailbox
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

import kit
import paths


MAX_MAIL_FILES = 200
MAX_FILE_BYTES = 50 * 1024 * 1024

RE_EMAIL_ADDR = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_PHONE = re.compile(r"(?:\+?82[- .]?)?0\d{1,2}[- .]?\d{3,4}[- .]?\d{4}|\+\d(?:[ .()-]?\d){8,14}")
RE_URL = re.compile(r"https?://\S+", re.I)

FORMAL_ENDINGS = re.compile(r"(?:습니다|습니까|십시오|드립니다|바랍니다|감사드립니다|말씀드립니다)[.!?]?(?:\s|$)")
POLITE_ENDINGS = re.compile(r"(?:해요|세요|예요|에요|까요|나요|드려요|좋아요|괜찮아요|있어요|없어요|합니다요)[.!?]?(?:\s|$)")
WARM_MARKERS = re.compile(r"!|😊|🙂|반갑습니다|편하게|가볍게|부담\s*없이|좋은\s*하루|편안한\s*하루")
BULLET_LINE = re.compile(r"^\s*(?:[-*•·▪▫]|\d+[.)])\s+")
REPLY_PREFIX = re.compile(r"^\s*(?:re|fwd|fw|답장|전달)\s*[:：]", re.I)
QUOTED_REPLY_SPLIT = re.compile(
    r"(?m)^(?:On\s.+wrote:|From:\s|보낸\s*사람:|-----Original Message-----|>{2,}|_{5,}|-{5,}\s*Original)",
    re.I,
)
CTA_CUES = re.compile(
    r"(?:미팅|통화|이야기|나눠|시간|일정|데모|자료|공유|회신|답장|여쭙|가능하실|괜찮으실|어떠실|확인해\s*볼|"
    r"call|chat|meeting|15[- ]?min|demo|reply|let me know|worth a)",
    re.I,
)
GREETING_CUES = re.compile(r"^(?:안녕하십니까|안녕하세요|반갑습니다|hello|hi|dear)\b", re.I)
CLOSING_CUES = re.compile(
    r"^(?:감사합니다|감사드립니다|고맙습니다|편안한\s*하루|좋은\s*하루|회신\s*기다리|건강\s*유의|"
    r"best(?:\s+regards)?|kind\s+regards|regards|thanks|thank\s+you|sincerely|cheers)\b",
    re.I,
)
TRANSITION_PHRASES = (
    "혹시", "간단히", "부담 없이", "편하게", "참고로", "관련하여", "검토 중이시라면",
    "짧게", "공유드릴 수", "여쭙고 싶", "말씀해 주시면", "도움이 될", "사례를",
    "우선", "결론부터", "요약하자면",
)
SENT_FOLDER_CANDIDATES = (
    '"[Gmail]/Sent Mail"',
    '"[Gmail]/보낸편지함"',
    "Sent",
    '"Sent Messages"',
    '"Sent Items"',
    "INBOX.Sent",
    '"보낸편지함"',
    '"보낸메일함"',
)


def _decode_mime_header(value: Any) -> str:
    if not value:
        return ""
    parts = []
    for chunk, charset in decode_header(str(value)):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _html_to_text(raw_html: str) -> str:
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", raw_html, flags=re.I | re.S)
    text = re.sub(r"<(?:br|p|div|li|tr)\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    import html as _html
    text = _html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.splitlines()]
    return "\n".join(l for l in lines if l)


def _extract_email_body(msg: email.message.Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ctype == "text/plain":
                plain_parts.append(decoded)
            elif ctype == "text/html":
                html_parts.append(decoded)
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if (msg.get_content_type() or "").lower() == "text/html":
                html_parts.append(decoded)
            else:
                plain_parts.append(decoded)
        else:
            raw_str = str(msg.get_payload() or "")
            plain_parts.append(raw_str)

    body = "\n".join(plain_parts).strip() if plain_parts else _html_to_text("\n".join(html_parts))
    # Remove quoted thread replies so we only measure the sales rep's own writing
    body = QUOTED_REPLY_SPLIT.split(body, maxsplit=1)[0]
    lines = [l.rstrip() for l in body.replace("\r\n", "\n").replace("\r", "\n").splitlines() if not l.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def redact_pii(text: str) -> str:
    """Strip recipient emails, phone numbers, and query-bearing URLs from extracted templates."""
    cleaned = RE_EMAIL_ADDR.sub("[이메일]", text)
    cleaned = RE_PHONE.sub("[연락처]", cleaned)
    cleaned = RE_URL.sub("[링크]", cleaned)
    # Anonymize recipient name/company in greetings like "안녕하세요, OO기업 김철수 팀장님"
    cleaned = re.sub(
        r"(안녕하(?:세요|십니까)[,!\s]+)(?:[가-힣A-Za-z0-9()주식회사㈜&._-]{2,25}\s+){0,2}([가-힣A-Za-z]{2,12}\s*(?:대표|팀장|매니저|담당자|실장|본부장|이사|과장|차장|부장|님)님?)",
        r"\1{회사} {담당자}님",
        cleaned,
    )
    cleaned = re.sub(r"\b(Hello|Hi|Dear)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?([,!])", r"\1 {name}\2", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Local Mailbox Discovery & Loaders
# ---------------------------------------------------------------------------

def discover_local_mailboxes() -> list[dict[str, str]]:
    """Read-only discovery of common local desktop Sent mailboxes & exported mail files."""
    home = Path.home()
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, path: Path, client: str) -> None:
        resolved = str(path.expanduser().absolute())
        if resolved not in seen and not path.is_symlink():
            seen.add(resolved)
            found.append({"client": client, "kind": kind, "path": resolved})

    # Thunderbird Sent mbox
    for tb_base in (home / ".thunderbird", home / "Library/Thunderbird/Profiles",
                    Path(os.environ.get("APPDATA", "")) / "Thunderbird/Profiles"):
        if tb_base.is_dir():
            for sent in tb_base.glob("**/Sent"):
                if sent.is_file() and sent.stat().st_size > 0:
                    add("mbox", sent, "Thunderbird")

    # Apple Mail Sent folders
    apple_mail = home / "Library/Mail"
    if apple_mail.is_dir():
        for mbox_dir in apple_mail.glob("V*/*/Sent*.mbox"):
            if mbox_dir.is_dir():
                add("emlx_dir", mbox_dir, "Apple Mail")

    # Common user export locations (Gmail Takeout / Outlook exports)
    for folder in (home / "Downloads", home / "Documents"):
        if not folder.is_dir():
            continue
        for mbox_file in list(folder.glob("*.mbox"))[:10]:
            if mbox_file.is_file():
                add("mbox", mbox_file, "Exported MBOX")
        for sent_dir in list(folder.glob("*[Ss]ent*"))[:5]:
            if sent_dir.is_dir() and any(sent_dir.glob("*.eml")):
                add("eml_dir", sent_dir, "Exported EML Folder")

    return found


def load_mbox_messages(path: str | Path, *, limit: int = 50, skip_replies: bool = True) -> list[dict[str, str]]:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"MBOX 파일을 찾을 수 없습니다: {path}")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("MBOX 파일이 50MiB 안전 한도를 초과했습니다. 최근 발신 메일만 별도 export해 주세요.")
    box = mailbox.mbox(str(target), create=False)
    messages: list[dict[str, str]] = []
    try:
        items = list(box)
        # Prefer most recent messages (usually at end of mbox)
        for msg in reversed(items):
            subj = _decode_mime_header(msg.get("Subject"))
            if skip_replies and REPLY_PREFIX.match(subj):
                continue
            body = _extract_email_body(msg)
            if len(body) < 25:
                continue
            messages.append({
                "subject": subj,
                "body": body,
                "date": str(msg.get("Date") or ""),
            })
            if len(messages) >= limit:
                break
    finally:
        box.close()
    return messages


def load_eml_messages(path: str | Path, *, limit: int = 50, skip_replies: bool = True) -> list[dict[str, str]]:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.exists():
        raise ValueError(f"EML 경로를 찾을 수 없습니다: {path}")
    files: list[Path] = []
    if target.is_file():
        files = [target]
    else:
        for ext in ("*.eml", "*.emlx"):
            files.extend(target.rglob(ext))
        files = [f for f in files if f.is_file() and not f.is_symlink()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    messages: list[dict[str, str]] = []
    for f in files[:MAX_MAIL_FILES]:
        raw = f.read_bytes()
        # Apple .emlx files start with a byte-count line before RFC-822 headers
        if f.suffix.lower() == ".emlx":
            nl = raw.find(b"\n")
            if nl != -1 and raw[:nl].strip().isdigit():
                raw = raw[nl + 1:]
        msg = email.message_from_bytes(raw, policy=policy.default)
        subj = _decode_mime_header(msg.get("Subject"))
        if skip_replies and REPLY_PREFIX.match(subj):
            continue
        body = _extract_email_body(msg)
        if len(body) < 25:
            continue
        messages.append({"subject": subj, "body": body, "date": str(msg.get("Date") or "")})
        if len(messages) >= limit:
            break
    return messages


def load_text_or_json_messages(path: str | Path, *, limit: int = 50, skip_replies: bool = True) -> list[dict[str, str]]:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"메일 샘플 파일을 찾을 수 없습니다: {path}")
    raw = target.read_text(encoding="utf-8-sig")
    suffix = target.suffix.lower()
    messages: list[dict[str, str]] = []
    if suffix == ".json":
        data = json.loads(raw)
        rows = data.get("emails", data.get("messages", [])) if isinstance(data, dict) else data
        for r in rows[:limit * 2]:
            if not isinstance(r, dict):
                continue
            subj = str(r.get("subject") or r.get("title") or "").strip()
            body = str(r.get("body") or r.get("text") or r.get("content") or "").strip()
            if skip_replies and REPLY_PREFIX.match(subj):
                continue
            if len(body) >= 20:
                messages.append({"subject": subj, "body": body, "date": str(r.get("date") or "")})
    elif suffix == ".csv":
        for r in csv.DictReader(raw.splitlines()):
            lowered = {str(k).strip().lower(): v for k, v in r.items()}
            subj = (lowered.get("subject") or lowered.get("제목") or "").strip()
            body = (lowered.get("body") or lowered.get("본문") or lowered.get("content") or "").strip()
            if skip_replies and REPLY_PREFIX.match(subj):
                continue
            if len(body) >= 20:
                messages.append({"subject": subj, "body": body, "date": (lowered.get("date") or "").strip()})
    else:
        # Split markdown/txt samples separated by --- or ===
        chunks = [c.strip() for c in re.split(r"(?m)^(?:---|===)\s*$", raw) if c.strip()]
        for chunk in chunks:
            lines = chunk.splitlines()
            subj = ""
            body_lines = lines
            if lines and re.match(r"^(?:제목|subject)\s*[:：]", lines[0], re.I):
                subj = re.sub(r"^(?:제목|subject)\s*[:：]\s*", "", lines[0], flags=re.I).strip()
                body_lines = lines[1:]
            body = "\n".join(body_lines).strip()
            if len(body) >= 20:
                messages.append({"subject": subj, "body": body, "date": ""})
    return messages[:limit]


def fetch_imap_sent_messages(
    host: str,
    *,
    port: int = 993,
    user: str = "",
    password: str = "",
    mailbox_name: str = "",
    limit: int = 30,
    skip_replies: bool = True,
    home: str | Path | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Read-only IMAP fetch of recent Sent emails. Credentials never stored in config."""
    import sources
    user = user or sources._read_env_key("IMAP_USER", home)
    password = password or sources._read_env_key("IMAP_APP_PASSWORD", home)
    if not user:
        if not sys.stdin.isatty():
            raise ValueError("IMAP_USER가 필요합니다. 터미널에서 직접 실행하거나 $HERMES_HOME/.env에 설정하세요.")
        user = input(f"IMAP 이메일 주소 ({host}): ").strip()
    if not password:
        if not sys.stdin.isatty():
            raise ValueError("IMAP 앱 비밀번호는 터미널 비공개 입력 또는 $HERMES_HOME/.env(IMAP_APP_PASSWORD)에서만 받습니다.")
        password = getpass.getpass("IMAP 앱 비밀번호 (화면에 표시되지 않음): ")

    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(user, password)
        chosen = ""
        candidates = [mailbox_name] if mailbox_name else list(SENT_FOLDER_CANDIDATES)
        for cand in candidates:
            if not cand:
                continue
            status, _ = conn.select(cand, readonly=True)
            if status == "OK":
                chosen = cand
                break
        if not chosen:
            raise ValueError("발신함(Sent) 폴더를 찾지 못했습니다. --imap-mailbox로 폴더 이름을 직접 지정하세요.")
        status, data = conn.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return chosen, []
        ids = data[0].split()
        recent_ids = list(reversed(ids))[:min(limit * 3, 150)]
        messages: list[dict[str, str]] = []
        for msg_id in recent_ids:
            st, fetched = conn.fetch(msg_id, "(RFC822)")
            if st != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            msg = email.message_from_bytes(fetched[0][1], policy=policy.default)
            subj = _decode_mime_header(msg.get("Subject"))
            if skip_replies and REPLY_PREFIX.match(subj):
                continue
            body = _extract_email_body(msg)
            if len(body) < 25:
                continue
            messages.append({"subject": subj, "body": body, "date": str(msg.get("Date") or "")})
            if len(messages) >= limit:
                break
        return chosen, messages
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Email Structure & Tone-and-Manner Analyzer
# ---------------------------------------------------------------------------

def _split_paragraphs(body: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n+", body.strip()) if p.strip()]
    if len(paras) == 1:
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        if len(lines) >= 3:
            return lines
    return paras


def _extract_signature_block(paras: list[str]) -> tuple[list[str], str]:
    """Separate trailing signature lines from the main body."""
    if len(paras) < 2:
        return paras, ""
    tail = paras[-1]
    lines = [l.strip() for l in tail.splitlines() if l.strip()]
    # Heuristic: short final block containing title/company/contact/closing
    if len(lines) <= 6 and (
        any(RE_EMAIL_ADDR.search(l) or RE_PHONE.search(l) or "드림" in l or "올림" in l or "·" in l or "|" in l for l in lines)
        or (len(tail) <= 120 and CLOSING_CUES.search(lines[0]))
    ):
        return paras[:-1], tail
    return paras, ""


def _infer_sender_hints(signatures: list[str]) -> dict[str, str]:
    """Infer consistent sender_name / sender_role / sender_company from repeated signature blocks (no phone PII)."""
    names: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    role_rx = re.compile(r"(대표|이사|본부장|실장|팀장|매니저|리드|프로|책임|선임|담당자|AE|SDR|BDR|BD|VP|Director|Manager|Lead)", re.I)
    for sig in signatures:
        for line in sig.splitlines():
            clean = RE_EMAIL_ADDR.sub("", RE_PHONE.sub("", line)).strip(" |·/-")
            if not clean or CLOSING_CUES.search(clean):
                continue
            m_role = role_rx.search(clean)
            if m_role:
                roles[m_role.group(1)] += 1
            m_name = re.search(r"([가-힣]{2,4})\s*(?:드림|올림|배상|팀장|매니저|대표|이사|프로|AE|SDR|BD)", clean)
            if m_name:
                names[m_name.group(1)] += 1
    out: dict[str, str] = {}
    if names:
        out["sender_name_hint"] = names.most_common(1)[0][0]
    if roles:
        out["sender_role_hint"] = roles.most_common(1)[0][0]
    return out


def analyze_sent_emails(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Extract anonymized writing style, structure, and tone profile from sent emails."""
    valid = [m for m in messages if isinstance(m, dict) and len((m.get("body") or "").strip()) >= 20]
    if not valid:
        raise ValueError("분석할 발신 메일이 없습니다(본문 20자 이상 메일 필요).")

    formal_hits = polite_hits = warm_hits = bullet_emails = question_emails = 0
    bracket_subjects = question_subjects = 0
    subject_lengths: list[int] = []
    body_lengths: list[int] = []
    para_counts: list[int] = []
    sent_counts: list[int] = []
    avg_sent_lengths: list[float] = []
    ko_chars = en_chars = 0

    greetings: Counter[str] = Counter()
    closings: Counter[str] = Counter()
    cta_examples: list[str] = []
    signatures: list[str] = []
    phrase_counts: Counter[str] = Counter()
    subject_patterns: Counter[str] = Counter()

    for m in valid:
        subj = (m.get("subject") or "").strip()
        body = (m.get("body") or "").strip()
        ko_chars += len(re.findall(r"[가-힣]", body))
        en_chars += len(re.findall(r"[A-Za-z]", body))

        if subj:
            subject_lengths.append(len(subj))
            if re.match(r"^\[[^\]]+\]", subj):
                bracket_subjects += 1
                subject_patterns["[말머리] 접두어 사용"] += 1
            if "?" in subj:
                question_subjects += 1
                subject_patterns["질문형 제목"] += 1
            if re.search(r"문의|여쭙", subj):
                subject_patterns["문의형 제목 (~관련 문의)"] += 1
            elif re.search(r"제안|소개", subj):
                subject_patterns["제안형 제목 (~제안/소개)"] += 1
            elif re.search(r"공유|안내|참고", subj):
                subject_patterns["공유/안내형 제목"] += 1

        paras = _split_paragraphs(body)
        core_paras, sig_block = _extract_signature_block(paras)
        if sig_block:
            signatures.append(sig_block)
            for line in sig_block.splitlines():
                if CLOSING_CUES.search(line.strip()):
                    closings[redact_pii(line.strip())[:80]] += 1

        core_text = "\n\n".join(core_paras)
        body_lengths.append(len(core_text))
        para_counts.append(len(core_paras))

        # Greeting & closing detection
        if core_paras:
            first_line = core_paras[0].splitlines()[0].strip()
            if GREETING_CUES.search(first_line):
                greetings[redact_pii(first_line)[:100]] += 1
            last_line = core_paras[-1].splitlines()[-1].strip()
            if CLOSING_CUES.search(last_line):
                closings[redact_pii(last_line)[:80]] += 1

        # Sentences & tone markers
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", core_text) if len(s.strip()) >= 5]
        if sentences:
            sent_counts.append(len(sentences))
            avg_sent_lengths.append(sum(len(s) for s in sentences) / len(sentences))

        formal_hits += len(FORMAL_ENDINGS.findall(core_text))
        polite_hits += len(POLITE_ENDINGS.findall(core_text))
        warm_hits += len(WARM_MARKERS.findall(core_text))
        if any(BULLET_LINE.match(line) for line in core_text.splitlines()):
            bullet_emails += 1
        if "?" in core_text:
            question_emails += 1

        # Extract CTA sentences from second half of email
        tail_sentences = sentences[max(0, len(sentences) // 2):]
        for sent in reversed(tail_sentences):
            if ("?" in sent or CTA_CUES.search(sent)) and 12 <= len(sent) <= 180 and not GREETING_CUES.search(sent):
                redacted_cta = redact_pii(sent)
                if redacted_cta and redacted_cta not in cta_examples:
                    cta_examples.append(redacted_cta)
                break

        for phrase in TRANSITION_PHRASES:
            if phrase in core_text:
                phrase_counts[phrase] += 1

    n = len(valid)
    avg_body = round(sum(body_lengths) / n)
    avg_paras = round(sum(para_counts) / n, 1)
    avg_sents = round(sum(sent_counts) / max(1, len(sent_counts)), 1)
    avg_sent_len = round(sum(avg_sent_lengths) / max(1, len(avg_sent_lengths)), 1)
    avg_subj = round(sum(subject_lengths) / len(subject_lengths)) if subject_lengths else 0
    bullet_rate = round(bullet_emails / n, 2)
    question_rate = round(question_emails / n, 2)

    total_endings = formal_hits + polite_hits
    formal_ratio = round(formal_hits / total_endings, 2) if total_endings else 0.5
    polite_ratio = round(polite_hits / total_endings, 2) if total_endings else 0.5

    # Classify tone into kit's 4 canonical outreach_tone values
    if avg_body <= 240 and avg_sents <= 4.5:
        detected_tone = "concise"
    elif warm_hits / n >= 0.8 or polite_ratio >= 0.65:
        detected_tone = "friendly"
    elif formal_ratio >= 0.72 and warm_hits / n < 0.5:
        detected_tone = "formal"
    else:
        detected_tone = "consultative"

    language = "en" if en_chars > ko_chars * 2 else "ko"
    top_greeting = greetings.most_common(1)[0][0] if greetings else ""
    top_closing = closings.most_common(1)[0][0] if closings else ""
    top_cta = cta_examples[0] if cta_examples else ""
    top_phrases = [p for p, _ in phrase_counts.most_common(8)]
    sender_hints = _infer_sender_hints(signatures)

    # Human-readable prompt guidance for Hermes LLM & template customization
    prompt_rules: list[str] = []
    speech_label = (
        "하십시오체(-습니다/-드립니다) 위주의 정중한 격식체" if formal_ratio >= 0.7
        else "해요체(-해요/-세요) 위주의 부드러운 존댓말" if polite_ratio >= 0.6
        else "하십시오체와 해요체를 자연스럽게 섞은 비즈니스 문체"
    )
    prompt_rules.append(f"문체: {speech_label} (추천 tone={detected_tone})")
    prompt_rules.append(f"분량 리듬: 평균 {avg_paras}개 문단, 약 {avg_sents}문장(본문 약 {avg_body}자, 문장당 평균 {avg_sent_len}자)")
    if bullet_rate >= 0.35:
        prompt_rules.append("핵심 제안 포인트는 불릿 리스트(-) 2~3개로 간결하게 정리하는 스타일을 선호함")
    else:
        prompt_rules.append("불릿보다는 자연스러운 짧은 문단 서술형을 선호함")
    if bracket_subjects / max(1, len(subject_lengths)) >= 0.4:
        prompt_rules.append("제목 앞에 [키워드/회사명] 말머리를 자주 사용함")
    if top_greeting:
        prompt_rules.append(f"선호 인사말 패턴: {top_greeting}")
    if top_closing:
        prompt_rules.append(f"선호 맺음말 패턴: {top_closing}")
    if top_cta:
        prompt_rules.append(f"선호 CTA 스타일: {top_cta}")
    if top_phrases:
        prompt_rules.append("자주 쓰는 연결 표현: " + ", ".join(top_phrases[:6]))

    return {
        "schema_version": "hermes_outbound_writing_style/v1",
        "emails_analyzed": n,
        "language": language,
        "detected_tone": detected_tone,
        "speech_level": {
            "formal_ratio": formal_ratio,
            "polite_ratio": polite_ratio,
            "warmth_per_email": round(warm_hits / n, 2),
            "summary": speech_label,
        },
        "structure": {
            "avg_subject_chars": avg_subj,
            "avg_body_chars": avg_body,
            "avg_paragraphs": avg_paras,
            "avg_sentences": avg_sents,
            "avg_sentence_chars": avg_sent_len,
            "bullet_usage_rate": bullet_rate,
            "question_rate": question_rate,
            "subject_patterns": [k for k, _ in subject_patterns.most_common(4)],
        },
        "patterns": {
            "preferred_greeting": top_greeting,
            "greeting_variants": [g for g, _ in greetings.most_common(3)],
            "preferred_closing": top_closing,
            "closing_variants": [c for c, _ in closings.most_common(3)],
            "preferred_cta": top_cta,
            "cta_variants": cta_examples[:4],
            "favorite_phrases": top_phrases,
        },
        "sender_hints": sender_hints,
        "prompt_guidance": prompt_rules,
        "privacy": {
            "raw_emails_stored": False,
            "pii_redacted": True,
        },
    }


def render_style_markdown(style: dict[str, Any]) -> str:
    st = style["structure"]
    sp = style["speech_level"]
    pat = style["patterns"]
    lines = [
        "# 개인 발신메일함 문체 · 구조 분석 리포트",
        "",
        f"> 분석 메일 수: **{style['emails_analyzed']}건** · 고객 이메일/연락처 등 개인정보는 저장하지 않고 익명화된 스타일 패턴만 추출했습니다.",
        "",
        "## 1. 톤앤매너 & 화법",
        f"- **감지된 추천 톤 (`outreach_tone`)**: `{style['detected_tone']}`",
        f"- **화법 분포**: {sp['summary']} (하십시오체 {int(sp['formal_ratio']*100)}% / 해요체 {int(sp['polite_ratio']*100)}%)",
        f"- **언어**: `{style['language']}`",
        "",
        "## 2. 메일 구조 & 분량 리듬",
        f"- **제목 평균 길이**: {st['avg_subject_chars']}자 (패턴: {', '.join(st['subject_patterns']) or '일반형'})",
        f"- **본문 평균 분량**: {st['avg_body_chars']}자 · 평균 {st['avg_paragraphs']}문단 · 평균 {st['avg_sentences']}문장 (문장당 {st['avg_sentence_chars']}자)",
        f"- **불릿 리스트 사용률**: {int(st['bullet_usage_rate']*100)}% · **질문형 문장 포함률**: {int(st['question_rate']*100)}%",
        "",
        "## 3. 자주 쓰는 인사 · 맺음 · CTA 패턴 (익명화됨)",
        f"- **인사말**: {pat['preferred_greeting'] or '미감지'}",
        f"- **맺음말**: {pat['preferred_closing'] or '미감지'}",
        f"- **CTA 패턴**: {pat['preferred_cta'] or '미감지'}",
        f"- **자주 쓰는 연결 표현**: {', '.join(pat['favorite_phrases']) or '미감지'}",
        "",
        "## 4. 초안 생성 프롬프트 반영 규칙",
    ]
    lines += [f"- {rule}" for rule in style["prompt_guidance"]]
    if style.get("jev_calibration"):
        jc = style["jev_calibration"]
        lines += [
            "",
            "## 5. Jev 톤 보정 결과 (선택 옵션)",
            f"- **Jev 감지 톤**: `{jc.get('tone')}` (신뢰도 {jc.get('tone_confidence')})",
            f"- **불릿 선호 확률**: {jc.get('uses_bullets_prob')} · **CTA 저압박 점수**: {jc.get('cta_softness_score')}/100",
        ]
    lines.append("")
    return "\n".join(lines)


def calibrate_style_with_jev(
    style: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    home: str | Path | None = None,
    opener=None,
) -> dict[str, Any]:
    """Optionally refine detected_tone using Jev on strictly PII-redacted excerpts."""
    try:
        import jev_client
        api_key = jev_client.resolve_api_key(home)
        if not api_key:
            return style
        redacted_samples = [
            {
                "subject": redact_pii((m.get("subject") or "")[:120]),
                "body": redact_pii((m.get("body") or "")[:700]),
            }
            for m in messages[:8]
            if isinstance(m, dict) and (m.get("body") or "").strip()
        ]
        if not redacted_samples:
            return style
        cal = jev_client.classify_email_style_with_jev(redacted_samples, api_key=api_key, opener=opener)
        style["jev_calibration"] = cal
        if cal.get("tone") in ("formal", "consultative", "concise", "friendly") and cal.get("tone_confidence", 0) >= 0.65:
            style["detected_tone"] = cal["tone"]
            style["prompt_guidance"].append(
                f"Jev 톤 보정: {cal['tone']} (신뢰도 {cal['tone_confidence']}, 저압박 CTA {cal.get('cta_softness_score', 0)}/100)"
            )
    except Exception as exc:
        style["jev_warning"] = f"Jev 톤 보정 건너뜀(로컬 분석 사용): {exc}"
    return style


def save_style_to_home(style: dict[str, Any], home: str | Path, config_path: str | Path | None = None) -> dict[str, str]:
    """Save anonymized writing-style.json to $HERMES_HOME and optionally apply tone/CTA to setup.json."""
    home_path = Path(home).expanduser().absolute()
    if any(p.is_symlink() for p in (home_path, *home_path.parents)):
        raise ValueError("설치 홈 경로에 심볼릭 링크가 있습니다.")
    home_path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(home_path, 0o700)

    style_path = home_path / "writing-style.json"
    fd, tmp = tempfile.mkstemp(prefix=".style-", dir=home_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(style, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, style_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    saved = {"writing_style": str(style_path)}
    if config_path:
        cfg_p = Path(config_path).expanduser().absolute()
        if cfg_p.is_file() and not cfg_p.is_symlink():
            cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
            cfg["outreach_tone"] = style["detected_tone"]
            if style["patterns"].get("preferred_cta") and not cfg.get("sender_cta"):
                cfg["sender_cta"] = style["patterns"]["preferred_cta"][:500]
            if style["sender_hints"].get("sender_name_hint") and not cfg.get("sender_name"):
                cfg["sender_name"] = style["sender_hints"]["sender_name_hint"]
            if style["sender_hints"].get("sender_role_hint") and not cfg.get("sender_role"):
                cfg["sender_role"] = style["sender_hints"]["sender_role_hint"]
            validated = kit.validate(cfg)
            cfg_p.write_text(json.dumps(validated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            saved["updated_config"] = str(cfg_p)
    return saved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="개인 발신메일함 구조·톤앤매너 분석기 (개인정보 익명화)")
    ap.add_argument("--discover", action="store_true", help="로컬 PC의 Thunderbird/Apple Mail/다운로드 발신함 자동 탐색")
    ap.add_argument("--mbox", help="로컬 .mbox 발신함 파일 경로 (Gmail Takeout 등)")
    ap.add_argument("--eml", help=".eml/.emlx 파일 또는 폴더 경로")
    ap.add_argument("--samples", help="발신 메일 텍스트/마크다운/JSON/CSV 파일 경로")
    ap.add_argument("--imap-host", help="읽기 전용 IMAP 서버 (예: imap.gmail.com, imap.naver.com)")
    ap.add_argument("--imap-port", type=int, default=993)
    ap.add_argument("--imap-mailbox", default="", help="발신함 폴더명 (생략 시 Sent/보낸편지함 자동 탐색)")
    ap.add_argument("--limit", type=int, default=30, help="최대 분석 메일 수 (기본 30)")
    ap.add_argument("--include-replies", action="store_true", help="Re:/답장 메일도 분석에 포함 (기본은 신규 발신 메일 위주)")
    ap.add_argument("--home", help="writing-style.json을 저장할 HERMES_HOME")
    ap.add_argument("--config", help="감지된 톤/CTA/서명 힌트를 반영할 setup.json 경로")
    ap.add_argument("--apply", action="store_true", help="분석 결과를 --home/writing-style.json (및 --config)에 저장")
    ap.add_argument("--report", help="마크다운 리포트 저장 경로 (예: Style-Guide.md)")
    ap.add_argument("--use-jev", action="store_true", help="TYPESAFE_API_KEY(JEV_API_KEY)가 있으면 익명화 발췌본으로 Jev 톤 보정")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    home = paths.normalize_home(args.home)
    try:
        if args.discover:
            boxes = discover_local_mailboxes()
            print(json.dumps({"discovered_mailboxes": boxes, "count": len(boxes)}, ensure_ascii=False, indent=2))
            return 0

        messages: list[dict[str, str]] = []
        skip_replies = not args.include_replies
        if args.mbox:
            messages.extend(load_mbox_messages(args.mbox, limit=args.limit, skip_replies=skip_replies))
        if args.eml:
            messages.extend(load_eml_messages(args.eml, limit=args.limit, skip_replies=skip_replies))
        if args.samples:
            messages.extend(load_text_or_json_messages(args.samples, limit=args.limit, skip_replies=skip_replies))
        if args.imap_host:
            _folder, imap_msgs = fetch_imap_sent_messages(
                args.imap_host, port=args.imap_port, mailbox_name=args.imap_mailbox,
                limit=args.limit, skip_replies=skip_replies, home=home,
            )
            messages.extend(imap_msgs)
        if not messages:
            ap.error("--discover, --mbox, --eml, --samples, --imap-host 중 하나 이상으로 발신 메일을 지정하세요.")

        batch = messages[:args.limit]
        style = analyze_sent_emails(batch)
        if args.use_jev:
            style = calibrate_style_with_jev(style, batch, home=home)
        if args.apply:
            style["applied"] = save_style_to_home(style, home, args.config)
        md = render_style_markdown(style)
        if args.report:
            Path(args.report).expanduser().absolute().write_text(md, encoding="utf-8")
        if args.json:
            print(json.dumps(style, ensure_ascii=False, indent=2))
        else:
            print(md)
        return 0
    except (ValueError, OSError, imaplib.IMAP4.error, json.JSONDecodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
