#!/usr/bin/env python3
"""Optional JS/SPA rendering (Firecrawl) and image OCR/Vision extraction.

Zero mandatory third-party dependencies:
- JS rendering uses Firecrawl (/v1/scrape) only when FIRECRAWL_API_KEY is present
  in the environment or $HERMES_HOME/.env.
- Image text extraction uses a transparent 3-tier fallback:
  1) Local free `tesseract` binary (`kor+eng` -> `eng`) if installed on PATH
  2) Optional OpenAI / OpenRouter Vision API if OPENAI_API_KEY or OPENROUTER_API_KEY
     is configured in the environment or $HERMES_HOME/.env
  3) Explicit `ocr_unavailable` status with actionable setup hints (never fabricating text)

Never bypasses login walls, CAPTCHAs, or paywalls.
"""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import base64
import html as html_lib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Sequence
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_API_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

_SCRIPT_STYLE_RE = re.compile(r"<(?:script|style|noscript|svg)[^>]*>.*?</(?:script|style|noscript|svg)>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_JS_SHELL_MARKERS = (
    re.compile(r'<div[^>]+id=["\'](?:root|app|__next|__nuxt)["\'][^>]*>\s*</div>', re.I),
    re.compile(r"<noscript[^>]*>[^<]*(?:enable\s+javascript|자바스크립트를\s*활성화|javascript\s+is\s+required)", re.I),
    re.compile(r"window\.__NUXT__|__NEXT_DATA__|data-reactroot", re.I),
)
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
_ATTR_SRC_RE = re.compile(r'\b(?:data-original|data-src|data-lazy-src|src)\s*=\s*["\']([^"\']+)["\']', re.I)
_NOISE_IMG_RE = re.compile(
    r"(?:favicon|logo|icon|sprite|badge|avatar|pixel|tracker|blank|spacer|btn_|button|arrow|banner_ad|\.svg(?:\?|$)|1x1)",
    re.I,
)


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file() or path.is_symlink():
        return values
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val:
                values[key] = val
    except OSError:
        return values
    return values


def resolve_env_key(names: Sequence[str], home: str | Path | None = None) -> str:
    """Resolve an API key from process env or $HERMES_HOME/.env without leaking it."""
    for name in names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    candidates: list[Path] = []
    if home:
        candidates.append(Path(home).expanduser() / ".env")
    env_home = (os.environ.get("HERMES_HOME") or "").strip()
    if env_home:
        candidates.append(Path(env_home).expanduser() / ".env")
    candidates.extend([
        Path.home() / ".hermes-outbound" / ".env",
        Path.home() / ".hermes" / ".env",
    ])
    seen: set[Path] = set()
    for env_file in candidates:
        resolved = env_file.resolve() if env_file.exists() else env_file
        if resolved in seen:
            continue
        seen.add(resolved)
        parsed = _read_dotenv(env_file)
        for name in names:
            if parsed.get(name):
                return parsed[name]
    return ""


def _strip_visible_text(html_text: str) -> str:
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html_text)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = html_lib.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def looks_like_js_shell(raw_html: str | bytes, visible_text: str | None = None) -> bool:
    """Detect client-side rendered SPA shells whose static HTML lacks meaningful text."""
    html_text = raw_html.decode("utf-8", errors="ignore") if isinstance(raw_html, bytes) else (raw_html or "")
    if not html_text.strip():
        return True
    text = _strip_visible_text(html_text) if visible_text is None else visible_text.strip()
    if len(text) >= 400:
        return False
    has_marker = any(pat.search(html_text) for pat in _JS_SHELL_MARKERS)
    if has_marker and len(text) < 280:
        return True
    script_count = len(re.findall(r"<script\b", html_text, re.I))
    if script_count >= 3 and len(text) < 140:
        return True
    if re.search(r"(?:please\s+enable\s+javascript|자바스크립트를\s*허용|javascript\s+is\s+disabled)", text, re.I):
        return True
    return False


def _validate_public_http_url(url: str) -> str:
    parsed = urllib.parse.urlsplit((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("공개 http(s) URL만 지원합니다.")
    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local"):
        raise ValueError("로컬/사설 주소는 외부 렌더링·다운로드 대상으로 허용하지 않습니다.")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("사설/예약 IP 주소는 허용하지 않습니다.")
    except ValueError as exc:
        if "허용하지 않습니다" in str(exc):
            raise
    return parsed.geturl()


def scrape_with_firecrawl(
    url: str,
    *,
    api_key: str = "",
    home: str | Path | None = None,
    formats: Sequence[str] = ("markdown",),
    timeout: int = 30,
    opener=None,
) -> dict[str, Any]:
    """Render a public JS/SPA page via Firecrawl /v1/scrape using FIRECRAWL_API_KEY."""
    clean_url = _validate_public_http_url(url)
    key = (api_key or "").strip() or resolve_env_key(("FIRECRAWL_API_KEY",), home=home)
    if not key:
        return {
            "status": "missing_key",
            "provider": "firecrawl",
            "url": clean_url,
            "title": "",
            "markdown": "",
            "html": "",
            "text": "",
            "hint": "JS/SPA 페이지 자동 렌더링을 쓰려면 $HERMES_HOME/.env에 FIRECRAWL_API_KEY를 추가하세요.",
        }
    payload = {
        "url": clean_url,
        "formats": list(formats) or ["markdown"],
        "onlyMainContent": True,
    }
    req = urllib.request.Request(
        FIRECRAWL_SCRAPE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hermes-outbound-kit/0.1",
        },
        method="POST",
    )
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_fn(req, timeout=timeout) as resp:
            raw = resp.read(MAX_API_BYTES + 1)
            if len(raw) > MAX_API_BYTES:
                return {
                    "status": "error",
                    "provider": "firecrawl",
                    "url": clean_url,
                    "title": "",
                    "markdown": "",
                    "html": "",
                    "text": "",
                    "error": "Firecrawl 응답이 안전 한도(2MiB)를 초과했습니다.",
                }
            body = json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        msg = "Firecrawl 인증 실패(FIRECRAWL_API_KEY 확인 필요)" if code in (401, 403) else f"Firecrawl HTTP {code}"
        return {
            "status": "error",
            "provider": "firecrawl",
            "url": clean_url,
            "title": "",
            "markdown": "",
            "html": "",
            "text": "",
            "error": msg,
        }
    except Exception as exc:
        return {
            "status": "error",
            "provider": "firecrawl",
            "url": clean_url,
            "title": "",
            "markdown": "",
            "html": "",
            "text": "",
            "error": f"Firecrawl 요청 실패: {type(exc).__name__}",
        }

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return {
            "status": "error",
            "provider": "firecrawl",
            "url": clean_url,
            "title": "",
            "markdown": "",
            "html": "",
            "text": "",
            "error": "Firecrawl 응답에 data 객체가 없습니다.",
        }
    markdown = str(data.get("markdown") or "").strip()
    html_out = str(data.get("html") or "").strip()
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    title = str(meta.get("title") or meta.get("ogTitle") or "").strip()
    text = markdown or (_strip_visible_text(html_out) if html_out else "")
    return {
        "status": "ok" if text else "empty",
        "provider": "firecrawl",
        "url": clean_url,
        "title": title,
        "markdown": markdown,
        "html": html_out,
        "text": text,
    }


def extract_image_urls(html_text: str, base_url: str = "", *, limit: int = 8) -> list[str]:
    """Extract likely content/JD image URLs from HTML while skipping icons & trackers."""
    if not html_text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _IMG_TAG_RE.finditer(html_text):
        tag = match.group(0)
        src_match = _ATTR_SRC_RE.search(tag)
        if not src_match:
            continue
        raw_src = html_lib.unescape(src_match.group(1).strip())
        if not raw_src or raw_src.startswith("data:"):
            continue
        if _NOISE_IMG_RE.search(raw_src):
            continue
        resolved = urllib.parse.urljoin(base_url, raw_src) if base_url else raw_src
        parsed = urllib.parse.urlsplit(resolved)
        if parsed.scheme not in ("http", "https"):
            continue
        if resolved not in seen:
            seen.add(resolved)
            found.append(resolved)
            if len(found) >= limit:
                break
    return found


def _load_image_bytes(source: str | Path, *, opener=None, timeout: int = 25) -> tuple[bytes, str, str]:
    text = str(source).strip()
    if re.match(r"^https?://", text, re.I):
        clean_url = _validate_public_http_url(text)
        req = urllib.request.Request(clean_url, headers={"User-Agent": "hermes-outbound-kit/0.1"})
        open_fn = opener.open if opener is not None else urllib.request.urlopen
        with open_fn(req, timeout=timeout) as resp:
            raw = resp.read(MAX_IMAGE_BYTES + 1)
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("이미지 크기가 안전 한도(8MiB)를 초과했습니다.")
            ctype = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if not ctype.startswith("image/"):
                guessed, _ = mimetypes.guess_type(urllib.parse.urlsplit(clean_url).path)
                ctype = guessed or "image/png"
            return raw, ctype, clean_url
    path = Path(source).expanduser()
    if not path.is_file():
        raise ValueError(f"이미지 파일을 찾을 수 없습니다: {path}")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("이미지 파일이 안전 한도(8MiB)를 초과했습니다.")
    guessed, _ = mimetypes.guess_type(path.name)
    return path.read_bytes(), guessed or "image/png", str(path)


def _run_tesseract(image_bytes: bytes, mime_type: str) -> str:
    binary = shutil.which("tesseract")
    if not binary:
        return ""
    suffix = mimetypes.guess_extension(mime_type) or ".png"
    if suffix == ".jpe":
        suffix = ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)
    try:
        for lang in ("kor+eng", "eng"):
            proc = subprocess.run(
                [binary, str(tmp_path), "stdout", "-l", lang],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return re.sub(r"\n{3,}", "\n\n", proc.stdout).strip()
    finally:
        tmp_path.unlink(missing_ok=True)
    return ""


def _call_vision_api(
    image_bytes: bytes,
    mime_type: str,
    *,
    home: str | Path | None = None,
    opener=None,
    timeout: int = 45,
) -> tuple[str, str]:
    openai_key = resolve_env_key(("OPENAI_API_KEY",), home=home)
    openrouter_key = "" if openai_key else resolve_env_key(("OPENROUTER_API_KEY",), home=home)
    if openai_key:
        endpoint = OPENAI_CHAT_URL
        key = openai_key
        model = (os.environ.get("OPENAI_VISION_MODEL") or "gpt-4o-mini").strip()
        provider = "openai_vision"
    elif openrouter_key:
        endpoint = OPENROUTER_CHAT_URL
        key = openrouter_key
        model = (os.environ.get("OPENROUTER_VISION_MODEL") or "openai/gpt-4o-mini").strip()
        provider = "openrouter_vision"
    else:
        return "", ""

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_uri = f"data:{mime_type};base64,{b64}"
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 1500,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "이 이미지에 실제로 보이는 한글·영문 텍스트, 회사명, 직무/제품명, "
                            "핵심 수치, 기술 스택만 정확히 텍스트로 옮겨 주세요. "
                            "이미지에 없는 내용은 추측하거나 지어내지 마세요."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    with open_fn(req, timeout=timeout) as resp:
        raw = resp.read(MAX_API_BYTES + 1)
        body = json.loads(raw.decode("utf-8", errors="replace"))
    choices = body.get("choices") if isinstance(body, dict) else None
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = msg.get("content") if isinstance(msg, dict) else ""
        if isinstance(content, str) and content.strip():
            return content.strip(), provider
    return "", provider


def extract_image_text(
    source: str | Path,
    *,
    home: str | Path | None = None,
    opener=None,
    timeout: int = 45,
) -> dict[str, Any]:
    """Extract text from a local image or public image URL via tesseract or Vision API."""
    try:
        image_bytes, mime_type, label = _load_image_bytes(source, opener=opener, timeout=timeout)
    except Exception as exc:
        return {
            "status": "error",
            "provider": "none",
            "source": str(source),
            "text": "",
            "error": str(exc),
        }

    # Tier 1: Local free Tesseract OCR
    try:
        ocr_text = _run_tesseract(image_bytes, mime_type)
        if ocr_text:
            return {
                "status": "ok",
                "provider": "tesseract",
                "source": label,
                "text": ocr_text,
            }
    except Exception:
        pass

    # Tier 2: Optional Vision LLM API (OPENAI_API_KEY or OPENROUTER_API_KEY)
    try:
        vision_text, provider = _call_vision_api(image_bytes, mime_type, home=home, opener=opener, timeout=timeout)
        if vision_text:
            return {
                "status": "ok",
                "provider": provider,
                "source": label,
                "text": vision_text,
            }
    except Exception as exc:
        return {
            "status": "error",
            "provider": "vision_api",
            "source": label,
            "text": "",
            "error": f"Vision API 호출 실패: {type(exc).__name__}",
        }

    # Tier 3: Transparent unavailable notice
    return {
        "status": "ocr_unavailable",
        "provider": "none",
        "source": label,
        "text": "",
        "hint": (
            "이미지에서 텍스트를 자동 추출하려면 로컬 tesseract(예: brew install tesseract-lang)를 설치하거나 "
            "$HERMES_HOME/.env에 OPENAI_API_KEY 또는 OPENROUTER_API_KEY를 설정하세요."
        ),
    }
