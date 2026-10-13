#!/usr/bin/env python3
"""startup-crm — BD 타깃 파이프라인 추적(발굴→접촉→응답→미팅→계약).

장부(targets.json)에 회사별 레코드를 upsert. 파이프라인이 새 데이터를 부어도
**사람이 손댄 상태·메모·접촉일은 절대 안 덮는다**(구직 키트의 스테이징 교훈: 사람 편집 보존).

  crm.py --ingest             # stdin(scored json) → 신규 발굴 추가, 기존은 데이터만 갱신
  crm.py --status "회사=접촉"   # 상태 갱신
  crm.py --note   "회사=메모"   # 메모 추가(누적)
  crm.py --list [--stage 접촉] # 파이프라인 보기
"""
import argparse
import json
import os
import re
import sys

# 기본 장부: $HERMES_HOME/headhunt/targets.json (스킬 폴더 밖이라 업데이트에 덮이지 않음).
_HOME = os.environ.get("HERMES_HOME", "")
LEDGER = os.environ.get("HH_CRM_LEDGER") or (
    os.path.join(_HOME, "headhunt", "targets.json") if _HOME else "targets.json")
if os.path.dirname(LEDGER):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
STAGES = ["발굴", "접촉", "응답", "미팅", "계약", "실패"]


def _key(name):
    return re.sub(r"[^가-힣a-z0-9]", "", (name or "").lower())


def _load():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        sys.exit(f"❌ {LEDGER} 손상 — 수동 확인 필요(덮어쓰지 않음)")


def _save(d):
    tmp = f"{LEDGER}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LEDGER)


# 파이프라인이 채우는 필드(갱신 대상) vs 사람이 채우는 필드(보존 대상)
_DATA_FIELDS = ("company", "round", "amount", "sector", "open_roles", "roles", "score", "url", "date")
_HUMAN_FIELDS = ("status", "notes", "contacted_at")


def ingest(led, rows):
    added = updated = 0
    for r in rows:
        k = _key(r.get("company", ""))
        if not k:
            continue
        if k in led:                                # 기존: 데이터만 갱신, 사람 필드 보존
            for f in _DATA_FIELDS:
                if f in r:
                    led[k][f] = r[f]
            updated += 1
        else:                                       # 신규: 발굴 상태로 추가
            rec = {f: r.get(f) for f in _DATA_FIELDS}
            rec["status"] = "발굴"
            rec["notes"] = []
            rec["contacted_at"] = ""
            led[k] = rec
            added += 1
    return added, updated


def _find(led, name):
    k = _key(name)
    if k in led:
        return k
    for kk in led:                                  # 부분 일치 폴백
        if k and (k in kk or kk in k):
            return kk
    return None


def main():
    ap = argparse.ArgumentParser(description="BD 타깃 CRM 파이프라인")
    ap.add_argument("--ingest", action="store_true", help="stdin scored json 흡수")
    ap.add_argument("--status", help='"회사=상태" (발굴/접촉/응답/미팅/계약/실패)')
    ap.add_argument("--note", help='"회사=메모"')
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stage", help="--list 필터")
    a = ap.parse_args()
    led = _load()

    if a.ingest:
        rows = json.load(sys.stdin)
        add, upd = ingest(led, rows)
        _save(led)
        print(f"흡수: 신규 {add} · 갱신 {upd} (총 {len(led)})")
        return 0

    if a.status:
        name, _, val = a.status.partition("=")
        if val.strip() not in STAGES:
            sys.exit(f"상태는 {STAGES} 중 하나")
        k = _find(led, name)
        if not k:
            sys.exit(f"'{name}' 타깃 없음")
        led[k]["status"] = val.strip()
        if val.strip() == "접촉" and not led[k].get("contacted_at"):
            led[k]["contacted_at"] = "(접촉 표시)"
        _save(led)
        print(f"{led[k]['company']} → {val.strip()}")
        return 0

    if a.note:
        name, _, txt = a.note.partition("=")
        k = _find(led, name)
        if not k:
            sys.exit(f"'{name}' 타깃 없음")
        led[k].setdefault("notes", []).append(txt.strip())
        _save(led)
        print(f"{led[k]['company']} 메모 추가")
        return 0

    # 기본: --list
    recs = [v for v in led.values() if not a.stage or v.get("status") == a.stage]
    order = {s: i for i, s in enumerate(STAGES)}
    recs.sort(key=lambda r: (order.get(r.get("status"), 9), -(r.get("score") or 0)))
    print(f"{'상태':<6}{'점수':<6}{'회사':<20}{'라운드':<9}{'공고':<5}메모")
    for r in recs:
        opn = r.get("open_roles")
        opn = "?" if opn is None else str(opn)
        note = (r.get("notes") or [""])[-1][:30]
        print(f"{r.get('status',''):<6}{str(r.get('score','')):<6}{(r.get('company') or '')[:18]:<20}"
              f"{r.get('round',''):<9}{opn:<5}{note}")
    from collections import Counter
    c = Counter(r.get("status") for r in led.values())
    print("\n파이프라인:", " · ".join(f"{s} {c.get(s,0)}" for s in STAGES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
