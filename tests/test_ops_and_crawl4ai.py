"""Tests for PR #5: Crawl4AI-first free JS rendering waterfall and real-world B2B
sales ops system (CRM Kanban sync, draft vs contact history separation, pure-Python
vault integrity audit, 3-stage G2B diff monitor, competitor reverse-engineering intel,
plain-Korean doc linter, daily briefing, and post-install cron verification).
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src  # noqa: E402,F401
import copy_guard  # noqa: E402
import crm_board  # noqa: E402
import daily_briefing  # noqa: E402
import g2b_monitor  # noqa: E402
import kit  # noqa: E402
import linkedin_outbound  # noqa: E402
import market_intel  # noqa: E402
import operations  # noqa: E402
import profile_bootstrap  # noqa: E402
import web_extract  # noqa: E402


class _MockResponse:
    def __init__(self, body: bytes, content_type: str = "application/json", status: int = 200):
        self._buf = io.BytesIO(body)
        self.headers = {"Content-Type": content_type}
        self.status = status

    def read(self, amt: int = -1) -> bytes:
        return self._buf.read(amt)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RoutingOpener:
    def __init__(self, routes: dict[str, tuple[bytes, str]]):
        self.routes = routes
        self.calls: list[str] = []

    def open(self, req, timeout=20):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.calls.append(url)
        for prefix, (payload, ctype) in self.routes.items():
            if url.startswith(prefix):
                return _MockResponse(payload, content_type=ctype)
        raise AssertionError(f"Unexpected URL: {url}")


class TestCrawl4AIFirstWaterfall(unittest.TestCase):
    def test_crawl4ai_http_takes_priority_without_firecrawl_key(self):
        spa_html = b'<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
        c4_resp = json.dumps({
            "results": [{
                "markdown": {"fit_markdown": "# Sample Medical Ops\n\n해외 긴급의료지원 및 환자 후송 실행 서비스입니다."},
                "cleaned_html": "<h1>Sample Medical Ops</h1><p>해외 긴급의료지원</p>",
                "metadata": {"title": "Sample Medical Ops"},
            }]
        }).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".env").write_text("CRAWL4AI_BASE_URL=http://127.0.0.1:11235\n", encoding="utf-8")
            opener = _RoutingOpener({
                "https://spa.example.com": (spa_html, "text/html"),
                "http://127.0.0.1:11235/crawl": (c4_resp, "application/json"),
            })
            with mock.patch.dict(os.environ, {"FIRECRAWL_API_KEY": "", "CRAWL4AI_BASE_URL": "", "HERMES_HOME": str(home)}, clear=False):
                doc = profile_bootstrap.fetch_website(
                    "https://spa.example.com/", "company_site", max_subpages=0, home=home, opener=opener
                )
            self.assertEqual(doc.status, "ok")
            self.assertIn("해외 긴급의료지원", doc.text)
            self.assertTrue(any("127.0.0.1:11235/crawl" in u for u in opener.calls))

    def test_no_renderer_mentions_free_crawl4ai_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with mock.patch("shutil.which", return_value=None), mock.patch("importlib.util.find_spec", return_value=None), mock.patch.dict(
                os.environ, {"FIRECRAWL_API_KEY": "", "CRAWL4AI_BASE_URL": "", "HERMES_HOME": str(home)}, clear=False
            ):
                res = web_extract.render_js_page("https://spa.example.com/", home=home)
            self.assertEqual(res["status"], "js_renderer_unavailable")
            self.assertIn("Crawl4AI", res["hint"])


class TestCRMBoardAuditAndKnowledge(unittest.TestCase):
    def test_intangible_icp_fields_and_plain_korean_knowledge_docs(self):
        base = json.loads((ROOT / "setup.example.json").read_text(encoding="utf-8"))
        base.update({
            "product": "해외 긴급의료지원 및 후송 실행 서비스",
            "end_user_persona": "해외 파견 주재원 및 장기 출장자",
            "buyer_persona": "본사 EHS·안전기획·인사총무 의사결정자",
            "common_misconception": "여행자보험으로 이미 해결된다고 생각하는 오해",
            "reality_differentiator": "보험이 아니라 병원 연결·지급보증·이송을 직접 실행하는 서비스",
            "partial_entry_offer": "특정 국가·프로젝트·한국 귀환 인계 구간부터 작은 시험 운영 제안",
        })
        kit.validate(base)

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            out = crm_board.ensure_knowledge_docs(vault, base)
            self.assertEqual(len(out["written"]), 5)
            self.assertTrue((vault / "Templates" / "Examples" / "LinkedIn Profile Example.md").is_file())

            # Every generated Knowledge doc must pass the plain-Korean tone & table linter!
            for doc_path in (vault / "Knowledge").glob("*.md"):
                lint = copy_guard.lint_document(doc_path.read_text(encoding="utf-8"), path=doc_path.name)
                self.assertTrue(lint["passed"], f"{doc_path.name} failed doc lint: {lint}")

    def test_linkedin_draft_contact_separation_kanban_sync_and_audit(self):
        base = json.loads((ROOT / "setup.example.json").read_text(encoding="utf-8"))
        base["buyer_persona"] = "본사 안전기획팀장"

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            contacts_file = Path(tmp) / "contacts.json"
            contacts_file.write_text(json.dumps([
                {
                    "fullName": "김철수",
                    "companyName": "한빛중공업",
                    "headline": "VP of Safety & EHS",
                    "profileUrl": "https://www.linkedin.com/in/kim-ehs-example",
                    "location": "Seoul",
                },
                {
                    "fullName": "박영희",
                    "companyName": "세움플랜트",
                    "headline": "Head of Global HR Operations",
                    "profileUrl": "https://www.linkedin.com/in/park-hr-example",
                    "recentPost": "해외 파견 인력 안전 관리 체계 개편 회고",
                    "location": "Seoul",
                },
            ], ensure_ascii=False), encoding="utf-8")

            res = linkedin_outbound.run_linkedin_pipeline(base, vault=vault, contacts_file=contacts_file)
            self.assertEqual(res["contacts_count"], 2)
            lead_no_post = vault / "LinkedIn" / "한빛중공업" / "김철수.md"
            self.assertTrue(lead_no_post.is_file())
            lead_text = lead_no_post.read_text(encoding="utf-8")
            self.assertIn('메시지상태: "미발송"', lead_text)
            self.assertIn("연락횟수: 0", lead_text)
            self.assertIn("성향이나 문체는 추정하지 않았습니다", lead_text)

            # Audit must be 100% clean right after generation
            audit1 = crm_board.audit_vault(vault)
            self.assertEqual(audit1["status"], "ok", audit1["issues"])
            self.assertEqual(audit1["summary"]["live_crm_leads"], 2)
            self.assertEqual(audit1["summary"]["crm_board_cards"], 2)
            self.assertEqual(audit1["summary"]["broken_wikilinks"], 0)

            # Explicit stage move + mark_sent increments 연락횟수 and syncs CRM Board.md
            staged = crm_board.update_lead_stage(
                lead_no_post, "컨택함", vault_dir=vault, mark_sent=True, date_str="2026-11-22"
            )
            self.assertEqual(staged["contacts_count"], 1)
            self.assertEqual(staged["board"]["stage_counts"]["컨택함"], 1)
            self.assertEqual(staged["board"]["stage_counts"]["소싱됨"], 1)
            self.assertEqual(crm_board.audit_vault(vault)["status"], "ok")

            # Re-running LinkedIn pipeline must preserve already-contacted lead!
            res2 = linkedin_outbound.run_linkedin_pipeline(base, vault=vault, contacts_file=contacts_file)
            self.assertEqual(res2["vault"]["notes_preserved"], 1)
            meta_after, _b, _e = crm_board.parse_frontmatter(lead_no_post.read_text(encoding="utf-8"))
            self.assertEqual(meta_after["연락횟수"], 1)
            self.assertEqual(meta_after["단계"], "컨택함")

            # Inject real-world failure modes and verify audit_vault catches EVERY single one
            bad_note = vault / "LinkedIn" / "한빛중공업" / "중복리드.md"
            bad_note.write_text(
                "---\n"
                'name: "Jane Cooper"\n'
                'company: "Acme Corp"\n'
                '단계: "소싱됨"\n'
                '메시지상태: "미발송"\n'
                "연락횟수: 2\n"
                'linkedin_url: "https://www.linkedin.com/in/kim-ehs-example"\n'
                "---\n\n"
                "[[존재하지않는노트]]\n\n"
                "| 열1 | 열2 |\n"
                "|---|---|\n"
                "| 값1 | 값2 | 깨진열3 |\n",
                encoding="utf-8",
            )
            audit2 = crm_board.audit_vault(vault)
            self.assertEqual(audit2["status"], "issues_found")
            found_types = {it["type"] for it in audit2["issues"]}
            self.assertTrue({
                "dummy_lead_in_live_crm",
                "duplicate_linkedin_url",
                "unsent_draft_has_contact_history",
                "missing_on_crm_board",
                "broken_wikilink",
                "table_column_mismatch",
            }.issubset(found_types), found_types)


class TestG2BIntelDocLintBriefingAndOps(unittest.TestCase):
    def test_g2b_3stage_baseline_diff_and_noise_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            baseline_items = [
                {
                    "_stage": "order_plan",
                    "orderPlanUntyNo": "OP-001",
                    "bizNm": "공공의료지원센터 편의시설(비즈니스라운지형 카페) 입점업체 선정",
                    "orderInsttNm": "예시공단",
                    "sumOrderAmt": "50000000",
                    "nticeDt": "2026-01-10",
                },
                {
                    "_stage": "order_plan",
                    "orderPlanUntyNo": "OP-002",
                    "bizNm": "해외 파견 인력 긴급 의료지원 및 환자 후송 용역",
                    "orderInsttNm": "예시개발원",
                    "sumOrderAmt": "300000000",
                    "nticeDt": "2026-01-12",
                },
            ]
            r1 = g2b_monitor.run_g2b_monitor(
                keywords=["의료지원", "의료후송"],
                stages=["order_plan"],
                context_keywords=["해외", "파견", "후송"],
                vault_dir=vault,
                initialize=True,
                min_interval=0,
                fixture_items=baseline_items,
            )
            self.assertEqual(r1["total_collected"], 2)
            self.assertEqual(r1["verdict_counts"]["적합"], 1)
            self.assertEqual(r1["verdict_counts"]["제외"], 1)  # cafe notice filtered out!
            self.assertEqual(r1["new_count"], 0)
            self.assertTrue((vault / "Market Intelligence" / "Procurement" / "G2B 발주계획 원장.md").is_file())

            # Second run: OP-002 budget changed + OP-003 new prespec added
            day2_items = [
                baseline_items[0],
                {**baseline_items[1], "sumOrderAmt": "350000000"},
                {
                    "_stage": "prespec",
                    "bfSpecRgstNo": "PS-003",
                    "prdctClsfcNoNm": "해외 출장자 비상대피 및 의료후송 지원 사업",
                    "rlDminsttNm": "예시공기업",
                    "asignBdgtAmt": "220000000",
                    "rgstDt": "2026-01-15",
                },
            ]
            r2 = g2b_monitor.run_g2b_monitor(
                keywords=["의료지원", "의료후송"],
                stages=["order_plan", "prespec"],
                context_keywords=["해외", "파견", "후송", "출장"],
                vault_dir=vault,
                initialize=False,
                min_interval=0,
                fixture_items=day2_items,
            )
            self.assertEqual(r2["new_count"], 1)
            self.assertEqual(r2["changed_count"], 1)
            self.assertEqual(len(r2["new_actionable"]), 1)
            self.assertEqual(len(r2["changed_actionable"]), 1)

            # Market intelligence dedupe & lookalike queue
            loaded = market_intel.load_competitor_signals(records=[
                {"id": "sig-01", "competitor": "GlobalAssist", "industry": "해양플랜트", "title": "Offshore medical evacuation case", "url": "https://example.com/case-1"},
                {"id": "sig-01", "competitor": "GlobalAssist", "industry": "해양플랜트", "title": "Duplicate ID", "url": "https://example.com/case-2"},
                {"id": "sig-02", "competitor": "GlobalAssist", "industry": "해양플랜트", "title": "Duplicate URL", "url": "https://example.com/case-1/"},
                {"id": "sig-03", "competitor": "GlobalAssist", "industry": "EPC 건설", "title": "Expat duty of care program", "url": "https://example.com/case-3"},
            ])
            self.assertEqual(len(loaded["signals"]), 2)
            self.assertEqual(loaded["duplicate_ids_dropped"], 1)
            self.assertEqual(loaded["duplicate_urls_dropped"], 1)
            mi = market_intel.export_market_intel_to_vault(loaded, vault)
            self.assertEqual(mi["signal_count"], 2)
            self.assertTrue((vault / "Market Intelligence" / "Lookalike-Queue.md").is_file())

            # Daily briefing aggregates everything cleanly
            brief = daily_briefing.build_daily_briefing(vault, date_str="2026-11-22")
            self.assertEqual(brief["status"], "ok")
            self.assertEqual(brief["metrics"]["g2b_actionable"], 2)
            self.assertEqual(brief["metrics"]["competitor_signals"], 2)
            self.assertTrue((vault / "Daily" / "2026-11-22-Briefing.md").is_file())

    def test_plain_korean_doc_linter_and_table_checker(self):
        bad_doc = (
            "# 전략 문서\n\n"
            "전장 판단 결과 오버레이 파일럿으로 접근하고 Guarantee of payments를 지원합니다.\n\n"
            "| 구분 | 내용 |\n"
            "|---|---|\n"
            "| 항목1 | 값1 | 추가깨진열 |\n"
        )
        res = copy_guard.lint_document(bad_doc)
        self.assertFalse(res["passed"])
        self.assertGreaterEqual(res["jargon_count"], 4)
        self.assertEqual(res["table_error_count"], 1)

    def test_operations_install_schedule_verify_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "setup.json"
            base = json.loads((ROOT / "setup.example.json").read_text(encoding="utf-8"))
            base.update({"schedule_enabled": True, "schedule_frequency": "daily", "schedule_time": "09:00"})
            cfg_path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
            home, out, vault, state_dir = root / "home", root / "out", root / "vault", root / "state"
            plan = operations.build_plan(cfg_path, home, out, vault, state_dir, "linux")
            # Seed matching manual run-once receipt
            state_dir.mkdir(parents=True, exist_ok=True)
            operations._state_path(state_dir).write_text(json.dumps({
                "schema_version": operations.STATE_VERSION,
                "last_success": {
                    "status": "succeeded",
                    "manual": True,
                    "contract_sha256": plan["contract"]["contract_sha256"],
                },
            }), encoding="utf-8")
            # Redirect descriptor targets into tmp dir so test never touches real ~/.config
            plan["scheduler"]["targets"] = [str(root / "unit.service"), str(root / "unit.timer")]
            fake_runner = mock.Mock(return_value=mock.Mock(returncode=0, stdout="", stderr=""))
            installed = operations.install_schedule(plan, state_dir, apply=True, verify=True, run_command=fake_runner)
            self.assertEqual(installed["status"], "installed")
            self.assertTrue(installed["script_verified"])
            self.assertEqual(installed["manual_verify"]["last_status"], "ok")


if __name__ == "__main__":
    unittest.main()
