#!/usr/bin/env python3
"""review_panel.py — 경량 오프라인 근거 교차검증 HTML 패널 생성기 (stdlib only, 단일 HTML)."""
from __future__ import annotations

from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import argparse
import html
import json
from pathlib import Path
import re
from typing import Any


def _safe_json_for_script(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _item(rid: Any, lead: Any, **kw: Any) -> dict[str, Any]:
    return {
        "id": str(rid), "lead": str(lead), "angle": str(kw.get("angle") or "default"),
        "signal": str(kw.get("signal") or ""), "site": str(kw.get("site") or ""), "detail": str(kw.get("detail") or ""),
        "evidence_url": str(kw.get("evidence_url") or ""), "homepage": str(kw.get("homepage") or ""),
        "evidence_date": str(kw.get("evidence_date") or ""), "evidence_excerpt": str(kw.get("evidence_excerpt") or ""),
        "industry": str(kw.get("industry") or ""), "role": str(kw.get("role") or ""), "size": str(kw.get("size") or ""),
        "subject": str(kw.get("subject") or ""), "body": str(kw.get("body") or ""), "dm": str(kw.get("dm") or ""),
        "qa_score": kw.get("qa_score", 100), "flags": list(kw.get("flags") or []),
    }


def _from_drafts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            continue
        fl = r.get("flags") or ""
        flags = [x.strip() for x in fl.split("|") if x.strip()] if isinstance(fl, str) else list(fl)
        out.append(_item(
            r.get("id") or i, r.get("lead") or r.get("company") or f"리드 #{i}",
            angle=r.get("angle") or r.get("action"), signal=r.get("signal"), site=r.get("site"),
            detail=r.get("detail"), evidence_url=r.get("evidence_url") or r.get("url"), homepage=r.get("homepage"),
            evidence_date=r.get("evidence_date"), evidence_excerpt=r.get("evidence_excerpt"),
            industry=r.get("industry"), role=r.get("role"), size=r.get("size"),
            subject=r.get("subject"), body=r.get("body"), dm=r.get("dm"),
            qa_score=r.get("qa_score", (r.get("qa") or {}).get("score", 100)), flags=flags,
        ))
    return out


def _from_workflow(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for run in (data.get("runs") if isinstance(data.get("runs"), list) else [data]):
        if not isinstance(run, dict):
            continue
        scores = run.get("scores") or {}
        for i, rec in enumerate(run.get("records") or [], 1):
            sid = rec.get("source_id") or str(i)
            sc = scores.get(sid) or {}
            jev = sc.get("jev") if isinstance(sc.get("jev"), dict) else {}
            dqa = sc.get("draft_qa") if isinstance(sc.get("draft_qa"), dict) else {}
            flags = list(dqa.get("flags") or [])
            if jev.get("disagreement_note"):
                flags.append(f"[채점주의] {jev['disagreement_note']}")
            out.append(_item(
                sid, rec.get("company") or rec.get("company_candidate") or f"계정 #{i}",
                angle=sc.get("action") or "리서치 필요", signal=rec.get("record_type"), site=rec.get("source"),
                detail=rec.get("title"), evidence_url=rec.get("url"), evidence_date=rec.get("published_at"),
                evidence_excerpt=rec.get("description"), industry=rec.get("sector_candidate"),
                role=", ".join(rec.get("stack") or []), size=rec.get("location"),
                subject=f"{rec.get('company') or ''} {str(rec.get('title') or '')[:24]} 관련".strip(),
                body=f"(Obsidian Drafts 확인 · 근거: {rec.get('url') or ''})\n\n근거 설명: {sc.get('rationale') or ''}",
                qa_score=sc.get("fit_score") if sc.get("fit_score") is not None else 0, flags=flags,
            ))
    return out


def _from_vault(vault_dir: Path) -> list[dict[str, Any]]:
    d = vault_dir / "Drafts"
    if not d.is_dir():
        return []
    out = []
    for path in sorted(d.glob("*.md")):
        txt = path.read_text(encoding="utf-8", errors="replace")
        m = lambda rx: (re.search(rx, txt, re.M).group(1).strip() if re.search(rx, txt, re.M) else "")
        sig_m = re.search(r"\*\*관측 신호\*\*:\s*`([^`]+)`\s*·\s*(.+)", txt)
        body = (txt.split("## 초안 본문", 1)[1] if "## 초안 본문" in txt else txt).split("<!-- user-notes:start -->", 1)[0].strip()
        qa_str = m(r"\*\*QA/Jev 점검 주의\*\*:\s*(.+)")
        flags = [x.strip() for x in qa_str.split(",") if x.strip()] if qa_str else []
        out.append(_item(
            path.stem, m(r"^#\s*Draft template\s*[—-]\s*(.+)$") or path.stem,
            angle=m(r"권장 액션:\s*`([^`]+)`") or "review",
            signal=sig_m.group(1) if sig_m else "", site="Obsidian Vault",
            detail=sig_m.group(2).strip() if sig_m else "",
            evidence_url=m(r"\[원문 바로 열기\]\((https?://[^)\s]+)\)"),
            evidence_excerpt=m(r"\*\*원문 발췌\*\*:\s*(.+)"),
            subject=m(r"^(?:제목|Subject):\s*(.+)$"), body=body,
            qa_score=80 if not flags else 55, flags=flags,
        ))
    return out


_HTML = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e2e6ec;--ink:#1b2230;--muted:#637083;--accent:#2563eb;--ok:#15803d;--warn:#b45309;--bad:#b91c1c;--soft:#eef2ff}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.5}
header{background:#fff;border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
header h1{margin:0;font-size:15px}.bar,.acts,.flts{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.pill{padding:2px 8px;border-radius:999px;font-size:12px;border:1px solid var(--line);background:#fff;color:var(--muted)}
.pill.ok{border-color:#bbf7d0;background:#f0fdf4;color:var(--ok)}.pill.warn{border-color:#fde68a;background:#fffbeb;color:var(--warn)}.pill.bad{border-color:#fecaca;background:#fef2f2;color:var(--bad)}
.btn{padding:5px 10px;border-radius:7px;border:1px solid var(--line);background:#fff;color:var(--ink);cursor:pointer;font-size:12px;font-weight:600}
.btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}.btn.ok{background:var(--ok);color:#fff;border-color:var(--ok)}.btn.warn{background:var(--warn);color:#fff;border-color:var(--warn)}.btn.bad{background:var(--bad);color:#fff;border-color:var(--bad)}
.grid{display:grid;grid-template-columns:270px 1fr 360px;gap:10px;padding:10px;min-height:calc(100vh - 54px)}
@media(max-width:1100px){.grid{grid-template-columns:1fr}}
.panel{background:#fff;border:1px solid var(--line);border-radius:9px;padding:12px;display:flex;flex-direction:column;gap:8px}
.flts button{padding:3px 7px;border-radius:6px;border:1px solid var(--line);background:#fff;font-size:11px;cursor:pointer}.flts button.active{background:var(--ink);color:#fff;border-color:var(--ink)}
.list{display:flex;flex-direction:column;gap:5px;overflow-y:auto;max-height:calc(100vh - 170px)}
.item{padding:8px 9px;border:1px solid var(--line);border-radius:7px;cursor:pointer;text-align:left;background:#fff}.item.active{border-color:var(--accent);background:var(--soft)}
.item-top{display:flex;justify-content:space-between;align-items:center;gap:6px}.item-sub{font-size:11px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
label.lbl{font-size:12px;font-weight:700;color:var(--muted);display:flex;justify-content:space-between}
input.f,textarea.f{width:100%;padding:8px 9px;border:1px solid var(--line);border-radius:7px;font-family:inherit;font-size:13.5px;line-height:1.55}
textarea.f{min-height:230px;resize:vertical}textarea.f.dm{min-height:105px}
.box{border:1px solid var(--line);border-radius:7px;padding:9px;background:#fafbfc}.box h3{margin:0 0 6px;font-size:13px}
.row{font-size:12.5px;margin:3px 0;word-break:break-word}.ev-link{display:inline-block;padding:4px 9px;border-radius:6px;background:var(--soft);color:var(--accent);text-decoration:none;font-weight:600;font-size:12px;margin:3px 5px 3px 0}
.exc{background:#fff;border-left:3px solid var(--accent);padding:7px 9px;border-radius:4px;font-size:12.5px;margin-top:5px;white-space:pre-wrap}
.chk label{display:flex;gap:6px;font-size:12.5px;margin:4px 0;cursor:pointer}.fl{margin:4px 0 0;padding-left:17px;color:var(--bad);font-size:12.5px}
.note{font-size:11.5px;color:var(--muted);background:#f8fafc;border:1px dashed var(--line);padding:6px 8px;border-radius:6px}
</style></head><body>
<header><h1>__TITLE__</h1><div class="bar">
  <span class="pill" id="st-all">전체 0</span><span class="pill ok" id="st-ok">승인 0</span><span class="pill warn" id="st-fl">점검주의 0</span>
  <button class="btn" id="exp-json">JSON 저장</button><button class="btn primary" id="exp-csv">CSV 저장</button>
</div></header>
<div class="grid">
  <aside class="panel">
    <input class="f" id="q" placeholder="회사명·신호·각도 검색...">
    <div class="flts" id="flts"><button data-f="all" class="active">전체</button><button data-f="flagged">주의</button><button data-f="pending">대기</button><button data-f="approved">승인</button><button data-f="needs_edit">수정</button><button data-f="rejected">제외</button></div>
    <div class="list" id="list"></div>
  </aside>
  <main class="panel">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
      <div><strong id="c-lead" style="font-size:15px">-</strong> <span class="pill" id="c-ang">-</span> <span class="pill" id="c-st">pending</span></div>
      <div class="acts"><button class="btn ok" id="m-ok">승인</button><button class="btn warn" id="m-ed">수정필요</button><button class="btn bad" id="m-no">제외</button></div>
    </div>
    <label class="lbl"><span>이메일 제목</span><span id="l-s">0자</span></label><input class="f" id="e-s">
    <label class="lbl"><span>이메일 본문 (자동 발송 없음)</span><span id="l-b">0자</span></label><textarea class="f" id="e-b"></textarea>
    <div class="acts"><button class="btn" id="cp-e">제목+본문 복사</button><button class="btn" id="rst">원본 복원</button></div>
    <label class="lbl"><span>DM / 링크드인 (300자 이내)</span><span id="l-d">0자</span></label><textarea class="f dm" id="e-d"></textarea>
    <div class="acts"><button class="btn" id="cp-d">DM 복사</button></div>
    <div class="note">자동 발송 없음. 오른쪽 근거 원문 링크를 직접 열어 확인 후 발송하세요. 영리 목적 메일은 발송 전 정보통신망법 제50조((광고)·수신거부·사전동의)를 확인하세요.</div>
  </main>
  <section class="panel">
    <div class="box"><h3>1. 근거 원문 링크 (수작업 교차검증)</h3><div id="ev-links"></div>
      <div class="row"><strong>신호:</strong> <span id="ev-sig">-</span> · <strong>출처/일자:</strong> <span id="ev-src">-</span></div>
      <div class="row"><strong>제목:</strong> <span id="ev-det">-</span></div>
      <div class="row"><strong>업종·직무·규모:</strong> <span id="ev-meta">-</span></div>
      <div class="exc" id="ev-exc">-</div>
    </div>
    <div class="box"><h3>2. 자동 QA · 실시간 교차검증</h3>
      <div class="row"><strong>초기 QA:</strong> <span id="qa-sc">-</span> · <strong>근거 키워드 반영:</strong> <span id="ev-ov">-</span></div>
      <ul class="fl" id="qa-fl"></ul>
    </div>
    <div class="box chk"><h3>3. 사람 교차검증 체크리스트</h3>
      <label><input type="checkbox" data-c="id"> 회사명·도메인 동일성 확인</label>
      <label><input type="checkbox" data-c="ev"> 원문 링크 사실과 초안 첫 줄 일치</label>
      <label><input type="checkbox" data-c="fl"> 높임 주어·문장 인과/흐름 자연스러움</label>
      <label><input type="checkbox" data-c="law"> 수신 대상·광고/수신거부 규정 확인</label>
      <input class="f" id="e-m" style="margin-top:6px" placeholder="검토 메모...">
    </div>
  </section>
</div>
<script>
const INIT=__ITEMS_JSON__,KEY="hermes_rp_v1_"+location.pathname;
const sv=(()=>{try{return JSON.parse(localStorage.getItem(KEY)||"{}")}catch{return{}}})();
const S={items:INIT.map(x=>{const s=sv[x.id]||{};return{...x,_s:x.subject,_b:x.body,_d:x.dm,subject:s.subject??x.subject,body:s.body??x.body,dm:s.dm??x.dm,status:s.status||"pending",memo:s.memo||"",checks:s.checks||{}}}),id:INIT[0]?.id||null,f:"all",q:""};
const $=id=>document.getElementById(id),safeU=u=>/^https?:\/\//i.test(u||"")?u:"",cur=()=>S.items.find(x=>x.id===S.id)||S.items[0]||null;
const save=()=>{const p={};S.items.forEach(x=>p[x.id]={subject:x.subject,body:x.body,dm:x.dm,status:x.status,memo:x.memo,checks:x.checks});try{localStorage.setItem(KEY,JSON.stringify(p))}catch{}};
function liveLint(s,b,d){const h=[],full=(s||"")+"\n"+(b||"");["않나요?","것 같았습니다","기 쉽습니다","모습을 보여드리","다시 연락드릴 수 있습니다","연락드리느라"].forEach(w=>{if(full.includes(w))h.push("[실시간] 표현/높임 확인: "+w)});if(/[—–]/.test(full))h.push("[실시간] em/en dash(—/–) 제거 권장");if(/\[(회사명|기관명|사업명|확인 필요|이름|회사)\]/.test(full))h.push("[실시간] 자리표시 미치환");if((d||"").length>300)h.push("[실시간] DM 300자 초과("+d.length+"자)");return h}
function checks(){const x=cur();if(!x)return;const s=$("e-s").value,b=$("e-b").value,d=$("e-d").value;const ev=((x.detail||"")+" "+(x.evidence_excerpt||"")).trim();const toks=[...new Set((ev.match(/[가-힣A-Za-z0-9]{2,}/g)||[]).filter(t=>!["채용","공고","관련","대상","진행","운영","담당"].includes(t)))];const hit=toks.filter(t=>b.toLowerCase().includes(t.toLowerCase()));$("ev-ov").textContent=toks.length?(hit.length+"/"+toks.length+"개 ("+hit.slice(0,5).join(", ")+")"):"없음";const fl=$("qa-fl");fl.innerHTML="";const all=[...(x.flags||[]),...liveLint(s,b,d)];(all.length?all:["자동·실시간 점검 이상 없음"]).forEach((t,i)=>{const li=document.createElement("li");if(!all.length)li.style.color="var(--ok)";li.textContent=t;fl.append(li)})}
function lens(){const s=$("e-s").value,b=$("e-b").value,d=$("e-d").value;$("l-s").textContent=s.length+"자";$("l-b").textContent=b.length+"자 (공백제외 "+b.replace(/\s/g,"").length+"자)";$("l-d").textContent=d.length+"자 / 300자";$("l-d").style.color=d.length>300?"var(--bad)":"var(--muted)"}
function render(){
  $("st-all").textContent="전체 "+S.items.length;$("st-ok").textContent="승인 "+S.items.filter(x=>x.status==="approved").length;$("st-fl").textContent="점검주의 "+S.items.filter(x=>(x.flags||[]).length).length;
  const lst=$("list");lst.innerHTML="";const q=S.q.trim().toLowerCase();
  S.items.filter(x=>(S.f==="all"||(S.f==="flagged"?(x.flags||[]).length:x.status===S.f))&&(!q||(x.lead+" "+x.detail+" "+x.angle+" "+x.signal).toLowerCase().includes(q))).forEach(x=>{
    const b=document.createElement("button");b.type="button";b.className="item"+(x.id===S.id?" active":"");
    const t=document.createElement("div");t.className="item-top";const nm=document.createElement("strong");nm.textContent=x.lead;
    const bg=document.createElement("span");bg.className="pill "+(x.status==="approved"?"ok":(x.flags?.length?"bad":""));bg.textContent=x.status==="approved"?"승인":(x.flags?.length?"주의 "+x.flags.length:x.status);
    t.append(nm,bg);const sub=document.createElement("div");sub.className="item-sub";sub.textContent=[x.angle,x.signal,x.detail].filter(Boolean).join(" · ");
    b.append(t,sub);b.onclick=()=>{S.id=x.id;render()};lst.append(b);
  });
  const x=cur();if(!x)return;
  $("c-lead").textContent=x.lead;$("c-ang").textContent=x.angle;$("c-st").textContent=x.status;
  $("e-s").value=x.subject;$("e-b").value=x.body;$("e-d").value=x.dm;$("e-m").value=x.memo;lens();
  const lk=$("ev-links");lk.innerHTML="";
  [["원문 근거 열기 ↗",safeU(x.evidence_url)],["기업 홈페이지 ↗",safeU(x.homepage)]].forEach(([lb,u])=>{if(u){const a=document.createElement("a");a.className="ev-link";a.href=u;a.target="_blank";a.rel="noopener noreferrer";a.textContent=lb;lk.append(a)}});
  if(!lk.childNodes.length){const sp=document.createElement("span");sp.className="pill warn";sp.textContent="원문 URL 없음";lk.append(sp)}
  $("ev-sig").textContent=x.signal||"-";$("ev-src").textContent=[x.site,x.evidence_date].filter(Boolean).join(" · ")||"-";
  $("ev-det").textContent=x.detail||"-";$("ev-meta").textContent=[x.industry,x.role,x.size].filter(Boolean).join(" · ")||"-";
  $("ev-exc").textContent=x.evidence_excerpt||"(원문 발췌 없음 — 링크를 열어 직접 확인)";$("qa-sc").textContent=(x.qa_score??"-")+"점";
  document.querySelectorAll("input[data-c]").forEach(el=>el.checked=Boolean(x.checks?.[el.dataset.c]));checks();
}
$("q").oninput=e=>{S.q=e.target.value;render()};
document.querySelectorAll("#flts button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#flts button").forEach(y=>y.classList.remove("active"));b.classList.add("active");S.f=b.dataset.f;render()});
[["e-s","subject"],["e-b","body"],["e-d","dm"]].forEach(([id,k])=>$(id).oninput=e=>{const x=cur();if(x){x[k]=e.target.value;save();lens();checks()}});
$("e-m").oninput=e=>{const x=cur();if(x){x.memo=e.target.value;save()}};
document.querySelectorAll("input[data-c]").forEach(el=>el.onchange=()=>{const x=cur();if(x){x.checks[el.dataset.c]=el.checked;save()}});
[["m-ok","approved"],["m-ed","needs_edit"],["m-no","rejected"]].forEach(([id,st])=>$(id).onclick=()=>{const x=cur();if(x){x.status=st;save();render()}});
$("rst").onclick=()=>{const x=cur();if(x){x.subject=x._s;x.body=x._b;x.dm=x._d;save();render()}};
$("cp-e").onclick=()=>navigator.clipboard?.writeText("제목: "+$("e-s").value+"\n\n"+$("e-b").value);
$("cp-d").onclick=()=>navigator.clipboard?.writeText($("e-d").value);
const dl=(n,t,m)=>{const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([t],{type:m}));a.download=n;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
const cc=v=>{let s=String(v??"");if(/^[=+\-@\t\r]/.test(s))s="'"+s;return'"'+s.replace(/"/g,'""')+'"'};
$("exp-json").onclick=()=>dl("reviewed-drafts.json",JSON.stringify(S.items,null,2),"application/json");
$("exp-csv").onclick=()=>{const c=["id","lead","status","angle","evidence_url","homepage","subject","body","dm","memo"];dl("reviewed-drafts.csv","\uFEFF"+[c.join(","),...S.items.map(x=>c.map(k=>cc(x[k])).join(","))].join("\n"),"text/csv;charset=utf-8")};
render();
</script></body></html>"""


def render_review_panel_html(items: list[dict[str, Any]], *, title: str = "Hermes Outbound 근거 교차검증 패널") -> str:
    return _HTML.replace("__TITLE__", html.escape(title, quote=True)).replace("__ITEMS_JSON__", _safe_json_for_script(items))


def _write_html(output_html: str | Path, items: list[dict[str, Any]], title: str) -> Path:
    dest = Path(output_html).expanduser().absolute()
    if dest.is_symlink():
        raise ValueError(f"심볼릭 링크에는 쓰지 않습니다: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_review_panel_html(items, title=title), encoding="utf-8")
    return dest


def build_review_panel_from_drafts(drafts: list[dict[str, Any]], output_html: str | Path, *, title: str = "Hermes Outbound 근거 교차검증 패널") -> Path:
    return _write_html(output_html, _from_drafts(drafts), title)


def build_review_panel(*, input_path: str | Path | None = None, vault_dir: str | Path | None = None, output_html: str | Path, title: str = "Hermes Outbound 근거 교차검증 패널") -> dict[str, Any]:
    if input_path:
        raw = json.loads(Path(input_path).expanduser().read_text(encoding="utf-8-sig"))
        items = _from_drafts(raw) if isinstance(raw, list) else _from_workflow(raw) if isinstance(raw, dict) else []
    elif vault_dir:
        items = _from_vault(Path(vault_dir).expanduser().absolute())
    else:
        raise ValueError("--input JSON 또는 --vault 경로 중 하나가 필요합니다.")
    dest = _write_html(output_html, items, title)
    return {"panel": str(dest), "count": len(items)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="개인화 초안·근거 원문 교차검증 단일 HTML 패널 생성기")
    ap.add_argument("--input")
    ap.add_argument("--vault")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="Hermes Outbound 근거 교차검증 패널")
    args = ap.parse_args(argv)
    print(json.dumps(build_review_panel(input_path=args.input, vault_dir=args.vault, output_html=args.out, title=args.title), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
