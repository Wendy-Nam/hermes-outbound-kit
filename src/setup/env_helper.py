#!/usr/bin/env python3
"""User-friendly .env API key manager & free local tool diagnostics (`outbound.py env`).

- Never prints raw secret values to stdout/stderr.
- Writes atomically to $HERMES_HOME/.env with 0600 permissions on POSIX.
- Checks presence of free open-source tools (Crawl4AI, Playwright, tesseract, Hermes)
  so users know what already works without paying for hosted APIs.
"""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any

import paths
import web_extract

ROOT = Path(__file__).resolve().parents[2]

ENV_SPECS: tuple[dict[str, str], ...] = (
    {"key": "DATA_GO_KR_API_KEY", "category": "나라장터(G2B)", "cost": "무료", "desc": "공공데이터포털 발주계획·사전규격·입찰공고 실시간 감시"},
    {"key": "CRAWL4AI_BASE_URL", "category": "JS 렌더링(1순위)", "cost": "무료 오픈소스", "desc": "로컬 Crawl4AI Docker 주소 (예: http://127.0.0.1:11235)"},
    {"key": "APIFY_TOKEN", "category": "LinkedIn 소싱", "cost": "선택 유료", "desc": "Apify 공식 Actor API (없으면 Sales Nav CSV / X-Ray 무료 모드)"},
    {"key": "OPENAI_API_KEY", "category": "이미지 OCR(2순위)", "cost": "선택 유료", "desc": "로컬 tesseract 없을 때 이미지 공고/브로셔 Vision 인식"},
    {"key": "OPENROUTER_API_KEY", "category": "이미지 OCR(2순위)", "cost": "선택 유료", "desc": "OpenRouter 경유 Vision 인식 대안"},
    {"key": "TYPESAFE_API_KEY", "category": "고속 채점·검수", "cost": "선택 유료", "desc": "TypeSafe AI Jev 고속 사전 필터링·초안 검수"},
    {"key": "FIRECRAWL_API_KEY", "category": "JS 렌더링(3순위)", "cost": "선택 유료", "desc": "로컬 Crawl4AI/Playwright 없이 SPA 페이지를 렌더링할 때"},
    {"key": "WEBSHARE_API_KEY", "category": "전용 프록시", "cost": "선택 유료", "desc": "허용된 공개 소스 전용 전송 (우회 금지)"},
    {"key": "GROQ_API_KEY", "category": "음성 인식 STT", "cost": "선택 유료", "desc": "Groq Whisper STT"},
    {"key": "COMPOSIO_CONSUMER_KEY", "category": "OAuth 앱 연결", "cost": "선택 유료", "desc": "Composio Connect MCP 소비자 키(ck_...)"},
)
KNOWN_KEYS = {item["key"] for item in ENV_SPECS}
KEY_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def _env_file(home: str | Path | None = None) -> Path:
    resolved_home = paths.normalize_home(home)
    return resolved_home / ".env"


def _parse_env_lines(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file() or path.is_symlink():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            values[k] = v
    return values


def set_env_value(key: str, value: str, *, home: str | Path | None = None) -> dict[str, Any]:
    """Atomically set or update one key in $HERMES_HOME/.env with 0600 permissions."""
    if not KEY_NAME_RE.fullmatch(key or ""):
        raise ValueError(f"유효하지 않은 환경변수 이름입니다: {key}")
    clean_val = (value or "").strip()
    if not clean_val or any(ord(c) < 32 for c in clean_val):
        raise ValueError("값이 비어 있거나 제어문자가 포함되어 있습니다.")
    env_path = _env_file(home)
    if env_path.is_symlink():
        raise ValueError(f"심볼릭 링크 .env에는 쓰지 않습니다: {env_path}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(env_path.parent, 0o700)

    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines() if env_path.exists() else []
    replaced = False
    new_lines: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            cur_key = stripped.split("=", 1)[0].strip()
            if cur_key == key:
                new_lines.append(f"{key}={clean_val}")
                replaced = True
                continue
        new_lines.append(raw)
    if not replaced:
        new_lines.append(f"{key}={clean_val}")

    fd, staged = tempfile.mkstemp(prefix=".env-", dir=env_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(new_lines) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if os.name == "posix":
            os.chmod(staged, 0o600)
        os.replace(staged, env_path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)

    return {
        "status": "updated" if replaced else "added",
        "key": key,
        "env_file": str(env_path),
        "value_redacted": True,
    }


def unset_env_value(key: str, *, home: str | Path | None = None) -> dict[str, Any]:
    if not KEY_NAME_RE.fullmatch(key or ""):
        raise ValueError(f"유효하지 않은 환경변수 이름입니다: {key}")
    env_path = _env_file(home)
    if not env_path.is_file() or env_path.is_symlink():
        return {"status": "not_found", "key": key, "env_file": str(env_path)}
    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    kept: list[str] = []
    removed = False
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped and stripped.split("=", 1)[0].strip() == key:
            removed = True
            continue
        kept.append(raw)
    if removed:
        fd, staged = tempfile.mkstemp(prefix=".env-", dir=env_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(("\n".join(kept) + "\n") if kept else "")
                fh.flush()
            if os.name == "posix":
                os.chmod(staged, 0o600)
            os.replace(staged, env_path)
        finally:
            if os.path.exists(staged):
                os.unlink(staged)
    return {"status": "removed" if removed else "not_found", "key": key, "env_file": str(env_path)}


def env_diagnostics(home: str | Path | None = None) -> dict[str, Any]:
    """Return redacted status of API keys and free open-source local tools."""
    env_path = _env_file(home)
    file_vals = _parse_env_lines(env_path)
    key_rows: list[dict[str, Any]] = []
    for spec in ENV_SPECS:
        k = spec["key"]
        in_proc = bool((os.environ.get(k) or "").strip())
        in_file = bool(file_vals.get(k))
        src_label = "process_env" if in_proc else (".env" if in_file else "unset")
        key_rows.append({
            "key": k,
            "category": spec["category"],
            "cost": spec["cost"],
            "configured": in_proc or in_file,
            "source": src_label,
            "description": spec["desc"],
        })

    c4_url = web_extract.resolve_env_key(("CRAWL4AI_BASE_URL",), home=env_path.parent)
    free_tools = {
        "crawl4ai": {
            "ready": bool(c4_url or shutil.which("crwl") or importlib.util.find_spec("crawl4ai") is not None),
            "mode": "http" if c4_url else ("cli" if shutil.which("crwl") else ("python" if importlib.util.find_spec("crawl4ai") else "not_installed")),
            "install_hint": "pip install crawl4ai && crawl4ai-setup (또는 Docker 실행 후 CRAWL4AI_BASE_URL=http://127.0.0.1:11235)",
        },
        "playwright": {
            "ready": importlib.util.find_spec("playwright") is not None,
            "install_hint": "pip install playwright && playwright install chromium",
        },
        "tesseract_ocr": {
            "ready": bool(shutil.which("tesseract")),
            "install_hint": "macOS: brew install tesseract-lang / Ubuntu: apt install tesseract-ocr tesseract-ocr-kor",
        },
        "hermes_cli": {
            "ready": bool(paths.resolve_hermes(env_path.parent, required=False)),
        },
    }
    return {
        "env_file": str(env_path),
        "env_file_exists": env_path.is_file(),
        "free_local_tools": free_tools,
        "keys": key_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="비개발자용 .env API 키 안전 관리 & 무료 로컬 도구 진단")
    sub = parser.add_subparsers(dest="action", required=True)

    p_st = sub.add_parser("status", help="현재 API 키 설정 여부(값 비공개)와 무료 로컬 도구 진단")
    p_st.add_argument("--home", default=None)
    p_st.add_argument("--json", action="store_true")

    p_set = sub.add_parser("set", help="특정 API 키/주소를 터미널 숨김 입력으로 $HERMES_HOME/.env에 안전 저장")
    p_set.add_argument("--key", required=True, help="예: APIFY_TOKEN, DATA_GO_KR_API_KEY, CRAWL4AI_BASE_URL")
    p_set.add_argument("--home", default=None)

    p_unset = sub.add_parser("unset", help="$HERMES_HOME/.env에서 특정 키 제거")
    p_unset.add_argument("--key", required=True)
    p_unset.add_argument("--home", default=None)

    args = parser.parse_args(argv)
    if args.action == "status":
        diag = env_diagnostics(args.home)
        if args.json:
            print(json.dumps(diag, ensure_ascii=False, indent=2))
            return 0
        print(f"환경 파일: {diag['env_file']} ({'존재함' if diag['env_file_exists'] else '아직 없음'})\n")
        print("[무료 오픈소스 로컬 도구 상태]")
        for name, info in diag["free_local_tools"].items():
            mark = "준비됨" if info["ready"] else "미설치"
            extra = f" ({info['mode']})" if "mode" in info and info["ready"] else ""
            print(f"  - {name:<15} {mark}{extra}")
            if not info["ready"] and info.get("install_hint"):
                print(f"      설치 안내: {info['install_hint']}")
        print("\n[선택 API 키 / 서비스 설정 상태 (값은 표시하지 않음)]")
        for row in diag["keys"]:
            st = f"설정됨({row['source']})" if row["configured"] else "미설정"
            print(f"  - {row['key']:<22} [{row['cost']:<8}] {st:<16} · {row['description']}")
        print("\n키를 추가하려면: python3 outbound.py env set --key DATA_GO_KR_API_KEY")
        return 0

    if args.action == "set":
        if not sys.stdin.isatty():
            print("오류: 키 입력은 본인의 대화형 터미널에서만 받습니다.", file=sys.stderr)
            return 2
        prompt = f"{args.key} 값을 입력하세요(화면에 표시되지 않습니다): "
        secret = getpass.getpass(prompt)
        res = set_env_value(args.key, secret, home=args.home)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    res = unset_env_value(args.key, home=args.home)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
