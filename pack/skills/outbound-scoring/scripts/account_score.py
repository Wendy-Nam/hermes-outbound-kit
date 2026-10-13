#!/usr/bin/env python3
"""아웃바운드 계정 스코어링 — 적합도·긴급도 2축. 이 스크립트가 유일 계산자(손채점 금지).

  각 축 = 100 × Σ(가중치 × 비율) / Σ(적용된 가중치)

핵심 원칙(구직 파이프라인과 동일): **증거가 없는 신호는 감점이 아니라 계산에서 뺀다.**
"모른다"와 "나쁘다"는 다르다. 리서치가 덜 된 계정을 낮은 점수로 묻어버리면
스코어가 계정의 질이 아니라 리서치 진행도를 재게 된다.

입력: JSON(파일 또는 stdin). 각 신호는 없으면 생략한다 — 빈 문자열로 채우지 말 것.
  {
    "company": "회사명",
    "fit":     {"revenue_model": "구독 기반 SaaS", "industry": "핀테크",
                "size": "시리즈C", "tech_stack": "Snowflake, dbt"},
    "urgency": {"exec_signal":  {"text": "대표가 AI 도입 선언", "days_ago": 12},
                "event_signal": {"text": "CTO가 데이터 컨퍼런스 발표", "days_ago": 40},
                "competitor":   {"text": "경쟁사 솔루션 도입 검토"},
                "hiring":       {"text": "데이터 엔지니어 채용 중"}},
    "evidence": {"exec_signal": "https://...", "event_signal": "https://..."}
  }

사용:
  account_score.py --in account.json          # 한 건
  account_score.py --in accounts.jsonl --jsonl # 여러 건, 우선순위 정렬 출력
"""
from __future__ import annotations
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 우선순위: OUTBOUND_SALES_PROFILE → $HERMES_HOME/sales-profile.json(사용자 사본) → 스킬 기본 예시값.
_HOME_PROFILE = os.path.join(os.environ.get("HERMES_HOME", ""), "sales-profile.json")
PROFILE = (os.environ.get("OUTBOUND_SALES_PROFILE")
           or (_HOME_PROFILE if os.environ.get("HERMES_HOME") and os.path.isfile(_HOME_PROFILE) else None)
           or os.path.join(os.path.dirname(HERE), "sales-profile.json"))


def load_profile():
    try:
        with open(PROFILE, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"❌ {PROFILE} 없음 — 채점 기준이 없으면 점수를 만들지 않는다.")
    except ValueError as e:
        raise SystemExit(f"❌ sales-profile.json 파싱 실패 — 중단(잘못된 점수보다 안전): {e}")


def _bands(rows):
    try:
        return [(re.compile("(?i)(" + pat + ")"), float(r)) for pat, r in (rows or [])]
    except (TypeError, ValueError, re.error) as e:
        raise SystemExit(f"❌ 밴드 정규식이 잘못됨 — 중단: {e}")


def _match(text, bands):
    """첫 매치의 비율. 매치 없으면 None(=축 제외, 0점 아님)."""
    if not text:
        return None
    for rx, r in bands:
        if rx.search(str(text)):
            return r
    return None


def _decay(days, table):
    if days is None:
        return 1.0                      # 시점 모르면 감쇠 없음 — 추측해서 깎지 않는다
    for limit, mult in table:
        if days <= limit:
            return float(mult)
    return float(table[-1][1]) if table else 1.0


def score_axis(data, weights, band_map, decay=None, min_cov=0.5):
    parts, used, missing = [], [], []
    for key, w in weights.items():
        raw = data.get(key)
        if raw is None:
            missing.append(key); continue
        text = raw.get("text") if isinstance(raw, dict) else raw
        ratio = _match(text, band_map.get(key, []))
        if ratio is None:
            missing.append(key); continue
        if decay and isinstance(raw, dict):
            ratio *= _decay(raw.get("days_ago"), decay)
        parts.append((w, ratio)); used.append(key)
    denom = sum(w for w, _ in parts)
    total = sum(weights.values()) or 1
    # 커버리지 게이트: 아는 게 너무 적으면 점수를 내지 않는다. 신호 하나로 100점이
    # 나오면 스코어가 계정의 질이 아니라 운 좋은 한 조각을 재게 된다.
    if not denom or denom / total < min_cov:
        return None, used, missing
    return round(100 * sum(w * r for w, r in parts) / denom), used, missing


def evaluate(acc, p):
    fitw = p["fit"]["weights"]
    fitw = {k: v for k, v in fitw.items() if not k.startswith("_")}
    fitb = {k: _bands(p["fit"].get(k + "_bands")) for k in fitw}
    urgw = {k: v for k, v in p["urgency"]["weights"].items() if not k.startswith("_")}
    urgb = {"exec_signal": _bands(p["urgency"].get("exec_bands")),
            "event_signal": _bands(p["urgency"].get("event_bands")),
            "competitor": _bands(p["urgency"].get("competitor_bands")),
            "hiring": _bands(p["urgency"].get("hiring_bands"))}
    decay = p["urgency"].get("recency_decay") or []

    mc = float(p["cutoff"].get("min_coverage", 0.5))
    fit, fu, fm = score_axis(acc.get("fit") or {}, fitw, fitb, min_cov=mc)
    urg, uu, um = score_axis(acc.get("urgency") or {}, urgw, urgb, decay, min_cov=mc)

    cn, nu = p["cutoff"]["call_now"], p["cutoff"]["nurture"]
    if fit is None or urg is None:
        action = "리서치 필요"          # 한 축이 통째로 비면 판정 자체를 미룬다
    elif fit >= cn and urg >= cn:
        action = "지금 콜"
    elif fit >= cn and urg >= nu:
        action = "콜 예약"
    elif fit >= nu:
        action = "너처링"
    else:
        action = "보류"
    return {"company": acc.get("company", "?"), "fit": fit, "urgency": urg,
            "action": action, "fit_used": fu, "fit_missing": fm,
            "urgency_used": uu, "urgency_missing": um,
            "evidence": acc.get("evidence") or {}}


def fmt(r):
    f = "—" if r["fit"] is None else f"{r['fit']:3d}"
    u = "—" if r["urgency"] is None else f"{r['urgency']:3d}"
    miss = r["fit_missing"] + r["urgency_missing"]
    tail = f"  (미확인: {', '.join(miss)})" if miss else ""
    return f"{r['action']:<8} 적합 {f} · 긴급 {u}  {r['company']}{tail}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", help="JSON 파일(없으면 stdin)")
    ap.add_argument("--jsonl", action="store_true", help="줄당 1건")
    ap.add_argument("--json-out", action="store_true", help="결과를 JSON으로")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    p = load_profile()

    if a.selftest:
        return selftest(p)

    raw = open(a.src, encoding="utf-8").read() if a.src else sys.stdin.read()
    accs = [json.loads(l) for l in raw.splitlines() if l.strip()] if a.jsonl else [json.loads(raw)]
    res = [evaluate(x, p) for x in accs]
    res.sort(key=lambda r: (r["fit"] or -1) + (r["urgency"] or -1), reverse=True)
    if a.json_out:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for r in res:
            print(fmt(r))
    return 0


def selftest(p):
    hot = {"company": "핫계정",
           "fit": {"revenue_model": "구독 기반 SaaS", "industry": "핀테크",
                   "size": "시리즈C 스케일업", "tech_stack": "Snowflake, dbt"},
           "urgency": {"exec_signal": {"text": "대표가 AI 도입 선언", "days_ago": 10},
                       "event_signal": {"text": "CTO 발표", "days_ago": 20},
                       "competitor": {"text": "경쟁사 도입 검토"},
                       "hiring": {"text": "데이터 엔지니어 채용"}}}
    thin = {"company": "리서치부족", "fit": {"industry": "핀테크"}, "urgency": {}}
    stale = {"company": "오래된신호",
             "fit": {"revenue_model": "구독 기반 SaaS", "industry": "SaaS",
                     "size": "시리즈C", "tech_stack": "Snowflake"},
             "urgency": {"exec_signal": {"text": "대표가 AI 도입 선언", "days_ago": 300}}}
    r1, r2, r3 = evaluate(hot, p), evaluate(thin, p), evaluate(stale, p)
    assert r1["action"] == "지금 콜", r1
    assert r2["urgency"] is None and r2["action"] == "리서치 필요", r2
    assert r2["fit"] is None, ("커버리지 게이트: 업종 하나로 점수가 나오면 안 된다", r2)
    assert "revenue_model" in r2["fit_missing"], r2
    assert r3["urgency"] is None, ("신호 1개(35%)는 커버리지 미달이어야 한다", r3)
    for r in (r1, r2, r3):
        print("  ", fmt(r))
    print("selftest 6/6 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
