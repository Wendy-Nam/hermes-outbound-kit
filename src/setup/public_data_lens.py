#!/usr/bin/env python3
"""Safe optional Hermes connector & direct read-only MCP client for Public Data Lens
(https://github.com/Wendy-Nam/public-data-lens, MIT License).

Zero mandatory third-party dependencies (works even without PyYAML installed).
- Always sends `X-Datanav-No-Log: 1` on every request so search terms are not logged.
- Configures `mcp_servers.public-data-lens` in `$HERMES_HOME/config.yaml` (`plan/apply/check/probe`).
- Supports direct deterministic tool calls (`search`, `dataset`, `plan-data`, `columns`)
  with strict PII/secret query blocking so sales users can discover ~96k Korean public datasets
  and build `DRAFT` data plans (`build_data_plan`) directly from `outbound.py lens`.
- Preserves Public Data Lens evidence level labels (`CATALOG_METADATA_ONLY`, `FILE_OBSERVATION`,
  `DRAFT`, `CANDIDATE_ONLY`) and never treats catalog records as active G2B tender notices.
"""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
import urllib.error
import urllib.request

try:
    import yaml as _yaml  # Optional; pure-Python fallback used when absent
except ImportError:
    _yaml = None


ENDPOINT = "https://service.datahub.kr/projects/public-data-lens/mcp"
SERVER_NAME = "public-data-lens"
STATE = ".public-data-lens-state.json"
SCHEMA = "hermes_outbound_public_data_lens/v1"
MAX_RESPONSE = 2 * 1024 * 1024
TOOLS = (
    "search_datasets", "get_dataset", "compare_datasets", "get_catalog_changes",
    "get_catalog_stats", "search_by_columns", "get_dataset_structure",
    "build_data_plan", "get_context",
)
EVIDENCE_LEVELS = (
    "CATALOG_METADATA_ONLY",
    "FILE_OBSERVATION",
    "DRAFT",
    "CANDIDATE_ONLY",
)
DESIRED = {
    "url": ENDPOINT,
    "headers": {"X-Datanav-No-Log": "1"},
    "strict_redirect_headers": True,
    "enabled": True,
    "tools": {"include": list(TOOLS)},
    "connect_timeout": 30,
    "timeout": 120,
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\b01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}\b")
_SECRET_RE = re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|gsk_[A-Za-z0-9]{16,}|apify_api_[A-Za-z0-9]{12,}|ck_[A-Za-z0-9_-]{12,})\b")

_PURE_YAML_BLOCK = (
    "  public-data-lens:\n"
    f"    url: {ENDPOINT}\n"
    "    headers:\n"
    '      X-Datanav-No-Log: "1"\n'
    "    strict_redirect_headers: true\n"
    "    enabled: true\n"
    "    tools:\n"
    "      include:\n"
    + "".join(f"      - {t}\n" for t in TOOLS)
    + "    connect_timeout: 30\n"
    + "    timeout: 120\n"
)


class PublicDataLensError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _validate_non_sensitive_query(text: str, field_name: str = "query") -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        raise PublicDataLensError(f"{field_name}: 검색어 또는 목적 문장이 필요합니다.")
    if len(cleaned) > 300:
        raise PublicDataLensError(f"{field_name}: 300자 이하로 입력해주세요.")
    if _EMAIL_RE.search(cleaned) or _PHONE_RE.search(cleaned) or _SECRET_RE.search(cleaned):
        raise PublicDataLensError(
            "보안 원칙상 이메일·전화번호·API 키 같은 개인정보나 비밀값은 공공데이터 렌즈 검색어에 넣을 수 없습니다."
        )
    return cleaned


def _safe_home(home, *, create: bool) -> Path:
    root = Path(home).expanduser().absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise PublicDataLensError("설정 경로의 심볼릭 링크는 허용하지 않습니다.")
    if create:
        root.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(root, 0o700)
    return root


def _read_yaml_or_fallback(path: Path) -> tuple[dict | None, str]:
    if not path.exists():
        return {}, ""
    if path.is_symlink() or not path.is_file():
        raise PublicDataLensError("기존 config.yaml을 안전하게 읽을 수 없습니다.")
    raw = path.read_text(encoding="utf-8-sig")
    if _yaml is not None:
        try:
            value = _yaml.safe_load(raw) or {}
        except (OSError, Exception):
            raise PublicDataLensError("기존 config.yaml 형식을 보존했습니다.") from None
        if not isinstance(value, dict):
            raise PublicDataLensError("config.yaml 최상위는 객체여야 합니다.")
        return value, raw
    return None, raw


def _atomic(path: Path, text: str) -> None:
    if path.is_symlink():
        raise PublicDataLensError("설정 심볼릭 링크를 덮어쓰지 않습니다.")
    fd, staged = tempfile.mkstemp(prefix=".public-data-lens-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.chmod(staged, 0o600)
        os.replace(staged, path)
    finally:
        Path(staged).unlink(missing_ok=True)


@contextmanager
def _config_lock(root: Path):
    """Serialize read/merge/replace so a parallel installer cannot lose an update."""
    path = root / ".public-data-lens.lock"
    if path.is_symlink():
        raise PublicDataLensError("설정 잠금 파일의 심볼릭 링크를 거부했습니다.")
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0"); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def plan(home) -> dict:
    root = _safe_home(home, create=False)
    return {
        "status": "plan_only", "hermes_home": str(root), "server": SERVER_NAME,
        "endpoint": ENDPOINT, "authentication": "none", "no_log_header": True,
        "tools": list(TOOLS), "evidence_levels": list(EVIDENCE_LEVELS),
        "scope": "catalog_discovery_not_procurement_notices",
        "mutations": ["config.yaml mcp_servers.public-data-lens", STATE,
                      ".public-data-lens.lock"],
    }


def apply(home) -> dict:
    """Add the fixed no-log MCP entry without replacing user-owned config (works with or without PyYAML)."""
    root = _safe_home(home, create=True)
    with _config_lock(root):
        return _apply_locked(root)


def _apply_locked(root: Path) -> dict:
    config_path, state_path = root / "config.yaml", root / STATE
    config, raw_text = _read_yaml_or_fallback(config_path)
    previous_state = {}
    if state_path.exists():
        try:
            previous_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PublicDataLensError("기존 Public Data Lens 영수증을 보존했습니다.") from None
    if previous_state and previous_state.get("schema_version") != SCHEMA:
        raise PublicDataLensError("알 수 없는 Public Data Lens 영수증을 보존했습니다.")

    if config is not None and _yaml is not None:
        servers = config.get("mcp_servers")
        if servers is None:
            servers = {}; config["mcp_servers"] = servers
        if not isinstance(servers, dict):
            raise PublicDataLensError("기존 mcp_servers가 객체가 아니어서 보존했습니다.")
        current = servers.get(SERVER_NAME)
        owned = previous_state.get("applied") == current == DESIRED
        if current is not None and current != DESIRED and not owned:
            raise PublicDataLensError("기존 mcp_servers.public-data-lens 설정을 덮어쓰지 않았습니다.")
        servers[SERVER_NAME] = DESIRED
        rendered = _yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    else:
        # Pure-Python fallback when PyYAML is not installed on system Python
        if "public-data-lens:" in raw_text and previous_state.get("applied") != DESIRED:
            raise PublicDataLensError("기존 mcp_servers.public-data-lens 설정을 덮어쓰지 않았습니다.")
        if not raw_text.strip():
            rendered = "mcp_servers:\n" + _PURE_YAML_BLOCK
        elif "public-data-lens:" in raw_text:
            rendered = raw_text
        elif re.search(r"^mcp_servers:\s*$", raw_text, re.M):
            rendered = re.sub(r"(^mcp_servers:\s*$)", r"\1\n" + _PURE_YAML_BLOCK.rstrip("\n"), raw_text, count=1, flags=re.M)
        else:
            rendered = raw_text.rstrip("\n") + "\n\nmcp_servers:\n" + _PURE_YAML_BLOCK

    state = {
        "schema_version": SCHEMA, "endpoint": ENDPOINT, "applied": DESIRED,
        "config_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "network_probed": False, "catalog_discovery_only": True,
    }
    before_config = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    before_state = state_path.read_text(encoding="utf-8") if state_path.exists() else None
    written = []
    try:
        _atomic(config_path, rendered); written.append(config_path)
        _atomic(state_path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except Exception:
        for path, before in ((config_path, before_config), (state_path, before_state)):
            if path in written:
                if before is None: path.unlink(missing_ok=True)
                else: _atomic(path, before)
        raise
    return {"status": "applied_restart_required", "server": SERVER_NAME,
            "no_log_header": True, "functional_verified": False,
            "scope": "catalog_discovery_not_procurement_notices"}


def check(home) -> dict:
    root = _safe_home(home, create=False)
    config, raw_text = _read_yaml_or_fallback(root / "config.yaml")
    if config is not None and _yaml is not None:
        configured = (config.get("mcp_servers") or {}).get(SERVER_NAME) == DESIRED \
            if isinstance(config.get("mcp_servers") or {}, dict) else False
    else:
        configured = ("public-data-lens:" in raw_text and ENDPOINT in raw_text and "X-Datanav-No-Log" in raw_text)
    try:
        state = json.loads((root / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    return {"status": "configured_restart_unverified" if configured else "not_applied",
            "configured": configured, "receipt_valid": state.get("schema_version") == SCHEMA,
            "no_log_header": configured, "network_probed": False,
            "functional_verified": False,
            "scope": "catalog_discovery_not_procurement_notices"}


def _post(payload: dict, *, opener, session=None, protocol=None, notification=False):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "X-Datanav-No-Log": "1"}
    if session:
        headers["Mcp-Session-Id"] = session
    if protocol:
        headers["MCP-Protocol-Version"] = protocol
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE + 1)
            response_session = response.headers.get("Mcp-Session-Id")
            ctype = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    except urllib.error.HTTPError as exc:
        code = exc.code; exc.close()
        if 300 <= code < 400:
            raise PublicDataLensError("Public Data Lens redirect를 거부했습니다.") from None
        raise PublicDataLensError(f"Public Data Lens MCP가 HTTP {code}를 반환했습니다.") from None
    except Exception:
        raise PublicDataLensError("Public Data Lens MCP 연결에 실패했습니다.") from None
    if len(raw) > MAX_RESPONSE:
        raise PublicDataLensError("Public Data Lens MCP 응답이 2MiB 제한을 넘었습니다.")
    if (response_session is not None
            and not re.fullmatch(r"[\x21-\x7e]{1,1024}", response_session)):
        raise PublicDataLensError("Public Data Lens MCP session ID 형식이 잘못되었습니다.")
    if notification and not raw:
        return {}, response_session
    text_raw = raw.decode("utf-8", errors="strict")
    if ctype == "text/event-stream" or text_raw.lstrip().startswith(("event:", "data:")):
        data_lines = [ln[5:].lstrip() for ln in text_raw.splitlines() if ln.startswith("data:")]
        text_raw = "\n".join(data_lines).strip()
    try:
        body = json.loads(text_raw)
    except (UnicodeDecodeError, ValueError):
        raise PublicDataLensError("Public Data Lens MCP 응답이 JSON이 아닙니다.") from None
    if not isinstance(body, dict):
        raise PublicDataLensError("Public Data Lens MCP 응답 형식이 잘못되었습니다.")
    return body, response_session


def _init_mcp_session(transport) -> tuple[str | None, str]:
    initialized, session = _post(
        {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "hermes-outbound-kit", "version": "0.1"},
            },
        },
        opener=transport,
    )
    try:
        result = initialized["result"]
        protocol = result["protocolVersion"]
        if not isinstance(protocol, str) or not re.fullmatch(r"20\d\d-\d\d-\d\d", protocol):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise PublicDataLensError("Public Data Lens MCP initialize 응답이 잘못되었습니다.") from None
    _post(
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        opener=transport, session=session, protocol=protocol, notification=True,
    )
    return session, protocol


def probe(*, opener=None) -> dict:
    """Perform only MCP initialization and tools/list; never send a search query."""
    transport = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    session, protocol = _init_mcp_session(transport)
    listed, _ = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                      opener=transport, session=session, protocol=protocol)
    try:
        tools = listed["result"]["tools"]
        by_name = {row["name"]: row for row in tools
                   if isinstance(row, dict) and isinstance(row.get("name"), str)}
        names = set(by_name)
    except (KeyError, TypeError):
        raise PublicDataLensError("Public Data Lens MCP tools/list 응답이 잘못되었습니다.") from None
    missing = sorted(set(TOOLS) - names)
    if missing:
        raise PublicDataLensError("Public Data Lens 필수 read-only tool이 없습니다: " + ", ".join(missing))
    unsafe = []
    for name in TOOLS:
        annotations = by_name[name].get("annotations")
        if (not isinstance(annotations, dict)
                or annotations.get("readOnlyHint") is not True
                or annotations.get("destructiveHint") is not False):
            unsafe.append(name)
    if unsafe:
        raise PublicDataLensError("read-only annotation을 확인할 수 없습니다: " + ", ".join(unsafe))
    return {"status": "mcp_discovery_verified", "no_log_header_sent": True,
            "tools_verified": sorted(set(TOOLS)), "query_sent": False,
            "readonly_annotations_verified": True,
            "procurement_notice_verified": False, "functional_verified": False}


def call_lens_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    opener=None,
) -> dict[str, Any]:
    """Call a read-only Public Data Lens MCP tool directly with X-Datanav-No-Log: 1."""
    if tool_name not in TOOLS:
        raise PublicDataLensError(f"지원하지 않는 Public Data Lens 도구입니다: {tool_name}")
    transport = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    session, protocol = _init_mcp_session(transport)
    resp, _ = _post(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        opener=transport,
        session=session,
        protocol=protocol,
    )
    if "error" in resp:
        err_msg = resp["error"].get("message") if isinstance(resp.get("error"), dict) else str(resp["error"])
        raise PublicDataLensError(f"Public Data Lens 도구 오류({tool_name}): {err_msg}")
    result = resp.get("result")
    if not isinstance(result, dict):
        raise PublicDataLensError("Public Data Lens tools/call 응답 형식이 잘못되었습니다.")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        for block in (result.get("content") or []):
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                try:
                    structured = json.loads(block["text"])
                    break
                except ValueError:
                    structured = {"raw_text": block["text"]}
    return {
        "status": "ok",
        "tool": tool_name,
        "record_type": "public_dataset_catalog",
        "no_log_header_sent": True,
        "procurement_notice": False,
        "notice": "이 결과는 공공데이터포털 목록/구조 탐색 결과(public_dataset_catalog)이며 실제 나라장터 입찰공고가 아닙니다.",
        "payload": structured or result,
    }


def search_datasets(query: str, *, limit: int = 10, opener=None) -> dict[str, Any]:
    clean_q = _validate_non_sensitive_query(query, "query")
    return call_lens_tool("search_datasets", {"query": clean_q, "limit": max(1, min(int(limit), 25))}, opener=opener)


def build_data_plan(purpose: str, *, opener=None) -> dict[str, Any]:
    clean_p = _validate_non_sensitive_query(purpose, "purpose")
    res = call_lens_tool("build_data_plan", {"purpose": clean_p}, opener=opener)
    res["evidence_level"] = "DRAFT"
    return res


def search_by_columns(columns: list[str], *, query: str = "", limit: int = 10, opener=None) -> dict[str, Any]:
    clean_cols = [_validate_non_sensitive_query(c, "column") for c in columns if c.strip()]
    if not clean_cols:
        raise PublicDataLensError("최소 1개 이상의 컬럼명이 필요합니다.")
    args: dict[str, Any] = {"columns": clean_cols[:10], "limit": max(1, min(int(limit), 25))}
    if query.strip():
        args["query"] = _validate_non_sensitive_query(query, "query")
    return call_lens_tool("search_by_columns", args, opener=opener)


def get_dataset(dataset_id: str, *, view: str = "card", opener=None) -> dict[str, Any]:
    clean_id = _validate_non_sensitive_query(dataset_id, "dataset_id")
    return call_lens_tool("get_dataset", {"id": clean_id, "view": view}, opener=opener)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="공공데이터 렌즈(Public Data Lens) 무료無인증 MCP 설정 및 카탈로그·데이터 활용 계획 직접 조회"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    for act in ("plan", "apply", "check", "probe"):
        p = sub.add_parser(act, help=f"Hermes MCP 설정 {act}")
        p.add_argument("--home", default=str(Path.home() / ".hermes-outbound"))

    p_search = sub.add_parser("search", help="키워드로 공공데이터셋 카탈로그 탐색 (search_datasets)")
    p_search.add_argument("query", help="비민감 공개 키워드 (예: 해외 의료지원, 산업단지 공장 등록)")
    p_search.add_argument("--limit", type=int, default=10)

    p_plan = sub.add_parser("plan-data", help="영업·리서치 목적 문장 -> 공공데이터 활용 계획 초안 생성 (build_data_plan, 항상 DRAFT)")
    p_plan.add_argument("purpose", help="예: 제조 스마트팩토리 잠재고객 발굴을 위해 공장등록·산업단지 공공데이터 결합 계획")

    p_cols = sub.add_parser("columns", help="원본 컬럼명으로 공공데이터셋 검색 (search_by_columns)")
    p_cols.add_argument("columns", help="쉼표 구분 컬럼명 (예: 회사명,업종,소재지)")
    p_cols.add_argument("--query", default="")
    p_cols.add_argument("--limit", type=int, default=10)

    p_ds = sub.add_parser("dataset", help="단건 데이터셋 판단 카드/구조 조회 (get_dataset)")
    p_ds.add_argument("dataset_id")
    p_ds.add_argument("--view", default="card", choices=("card", "normalized", "source", "jsonld"))

    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            result = plan(args.home)
        elif args.action == "apply":
            result = apply(args.home)
        elif args.action == "check":
            result = check(args.home)
        elif args.action == "probe":
            result = probe()
        elif args.action == "search":
            result = search_datasets(args.query, limit=args.limit)
        elif args.action == "plan-data":
            result = build_data_plan(args.purpose)
        elif args.action == "columns":
            cols = [c.strip() for c in args.columns.split(",") if c.strip()]
            result = search_by_columns(cols, query=args.query, limit=args.limit)
        else:
            result = get_dataset(args.dataset_id, view=args.view)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
