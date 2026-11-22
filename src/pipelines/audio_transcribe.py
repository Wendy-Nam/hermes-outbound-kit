#!/usr/bin/env python3
"""Groq Whisper local audio transcription for sales meetings & Plaud recordings.

Derived from Wendy-Nam/Plaud-Groq-transcribe (MIT License).
Zero third-party Python dependencies (Python 3.11+ stdlib only).

Features:
- Resolves GROQ_API_KEY from process env or $HERMES_HOME/.env (never prints secrets).
- Includes browser User-Agent to avoid Cloudflare HTTP 403 (error code 1010) on default urllib UA.
- Retries up to 3 times on transient empty/429/5xx responses.
- Automatically splits audio files >24MiB into 20-minute chunks via `ffmpeg` if installed.
- Works standalone (`outbound.py transcribe`) or directly inside `outbound.py meeting post --audio-file`.
"""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request

import web_extract

ROOT = Path(__file__).resolve().parents[2]
GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"
SUPPORTED_MODELS = ("whisper-large-v3-turbo", "whisper-large-v3")
SUPPORTED_AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".webm", ".flac", ".mp4", ".mpeg"}
MAX_SINGLE_CHUNK_BYTES = 24 * 1024 * 1024  # Groq 25MB cap with safety margin
CLOUDFLARE_SAFE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _guess_audio_mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith(("audio/", "video/")):
        return guessed
    ext = path.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
        ".mp4": "audio/mp4",
    }.get(ext, "audio/mpeg")


def _build_multipart(
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    *,
    model: str,
    language: str,
) -> tuple[bytes, str]:
    boundary = f"----HermesGroq{os.getpid()}{int(time.time() * 1000) % 100000}"
    parts: list[bytes] = []
    for name, val in (
        ("model", model),
        ("temperature", "0"),
        ("response_format", "json"),
        ("language", language),
    ):
        if not val:
            continue
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode("utf-8")
        )
    safe_name = Path(filename).name.replace('"', "")
    parts.append(
        (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
            f'Content-Type: {mime_type}\r\n\r\n'
        ).encode("utf-8")
    )
    parts.append(audio_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _split_audio_chunks(audio_path: Path, segment_seconds: int = 1200) -> tuple[list[Path], tempfile.TemporaryDirectory]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError(
            "오디오 파일이 24MB를 초과해 분할이 필요하지만 ffmpeg가 설치되어 있지 않습니다. "
            "ffmpeg를 설치(macOS: brew install ffmpeg)하거나 24MB 이하로 분할해 다시 시도하세요."
        )
    tmpdir = tempfile.TemporaryDirectory(prefix="hermes-audio-chunks-")
    out_pattern = str(Path(tmpdir.name) / f"chunk_%03d{audio_path.suffix.lower() or '.mp3'}")
    proc = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-i", str(audio_path),
            "-f", "segment", "-segment_time", str(segment_seconds),
            "-c", "copy", out_pattern,
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        tmpdir.cleanup()
        raise ValueError(f"ffmpeg 오디오 분할 실패(exit {proc.returncode}): {proc.stderr[:200]}")
    chunks = sorted(Path(tmpdir.name).glob("chunk_*"))
    if not chunks:
        tmpdir.cleanup()
        raise ValueError("ffmpeg 분할 결과 파일이 생성되지 않았습니다.")
    return chunks, tmpdir


def _transcribe_single_bytes(
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    *,
    api_key: str,
    model: str,
    language: str,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: int = 300,
    opener=None,
) -> str:
    if not audio_bytes:
        raise ValueError("오디오 파일이 비어 있습니다.")
    body, boundary = _build_multipart(audio_bytes, filename, mime_type, model=model, language=language)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": CLOUDFLARE_SAFE_UA,
        "Accept": "application/json",
    }
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    last_err = ""

    for attempt in range(max(1, max_retries)):
        req = urllib.request.Request(GROQ_TRANSCRIBE_URL, data=body, headers=headers, method="POST")
        try:
            with open_fn(req, timeout=timeout) as resp:
                raw = resp.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
            parsed = json.loads(raw)
            text = str(parsed.get("text") or "").strip()
            if text:
                return text
            last_err = "empty_transcript"
            if attempt + 1 < max_retries and retry_delay > 0:
                time.sleep(retry_delay * (attempt + 1))
        except urllib.error.HTTPError as exc:
            code = exc.code
            err_body = exc.read(300).decode("utf-8", errors="replace")
            exc.close()
            if code in (401, 403):
                if "1010" in err_body:
                    raise ValueError("Groq Cloudflare 차단(403/1010)이 발생했습니다.") from None
                raise ValueError("Groq API 인증 실패(GROQ_API_KEY를 확인하세요).") from None
            last_err = f"HTTP {code}"
            if (code in (400, 429, 500, 502, 503, 504)) and attempt + 1 < max_retries:
                if retry_delay > 0:
                    time.sleep(retry_delay * (attempt + 1))
                continue
            raise ValueError(f"Groq 전사 요청 실패({last_err})") from None
        except Exception as exc:
            last_err = type(exc).__name__
            if attempt + 1 < max_retries and retry_delay > 0:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise ValueError(f"Groq 전사 연결 실패({last_err})") from None

    raise ValueError(f"Groq 전사 결과가 비어 있습니다({last_err}).")


def transcribe_audio(
    audio_path: str | Path,
    *,
    out_path: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    language: str = "ko",
    home: str | Path | None = None,
    api_key: str = "",
    max_retries: int = 3,
    retry_delay: float = 2.0,
    opener=None,
) -> dict[str, Any]:
    """Transcribe a local Plaud or meeting audio file via Groq Whisper API."""
    target = Path(audio_path).expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"읽을 수 있는 오디오 파일이 아닙니다: {audio_path}")
    if target.suffix.lower() not in SUPPORTED_AUDIO_EXTS:
        raise ValueError(f"지원하지 않는 오디오 확장자입니다: {target.suffix} (지원: {', '.join(sorted(SUPPORTED_AUDIO_EXTS))})")
    key = (api_key or "").strip() or web_extract.resolve_env_key(("GROQ_API_KEY",), home=home)
    if not key:
        return {
            "status": "missing_key",
            "audio_path": str(target),
            "text": "",
            "hint": "오디오 자동 전사를 쓰려면 `python3 outbound.py env set --key GROQ_API_KEY`로 무료 Groq 키를 등록하세요.",
        }

    size_bytes = target.stat().st_size
    mime = _guess_audio_mime(target)
    chunk_texts: list[str] = []
    chunks_used = 1

    if size_bytes > MAX_SINGLE_CHUNK_BYTES:
        chunks, tmpdir = _split_audio_chunks(target)
        chunks_used = len(chunks)
        try:
            for chunk in chunks:
                part_text = _transcribe_single_bytes(
                    chunk.read_bytes(), chunk.name, _guess_audio_mime(chunk),
                    api_key=key, model=model, language=language,
                    max_retries=max_retries, retry_delay=retry_delay, opener=opener,
                )
                chunk_texts.append(part_text)
        finally:
            tmpdir.cleanup()
    else:
        part_text = _transcribe_single_bytes(
            target.read_bytes(), target.name, mime,
            api_key=key, model=model, language=language,
            max_retries=max_retries, retry_delay=retry_delay, opener=opener,
        )
        chunk_texts.append(part_text)

    full_text = "\n\n".join(t for t in chunk_texts if t).strip()
    saved_to = ""
    if out_path:
        dest = Path(out_path).expanduser().absolute()
        if dest.is_symlink():
            raise ValueError(f"심볼릭 링크에는 저장하지 않습니다: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(full_text + "\n", encoding="utf-8")
        saved_to = str(dest)

    return {
        "status": "ok",
        "provider": "groq_whisper",
        "model": model,
        "language": language,
        "audio_path": str(target),
        "size_bytes": size_bytes,
        "chunks": chunks_used,
        "chars": len(full_text),
        "output_path": saved_to,
        "text": full_text,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plaud/미팅 녹음 파일을 Groq Whisper(무료 티어)로 한국어·영문 전사")
    parser.add_argument("audio", help="로컬 오디오 파일 경로 (.mp3, .m4a, .wav 등)")
    parser.add_argument("--output", "-o", default="", help="전사 텍스트 저장 경로 (생략 시 표준출력/JSON)")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=SUPPORTED_MODELS,
                        help="whisper-large-v3-turbo(빠름, 기본) 또는 whisper-large-v3(정확도 우선)")
    parser.add_argument("--language", default="ko", help="음성 언어 코드 (기본: ko)")
    parser.add_argument("--home", default=None, help="HERMES_HOME 경로")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        res = transcribe_audio(
            args.audio,
            out_path=args.output or None,
            model=args.model,
            language=args.language,
            home=args.home,
        )
        if args.json or res.get("status") != "ok":
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if res.get("status") == "ok" else 1
        if res["output_path"]:
            print(f"전사 완료 ({res['chars']}자, {res['chunks']}청크) -> {res['output_path']}")
        else:
            print(res["text"])
        return 0
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
