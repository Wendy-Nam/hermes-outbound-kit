#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""범용 콜드메일·DM 초안 생성기 (Hermes Outbound Kit 경량 통합판, stdlib only).

사용:
  python3 gen_drafts.py --profile <profile.json> --leads <leads.csv> --out <out_prefix> [--date YYMMDD] [--copy-guard] [--use-jev] [--html <panel.html>]
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
if (_REPO_ROOT / "src").is_dir() and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
    try:
        import src as _src_bootstrap  # noqa: F401
    except Exception:
        pass


def _csv_safe(v: Any) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s and s[0] in ("=", "+", "-", "@", "\t", "\r") else s


def match(when: dict[str, Any] | None, row: dict[str, Any]) -> bool:
    for k, pat in (when or {}).items():
        if k.startswith("_"):
            continue
        v = row.get(k.strip(), "") or ""
        for single in (pat if isinstance(pat, list) else [pat]):
            if isinstance(single, str):
                neg = single.startswith("!")
                if bool(re.search(single[1:] if neg else single, v, re.I)) == neg:
                    return False
    return True


def clean_name(s: str) -> str:
    s = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|사단법인|\(재\)|재단법인|^\(?주\)\s*", "", s or "")
    s = re.sub(r"\s*\([^)]*$", "", s)
    s = re.sub(r"\s*\([A-Za-z0-9 .,&'-]+\)\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_detail(d: str, lead: str) -> str:
    t = d or ""
    for n in {lead, clean_name(lead)}:
        if n and len(n) > 1:
            t = t.replace(n, "")
    t = re.sub(r"\[[^\]]*\]|【[^】]*】|<[^>]*>|[.!?]+|채용\s*공고|채용합니다|모집합니다|모십니다", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–:|/·,")
    t = re.sub(r"\s*(채용|모집|구인)$", "", t)
    return re.sub(r"\s+(를|을|의)$", "", t).strip()


def pick(key: str, opts: list[str]) -> str:
    return opts[int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16) % len(opts)]


def _apply_fixes(text: str, fixes: list[list[str]]) -> str:
    for x, y in fixes:
        text = text.replace(x, y)
    return text


def _build_dm(lead: str, dm_intro: str, trig: str, q: str, q_short: str, benefit: str, cta: str, fixes: list[list[str]]) -> str:
    head = f"안녕하세요, {lead} 담당자님. {dm_intro}".strip()
    cands = [
        [head, trig, q, benefit, cta],
        [head, trig, q_short, benefit, cta],
        [head, q_short, benefit, cta],
        [head, trig, q_short, cta],
    ]
    for seq in cands:
        dm = _apply_fixes("\n".join(l for l in seq if l), fixes)
        if len(dm) <= 300:
            return dm
    return _apply_fixes("\n".join(l for l in cands[-1] if l), fixes)[:300]


def generate_drafts(
    profile: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    date_str: str | None = None,
    use_copy_guard: bool = False,
    use_jev: bool = False,
    home: str | Path | None = None,
    jev_opener=None,
) -> list[dict[str, Any]]:
    date_val = date_str or datetime.date.today().strftime("%y%m%d")
    P = profile
    fixes = P.get("fix", [])
    cg = None
    if use_copy_guard or use_jev:
        try:
            import copy_guard as cg
        except Exception:
            cg = None

    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        lead = clean_name(r.get("lead", ""))
        rid = r.get("id") or str(i + 1)
        if not lead:
            continue

        site = (r.get("site") or "").strip()
        raw_signal = (r.get("signal") or "default").strip()
        raw_detail = (r.get("detail") or "").strip()
        ev = {
            "signal": raw_signal,
            "site": site,
            "detail": raw_detail,
            "evidence_url": (r.get("evidence_url") or r.get("url") or "").strip(),
            "homepage": (r.get("homepage") or r.get("hp") or "").strip(),
            "evidence_date": (r.get("evidence_date") or r.get("published_at") or "").strip(),
            "evidence_excerpt": (r.get("evidence_excerpt") or r.get("excerpt") or "").strip(),
            "industry": (r.get("industry") or "").strip(),
            "role": (r.get("role") or "").strip(),
            "size": (r.get("size") or "").strip(),
            "channels": (r.get("channels") or "").strip(),
        }

        if P.get("skip_when") and match(P["skip_when"], r):
            out.append({"id": rid, "lead": lead, "angle": "skip", "subject": "", "body": P.get("skip_note", ""), "dm": "", "flags": "", "qa_score": 100, **ev})
            continue

        ang = next((g for g in P["angles"] if match(g.get("when"), r)), P["angles"][-1])
        feat = next((f for f in P.get("features", []) if match(f.get("when"), r)), None)

        sig = raw_signal
        detail = clean_detail(raw_detail, r.get("lead", ""))
        if sig == "hire" and not (4 <= len(detail) <= 30):
            sig = "hire_nodetail"
        trig = str(ang["trigger_default"]) if (sig == "default" and ang.get("trigger_default")) else P["triggers"].get(sig, P["triggers"]["default"])
        trig = (
            trig.replace("{site}에 ", f"{site}에 " if site else "")
            .replace("{site}에서 ", f"{site}에서 " if site else "")
            .replace("{site}", site)
            .replace("{detail}", detail)
            .strip()
        )
        if "''" in trig or '""' in trig:
            trig = str(ang.get("trigger_default") or P["triggers"].get("default", trig))

        q = (r.get("question") or "").strip()
        q_short = q or ang["question"]
        if not q:
            by_sig = ang.get("lead_in_by_signal") if isinstance(ang.get("lead_in_by_signal"), dict) else {}
            lead_in = (r.get("lead_in") or "").strip() or str(by_sig.get(sig, "")).strip()
            if not lead_in and (sig.startswith("hire") or sig in ("tender", "funding", "platform", "linkedin", "default")):
                lead_in = (ang.get("lead_in") or "").strip()
            q = f"{lead_in}, {ang['question']}" if lead_in else ang["question"]

        ben = [x.strip() for x in r["benefit"].split(" / ")] if r.get("benefit") else list(ang["benefit"])
        if feat:
            append_mode = (bool(feat.get("append")) or len(ben) < 2) and not (feat.get("replace_also") is True and len(ben) >= 2)
            if append_mode:
                ben.append(feat["text"])
            else:
                ben[-1] = "또한, " + feat["text"]

        def_key = feat["def"] if (feat and feat.get("def") and ang.get("def", "default") in ("default", "ai")) else ang.get("def", "default")
        def_sentence = ""
        if (r.get("known") or "").lower() not in ("y", "yes", "1"):
            def_sentence = P.get("defs", {}).get(def_key, "")
            if def_sentence:
                ben.insert(0, def_sentence)

        cta = (r.get("cta") or ang.get("cta") or pick(rid + lead, P["ctas"])).replace("{lead}", lead)
        owner = ang.get("owner_label") or P["owner_label"]
        who = owner if (P["company"] in owner or P["company"] == P["product"]) else f"{P['company']} {owner}"
        intro_tpl = (P.get("sender_intro") or "").strip()
        intro = intro_tpl.replace("{sender}", P["sender"]).replace("{company}", P["company"]).replace("{owner}", owner) if intro_tpl else f"{who} 담당자 {P['sender']}입니다."
        dm_intro_tpl = (P.get("dm_intro") or "").strip()
        dm_intro = dm_intro_tpl.replace("{sender}", P["sender"]).replace("{company}", P["company"]).replace("{owner}", owner) if dm_intro_tpl else intro

        body = _apply_fixes(
            f"안녕하세요. {lead} 담당자님,\n{intro}\n\n"
            + f"{trig}\n{q}".replace(". ", ".\n")
            + "\n\n" + " ".join(ben).replace(". ", ".\n")
            + "\n\n" + cta.replace(". ", ".\n")
            + "\n\n" + P["sign"].replace("{sender}", P["sender"]),
            fixes,
        )
        subject = P["subject"].format(company=P["company"], lead=lead, product=ang.get("product") or P["product"], date=date_val)
        core_ben = ang.get("dm_benefit") or (ben[1] if (len(ben) > 1 and def_sentence and ben[0] == def_sentence) else ben[0])
        cta_short = (ang.get("dm_cta") or P.get("dm_cta") or cta.split(". ")[0].rstrip(".") + ".").replace("{lead}", lead)
        dm = _build_dm(lead, dm_intro, trig, q, q_short, core_ben, cta_short, fixes)

        chk = body
        for n in (lead, r.get("lead", ""), detail, raw_detail):
            if n:
                chk = chk.replace(n, "")
        flags = [w for w in P.get("banned", []) if w in chk]
        if re.search(r"\[(회사명|기관명|사업명|공고 제목|확인 필요|발신|제품명|각도)", body):
            flags.append("자리표시")
        if "—" in body or "–" in body:
            flags.append("대시금지(—/–)")
        if chk.count("·") >= 3:
            flags.append("가운뎃점과다(·)")

        qa_score = max(0, 100 - len(flags) * 20)
        qa_detail = None
        if cg is not None:
            qa_detail = cg.lint_copy(
                body, subject=subject, language="ko", channel="email", touch_number=1,
                preserve_user_voice=True, use_jev=use_jev,
                record={"company": lead, "title": raw_detail or trig, "description": ev["evidence_excerpt"] or raw_detail, "url": ev["evidence_url"] or ev["homepage"]},
                home=home, opener=jev_opener,
            )
            qa_score = qa_detail.get("score", qa_score)
            flags.extend(qa_detail.get("issues") or [])
            if use_jev and isinstance(qa_detail.get("jev_qa"), dict):
                flags.extend(f"[Jev]{f}" for f in (qa_detail["jev_qa"].get("flags") or []))

        item: dict[str, Any] = {
            "id": rid, "lead": lead, "angle": ang["key"] + (f"+{feat['key']}" if feat else ""),
            "subject": subject, "body": body, "dm": dm,
            "flags": " | ".join(dict.fromkeys(flags)), "qa_score": qa_score, **ev,
        }
        if qa_detail is not None:
            item["qa"] = qa_detail
        out.append(item)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="범용 콜드메일·DM 초안 생성기 (근거 교차검증 지원)")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--leads", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--date", default=datetime.date.today().strftime("%y%m%d"))
    ap.add_argument("--copy-guard", action="store_true")
    ap.add_argument("--use-jev", action="store_true")
    ap.add_argument("--home")
    ap.add_argument("--html", help="근거 교차검증 HTML 패널 출력 경로")
    args = ap.parse_args(argv)

    with open(args.profile, encoding="utf-8-sig") as pf:
        profile = json.load(pf)
    with open(args.leads, encoding="utf-8-sig") as lf:
        rows = list(csv.DictReader(lf))

    out = generate_drafts(profile, rows, date_str=args.date, use_copy_guard=args.copy_guard, use_jev=args.use_jev, home=args.home)
    out_prefix = Path(args.out).expanduser().absolute()
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path, csv_path = Path(f"{out_prefix}.json"), Path(f"{out_prefix}.csv")
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    cols = ["id", "lead", "angle", "signal", "site", "detail", "evidence_url", "homepage", "evidence_date", "evidence_excerpt", "subject", "body", "dm", "qa_score", "flags"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as cf:
        w = csv.DictWriter(cf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in out:
            w.writerow({k: _csv_safe(row.get(k, "")) for k in cols})

    html_msg = ""
    if args.html:
        import review_panel
        panel = review_panel.build_review_panel_from_drafts(out, args.html, title=f"{profile.get('company', '')} · {profile.get('product', '콜드메일 초안')} 근거 교차검증 패널".strip(" ·"))
        html_msg = f" | panel -> {panel}"
    print(f"drafts {len(out)} | flagged {sum(1 for o in out if o['flags'])} | skipped {sum(1 for o in out if o['angle'] == 'skip')} -> {json_path}, {csv_path}{html_msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
