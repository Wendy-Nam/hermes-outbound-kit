#!/usr/bin/env python3
"""Stateful G2B (나라장터) 3-stage procurement monitor:
  1) 발주계획 (OrderPlanSttusService, dataset 15129462) — early proactive signal, NOT an active bid
  2) 사전규격 (HrcspSsstndrdInfoService) — pre-spec review stage
  3) 입찰공고 (BidPublicInfoService) — live bid notice

Features:
- Multi-keyword querying with deduplication, file locking, minimum request interval (default 3.2s),
  and bounded exponential-backoff retries (up to 5 attempts).
- 3-tier relevance classifier: direct_keywords + context_keywords + exclude_keywords (noise killer
  that filters out false positives like cafe/facility concession notices matching a broad word).
- Stateful baseline diff (`.g2b-state.json`): `--initialize` saves baseline; subsequent runs
  surface ONLY new and changed items.
- Writes Obsidian ledger under `<vault>/Market Intelligence/Procurement/G2B 발주계획 원장.md`.
"""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import web_extract

ROOT = Path(__file__).resolve().parents[2]

G2B_STAGE_ENDPOINTS: dict[str, dict[str, str]] = {
    "order_plan": {
        "label": "발주계획",
        "servc": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc",
        "thng": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListThng",
        "cnstwk": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwk",
        "frgcpt": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListFrgcpt",
    },
    "prespec": {
        "label": "사전규격",
        "servc": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc",
        "thng": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoThng",
        "cnstwk": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoCnstwk",
        "frgcpt": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoFrgcpt",
    },
    "bid_notice": {
        "label": "입찰공고",
        "servc": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc",
        "thng": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThng",
        "cnstwk": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk",
        "frgcpt": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoFrgcpt",
    },
}

DEFAULT_NOISE_EXCLUDES: tuple[str, ...] = (
    "카페", "편의시설", "입점업체", "판매대리", "매점", "구내식당", "자판기",
    "주차장", "청소용역", "경비용역", "미화", "식자재", "급식", "커피", "라운지",
)


@contextmanager
def _monitor_lock(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / ".g2b-monitor.lock"
    with lock_path.open("a+b") as fh:
        if os.name == "nt":
            import msvcrt
            if fh.seek(0, os.SEEK_END) == 0:
                fh.write(b"0")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_items_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("response", {}).get("body") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        return []
    items = body.get("items")
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return [it for it in (items or []) if isinstance(it, dict)]


def normalize_g2b_record(raw: dict[str, Any], stage: str) -> dict[str, Any]:
    """Normalize a single OrderPlan / PreSpec / BidNotice item into a unified schema."""
    stage_label = G2B_STAGE_ENDPOINTS.get(stage, {}).get("label", stage)
    item_id = _clean(
        raw.get("orderPlanUntyNo")
        or raw.get("bfSpecRgstNo")
        or raw.get("bidNtceNo")
        or raw.get("id")
        or ""
    )
    seq = _clean(raw.get("bidNtceOrd") or raw.get("orderPlanSno") or "00")
    title = _clean(
        raw.get("bizNm")
        or raw.get("prdctClsfcNoNm")
        or raw.get("bidNtceNm")
        or raw.get("title")
        or ""
    )
    agency = _clean(
        raw.get("orderInsttNm")
        or raw.get("rlDminsttNm")
        or raw.get("dminsttNm")
        or raw.get("ntceInsttNm")
        or raw.get("agency")
        or ""
    )
    budget = _clean(
        raw.get("sumOrderAmt")
        or raw.get("asignBdgtAmt")
        or raw.get("presmptPrce")
        or raw.get("budget")
        or ""
    )
    posted_at = _clean(
        raw.get("nticeDt")
        or raw.get("rgstDt")
        or raw.get("bidNtceDt")
        or raw.get("orderYear")
        or ""
    )
    expected_period = _clean(
        raw.get("orderMnth")
        or raw.get("opninRgstClseDt")
        or raw.get("bidClseDt")
        or ""
    )
    url = _clean(raw.get("bidNtceDtlUrl") or raw.get("url") or "")
    if not url and item_id and stage == "bid_notice":
        url = f"https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={urllib.parse.quote(item_id)}&bidPbancOrd={urllib.parse.quote(seq)}"
    if not url:
        url = "https://www.g2b.go.kr/"

    uid = f"g2b:{stage}:{item_id}-{seq}" if item_id else "g2b:" + stage + ":" + hashlib.sha256(f"{title}|{agency}".encode()).hexdigest()[:12]
    fp_src = json.dumps({"title": title, "agency": agency, "budget": budget, "expected": expected_period, "stage": stage}, sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()[:16]

    return {
        "uid": uid,
        "stage": stage,
        "stage_label": stage_label,
        "notice_no": item_id,
        "title": title,
        "agency": agency,
        "budget": budget,
        "posted_at": posted_at,
        "expected_period": expected_period,
        "url": url,
        "fingerprint": fingerprint,
    }


def classify_g2b_relevance(
    record: dict[str, Any],
    *,
    direct_keywords: list[str] | None = None,
    context_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """3-tier relevance classifier: direct match + context combo + noise exclusion."""
    haystack = f"{record.get('title', '')} {record.get('agency', '')}".lower()
    excludes = [k.strip().lower() for k in (exclude_keywords if exclude_keywords is not None else DEFAULT_NOISE_EXCLUDES) if k.strip()]
    for ex in excludes:
        if ex in haystack:
            return {"verdict": "제외", "reason": f"잡음 제외어 일치({ex})", "matched_direct": [], "matched_context": []}

    directs = [k.strip() for k in (direct_keywords or []) if k.strip()]
    contexts = [k.strip() for k in (context_keywords or []) if k.strip()]
    hit_direct = [k for k in directs if k.lower() in haystack]
    hit_context = [k for k in contexts if k.lower() in haystack]

    if hit_direct and (not contexts or hit_context):
        return {
            "verdict": "적합",
            "reason": f"직접 관련({', '.join(hit_direct)})" + (f" + 맥락({', '.join(hit_context)})" if hit_context else ""),
            "matched_direct": hit_direct,
            "matched_context": hit_context,
        }
    if hit_direct or len(hit_context) >= 2:
        return {
            "verdict": "추가검토",
            "reason": f"부분 일치(직접: {', '.join(hit_direct) or '없음'} / 맥락: {', '.join(hit_context) or '없음'})",
            "matched_direct": hit_direct,
            "matched_context": hit_context,
        }
    return {"verdict": "제외", "reason": "관련 키워드 미충족", "matched_direct": [], "matched_context": []}


def _fetch_g2b_with_retry(
    url: str,
    *,
    opener=None,
    max_retries: int = 5,
    base_backoff: float = 1.0,
    timeout: int = 20,
) -> tuple[str, dict[str, Any] | None, str]:
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    last_err = ""
    for attempt in range(max(1, max_retries)):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "hermes-outbound-kit/0.1"})
        try:
            with open_fn(req, timeout=timeout) as resp:
                raw = resp.read(2 * 1024 * 1024)
                return "ok", json.loads(raw.decode("utf-8", errors="replace")), ""
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            last_err = f"HTTP {code}"
            if code in (429, 500, 502, 503, 504) and attempt + 1 < max_retries:
                if base_backoff > 0:
                    time.sleep(base_backoff * (2 ** attempt))
                continue
            return "blocked" if code in (401, 403, 429) else "error", None, last_err
        except Exception as exc:
            last_err = type(exc).__name__
            if attempt + 1 < max_retries and base_backoff > 0:
                time.sleep(base_backoff * (2 ** attempt))
                continue
            return "error", None, last_err
    return "error", None, last_err


def run_g2b_monitor(
    *,
    keywords: list[str],
    stages: list[str] | None = None,
    tender_type: str = "servc",
    direct_keywords: list[str] | None = None,
    context_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    vault_dir: str | Path | None = None,
    state_path: str | Path | None = None,
    home: str | Path | None = None,
    initialize: bool = False,
    posted_from: str = "",
    min_interval: float = 3.2,
    max_retries: int = 5,
    fixture_items: list[dict[str, Any]] | None = None,
    opener=None,
) -> dict[str, Any]:
    """Run stateful G2B monitor across order_plan / prespec / bid_notice with baseline diff."""
    active_stages = [s for s in (stages or ["order_plan"]) if s in G2B_STAGE_ENDPOINTS]
    if not active_stages:
        active_stages = ["order_plan"]
    clean_keywords = [k.strip() for k in keywords if k.strip()]
    if not clean_keywords and fixture_items is None:
        raise ValueError("최소 1개 이상의 G2B 검색어가 필요합니다.")

    proc_dir = (Path(vault_dir).expanduser().absolute() / "Market Intelligence" / "Procurement") if vault_dir else Path(state_path or ".").expanduser().absolute().parent
    st_file = Path(state_path).expanduser().absolute() if state_path else (proc_dir / ".g2b-order-plan-state.json")

    dedup: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    with _monitor_lock(st_file.parent):
        if fixture_items is not None:
            for raw in fixture_items:
                st = str(raw.get("_stage") or active_stages[0])
                rec = normalize_g2b_record(raw, st)
                if rec["title"] and rec["uid"] not in dedup:
                    dedup[rec["uid"]] = rec
        else:
            api_key = web_extract.resolve_env_key(("DATA_GO_KR_API_KEY", "G2B_API_KEY"), home=home)
            if not api_key:
                return {
                    "status": "missing_key",
                    "error": "나라장터(G2B) 실시간 감시에는 $HERMES_HOME/.env에 DATA_GO_KR_API_KEY가 필요합니다.",
                    "stages": active_stages,
                }
            now = datetime.now(timezone.utc)
            start_dt = posted_from.replace("-", "")[:8] + "0000" if posted_from else (now - timedelta(days=30)).strftime("%Y%m%d0000")
            end_dt = now.strftime("%Y%m%d2359")
            req_idx = 0
            for stage in active_stages:
                endpoint = G2B_STAGE_ENDPOINTS[stage].get(tender_type, G2B_STAGE_ENDPOINTS[stage]["servc"])
                for kw in clean_keywords:
                    if req_idx > 0 and min_interval > 0:
                        time.sleep(min_interval)
                    req_idx += 1
                    params = {
                        "serviceKey": api_key,
                        "type": "json",
                        "pageNo": "1",
                        "numOfRows": "30",
                        "inqryDiv": "1",
                        "inqryBgnDt": start_dt,
                        "inqryEndDt": end_dt,
                    }
                    if stage == "order_plan":
                        params["bizNm"] = kw
                    elif stage == "prespec":
                        params["prdctClsfcNoNm"] = kw
                    else:
                        params["bidNtceNm"] = kw
                    url = endpoint + "?" + urllib.parse.urlencode(params)
                    status, payload, err = _fetch_g2b_with_retry(
                        url,
                        opener=opener,
                        max_retries=max_retries,
                        base_backoff=0.0 if min_interval == 0 else 1.0,
                    )
                    if status != "ok" or not payload:
                        errors.append(f"{stage}:{kw} -> {status} ({err})")
                        continue
                    for raw in _extract_items_from_payload(payload):
                        rec = normalize_g2b_record(raw, stage)
                        if rec["title"] and rec["uid"] not in dedup:
                            dedup[rec["uid"]] = rec

        # Relevance classification
        eff_direct = direct_keywords if direct_keywords is not None else clean_keywords
        classified: list[dict[str, Any]] = []
        for rec in dedup.values():
            cls = classify_g2b_relevance(
                rec,
                direct_keywords=eff_direct,
                context_keywords=context_keywords,
                exclude_keywords=exclude_keywords,
            )
            enriched = {**rec, **cls}
            classified.append(enriched)

        # Load prior baseline state
        prev_state: dict[str, dict[str, Any]] = {}
        if st_file.is_file() and not initialize:
            try:
                saved = json.loads(st_file.read_text(encoding="utf-8"))
                if isinstance(saved.get("items"), dict):
                    prev_state = saved["items"]
            except (OSError, ValueError):
                prev_state = {}

        new_items: list[dict[str, Any]] = []
        changed_items: list[dict[str, Any]] = []
        next_state_items = dict(prev_state)

        for item in classified:
            uid = item["uid"]
            old = prev_state.get(uid)
            if old is None:
                item["diff_status"] = "baseline" if initialize else "new"
                if not initialize:
                    new_items.append(item)
            elif old.get("fingerprint") != item["fingerprint"]:
                item["diff_status"] = "changed"
                changed_items.append(item)
            else:
                item["diff_status"] = "unchanged"
            next_state_items[uid] = {
                "fingerprint": item["fingerprint"],
                "stage": item["stage"],
                "title": item["title"],
                "agency": item["agency"],
                "verdict": item["verdict"],
                "posted_at": item["posted_at"],
            }

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state_payload = {
            "schema_version": "hermes_outbound_g2b_state/v1",
            "updated_at": now_iso,
            "stages": active_stages,
            "items": next_state_items,
        }
        fd, staged = tempfile.mkstemp(prefix=".g2b-", dir=st_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state_payload, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(staged, st_file)
        finally:
            if os.path.exists(staged):
                os.unlink(staged)

        # Write Obsidian Markdown ledger when vault_dir is provided
        ledger_path = None
        if vault_dir:
            proc_dir.mkdir(parents=True, exist_ok=True)
            ledger_path = proc_dir / "G2B 발주계획 원장.md"
            actionable = [it for it in classified if it["verdict"] in ("적합", "추가검토")]
            excluded_cnt = sum(1 for it in classified if it["verdict"] == "제외")
            rows = []
            for it in sorted(actionable, key=lambda x: (0 if x["verdict"] == "적합" else 1, x["posted_at"]), reverse=False):
                rows.append(
                    f"| {it['stage_label']} | {it['verdict']} | {it['diff_status']} | "
                    f"{it['agency'] or '미확인'} | {it['title'][:60]} | {it['budget'] or '—'} | {it['reason']} |"
                )
            md = (
                "# G2B 발주계획 · 사전규격 · 입찰공고 원장\n\n"
                "> **구분 원칙**: 발주계획은 선제 영업용 초기 구매 신호일 뿐 실제 입찰공고가 아닙니다. 사전규격·입찰공고와 구분해 검토합니다.\n\n"
                f"- **갱신 시각**: {now_iso}\n"
                f"- **조회 범위**: {', '.join(G2B_STAGE_ENDPOINTS[s]['label'] for s in active_stages)}\n"
                f"- **이번 수집**: 총 {len(classified)}건 (적합 {sum(1 for x in classified if x['verdict']=='적합')}건 / 추가검토 {sum(1 for x in classified if x['verdict']=='추가검토')}건 / 제외 {excluded_cnt}건)\n"
                f"- **신규·변경**: 신규 {len(new_items)}건 · 변경 {len(changed_items)}건\n\n"
                "## 검토 대상 항목 (적합 · 추가검토)\n"
                "| 단계 | 판정 | 변화 | 발주기관 | 사업명 | 예산 | 판정 근거 |\n"
                "|---|---|---|---|---|---|---|\n"
                + ("\n".join(rows) if rows else "| — | — | — | — | 검토 대상 항목 없음 | — | — |")
                + "\n"
            )
            ledger_path.write_text(md, encoding="utf-8")

            readme_path = proc_dir / "README.md"
            if not readme_path.exists():
                readme_path.write_text(
                    "# 나라장터(G2B) 감시 안내\n\n"
                    "- 원장: [[G2B 발주계획 원장]]\n"
                    "- 발주계획(초기 신호), 사전규격(규격 검토), 입찰공고(실제 공고)를 구분해 기록합니다.\n"
                    "- `.g2b-order-plan-state.json` 기준선과 비교해 신규·변경 항목만 브리핑에 올립니다.\n",
                    encoding="utf-8",
                )

    return {
        "status": "ok",
        "initialized": initialize,
        "stages": active_stages,
        "total_collected": len(classified),
        "verdict_counts": {
            "적합": sum(1 for x in classified if x["verdict"] == "적합"),
            "추가검토": sum(1 for x in classified if x["verdict"] == "추가검토"),
            "제외": sum(1 for x in classified if x["verdict"] == "제외"),
        },
        "new_count": len(new_items),
        "changed_count": len(changed_items),
        "new_actionable": [x for x in new_items if x["verdict"] in ("적합", "추가검토")],
        "changed_actionable": [x for x in changed_items if x["verdict"] in ("적합", "추가검토")],
        "state_path": str(st_file),
        "ledger_path": str(ledger_path) if ledger_path else "",
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="나라장터(G2B) 발주계획·사전규격·입찰공고 기준선 차분 감시기")
    parser.add_argument("--keywords", required=True, help="쉼표로 구분된 검색 키워드")
    parser.add_argument("--stages", default="order_plan", help="쉼표 구분 단계: order_plan,prespec,bid_notice")
    parser.add_argument("--tender-type", default="servc", choices=("servc", "thng", "cnstwk", "frgcpt"))
    parser.add_argument("--context-keywords", default="", help="맥락 조합 키워드(쉼표 구분)")
    parser.add_argument("--exclude-keywords", default="", help="추가 잡음 제외어(쉼표 구분)")
    parser.add_argument("--initialize", action="store_true", help="기준선 초기 저장 모드")
    parser.add_argument("--posted-from", default="", help="조회 시작일 (YYYY-MM-DD)")
    parser.add_argument("--vault", default="", help="Obsidian 볼트 경로")
    parser.add_argument("--home", default="", help="HERMES_HOME 경로")
    parser.add_argument("--min-interval", type=float, default=3.2)
    args = parser.parse_args(argv)

    kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    ctx = [k.strip() for k in args.context_keywords.split(",") if k.strip()] or None
    exc = list(DEFAULT_NOISE_EXCLUDES) + [k.strip() for k in args.exclude_keywords.split(",") if k.strip()]

    res = run_g2b_monitor(
        keywords=kws,
        stages=stages,
        tender_type=args.tender_type,
        context_keywords=ctx,
        exclude_keywords=exc,
        vault_dir=args.vault or None,
        home=args.home or None,
        initialize=args.initialize,
        posted_from=args.posted_from,
        min_interval=args.min_interval,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
