"""Tests for PR #6:
- env_helper.py (`outbound.py env status/set/unset`)
- audio_transcribe.py (`outbound.py transcribe` & `meeting post --audio-file`, Cloudflare UA, retry, missing key)
- public_data_lens.py (`outbound.py lens`, pure-Python YAML fallback, direct MCP `search`/`plan-data`/`columns`/`dataset` with X-Datanav-No-Log: 1 and PII blocking)
- market_intel.py live RSS/Atom & HTML/Crawl4AI crawling + stateful baseline diff
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
import audio_transcribe  # noqa: E402
import env_helper  # noqa: E402
import market_intel  # noqa: E402
import meeting_and_health  # noqa: E402
import outbound  # noqa: E402
import public_data_lens  # noqa: E402


class _MockResponse:
    def __init__(self, body: bytes, content_type: str = "application/json", status: int = 200, headers: dict | None = None):
        self._buf = io.BytesIO(body)
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.status = status

    def read(self, amt: int = -1) -> bytes:
        return self._buf.read(amt)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestEnvHelperAndPlaudGroqTranscribe(unittest.TestCase):
    def test_env_set_status_unset_never_leaks_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            added = env_helper.set_env_value("DATA_GO_KR_API_KEY", "test-datagokr-secret-123", home=home)
            self.assertEqual(added["status"], "added")
            self.assertTrue(added["value_redacted"])

            updated = env_helper.set_env_value("DATA_GO_KR_API_KEY", "test-datagokr-secret-456", home=home)
            self.assertEqual(updated["status"], "updated")

            with mock.patch.dict(os.environ, {"DATA_GO_KR_API_KEY": ""}, clear=False):
                diag = env_helper.env_diagnostics(home)
            row = next(r for r in diag["keys"] if r["key"] == "DATA_GO_KR_API_KEY")
            self.assertTrue(row["configured"])
            self.assertEqual(row["source"], ".env")
            self.assertNotIn("test-datagokr-secret", json.dumps(diag))

            removed = env_helper.unset_env_value("DATA_GO_KR_API_KEY", home=home)
            self.assertEqual(removed["status"], "removed")

    def test_plaud_groq_transcribe_and_meeting_post_audio_integration(self):
        captured_requests: list[tuple[str, dict[str, str], bytes]] = []

        class _GroqOpener:
            def open(self, req, timeout=300):
                hdrs = {k.lower(): v for k, v in req.header_items()}
                captured_requests.append((req.full_url, hdrs, req.data or b""))
                return _MockResponse(
                    json.dumps({"text": "다음 주 수요일까지 보안 아키텍처 1장 요약과 PoC 일정표를 공유하기로 합의했습니다."}).encode("utf-8"),
                    content_type="application/json",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            vault = root / "vault"
            audio_file = root / "plaud-meeting.mp3"
            audio_file.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x10fake-mp3-payload-bytes")

            # 1) Missing GROQ_API_KEY returns transparent hint
            with mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "HERMES_HOME": str(home)}, clear=False):
                missing = audio_transcribe.transcribe_audio(audio_file, home=home)
            self.assertEqual(missing["status"], "missing_key")
            self.assertIn("GROQ_API_KEY", missing["hint"])

            # 2) With GROQ_API_KEY in $HERMES_HOME/.env -> sends Cloudflare-safe UA & saves transcript
            env_helper.set_env_value("GROQ_API_KEY", "test-groq-whisper-key-999", home=home)
            out_txt = root / "transcripts" / "plaud-meeting.txt"
            with mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "HERMES_HOME": str(home)}, clear=False):
                tr = audio_transcribe.transcribe_audio(
                    audio_file, out_path=out_txt, model="whisper-large-v3-turbo", language="ko", home=home, opener=_GroqOpener()
                )
            self.assertEqual(tr["status"], "ok")
            self.assertTrue(out_txt.is_file())
            self.assertIn("보안 아키텍처", tr["text"])
            self.assertEqual(len(captured_requests), 1)
            _url, hdrs, body = captured_requests[0]
            self.assertIn("chrome/120.0", hdrs.get("user-agent", "").lower())
            self.assertIn(b"whisper-large-v3-turbo", body)

            # 3) End-to-end `outbound.py meeting post --audio-file`
            with mock.patch("audio_transcribe.transcribe_audio", return_value=tr):
                rc = meeting_and_health.main([
                    "post", "--company", "샘플테크", "--attendee", "이이사",
                    "--audio-file", str(audio_file), "--vault", str(vault), "--json",
                ])
            self.assertEqual(rc, 0)


class TestPublicDataLensAndLiveMarketIntel(unittest.TestCase):
    def test_public_data_lens_pure_yaml_fallback_and_direct_mcp_calls(self):
        self.assertIn("lens", outbound.COMMANDS)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            # Test pure-Python YAML fallback when _yaml is None
            with mock.patch.object(public_data_lens, "_yaml", None):
                applied = public_data_lens.apply(home)
                self.assertEqual(applied["status"], "applied_restart_required")
                checked = public_data_lens.check(home)
                self.assertTrue(checked["configured"])
                self.assertTrue(checked["no_log_header"])

        # Mock MCP initialize -> initialized -> tools/call
        seen_headers: list[dict[str, str]] = []

        class _LensOpener:
            def open(self, req, timeout=30):
                hdrs = {k.lower(): v for k, v in req.header_items()}
                seen_headers.append(hdrs)
                payload = json.loads((req.data or b"{}").decode("utf-8"))
                method = payload.get("method")
                if method == "initialize":
                    return _MockResponse(
                        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}}).encode("utf-8"),
                        headers={"Mcp-Session-Id": "sess-lens-01"},
                    )
                if method == "notifications/initialized":
                    return _MockResponse(b"", headers={"Mcp-Session-Id": "sess-lens-01"})
                if method == "tools/call":
                    params = payload.get("params") or {}
                    return _MockResponse(
                        json.dumps({
                            "jsonrpc": "2.0",
                            "id": 2,
                            "result": {
                                "structuredContent": {
                                    "data": {"tool": params.get("name"), "evidenceLevel": "DRAFT"},
                                    "meta": {"sourceSnapshot": "2026-06", "schemaVersion": "1.6.0"},
                                    "warnings": [],
                                }
                            },
                        }).encode("utf-8"),
                        headers={"Mcp-Session-Id": "sess-lens-01"},
                    )
                raise AssertionError(f"Unexpected MCP method: {method}")

        plan_res = public_data_lens.build_data_plan(
            "제조 스마트팩토리 잠재고객 발굴을 위해 공장등록·산업단지 공공데이터 결합 계획",
            opener=_LensOpener(),
        )
        self.assertEqual(plan_res["status"], "ok")
        self.assertEqual(plan_res["record_type"], "public_dataset_catalog")
        self.assertEqual(plan_res["evidence_level"], "DRAFT")
        self.assertFalse(plan_res["procurement_notice"])
        self.assertTrue(all(h.get("x-datanav-no-log") == "1" for h in seen_headers))

        # PII / email in query must be blocked before any network call
        with self.assertRaises(public_data_lens.PublicDataLensError):
            public_data_lens.search_datasets("고객 연락처 test@example.com 조회")

    def test_market_intel_live_rss_web_and_stateful_diff(self):
        rss_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<rss version='2.0'><channel><title>GlobalAssist News</title>"
            "<item><title>Offshore Energy Expat Medical Evacuation Case</title>"
            "<link>https://competitor.example.com/cases/offshore-1</link>"
            "<description>24/7 duty of care and emergency evacuation for offshore crew.</description>"
            "<pubDate>2026-10-01</pubDate></item>"
            "</channel></rss>"
        ).encode("utf-8")

        class _RssOpener:
            def open(self, req, timeout=20):
                return _MockResponse(rss_xml, content_type="application/rss+xml")

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            loaded1 = market_intel.load_competitor_signals(
                rss_urls=["https://competitor.example.com/feed.xml"],
                competitor_name="GlobalAssist",
                opener=_RssOpener(),
            )
            self.assertEqual(len(loaded1["signals"]), 1)
            out1 = market_intel.export_market_intel_to_vault(loaded1, vault, initialize=True)
            self.assertEqual(out1["new_signals_count"], 0)

            # Second run with 1 new case study added -> new_signals_count == 1
            loaded2 = market_intel.load_competitor_signals(
                records=[
                    *loaded1["signals"],
                    {
                        "competitor": "GlobalAssist",
                        "industry": "EPC 건설",
                        "title": "Middle East Plant Expat Medical Support",
                        "url": "https://competitor.example.com/cases/me-plant-2",
                    },
                ]
            )
            out2 = market_intel.export_market_intel_to_vault(loaded2, vault, initialize=False)
            self.assertEqual(out2["signal_count"], 2)
            self.assertEqual(out2["new_signals_count"], 1)

    def test_runtime_connect_works_without_pyyaml_and_sources_is_modular(self):
        import runtime_connect
        import sources
        import sources_ats
        import sources_common
        import sources_kr_jobs
        import sources_signals

        # Verify sources.py is now a slim facade (<350 lines) backed by focused modules
        sources_lines = len((ROOT / "src" / "core" / "sources.py").read_text(encoding="utf-8").splitlines())
        self.assertLess(sources_lines, 350)
        self.assertIs(sources.collect_wanted, sources_kr_jobs.collect_wanted)
        self.assertIs(sources.collect_ats_batch, sources_ats.collect_ats_batch)
        self.assertIs(sources.collect_funding, sources_signals.collect_funding)
        self.assertIs(sources.fetch_json, sources_common.fetch_json)

        # Verify runtime_connect.apply_services works when PyYAML (_yaml) is None!
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            data = {
                "services": ["groq", "composio", "firecrawl", "jev"],
                "groq_audio_consent": True,
                "composio_scope_ack": True,
                "jev_enabled": True,
            }
            with mock.patch.object(runtime_connect, "_yaml", None):
                res1 = runtime_connect.apply_services(data, home)
                self.assertTrue((home / "config.yaml").is_file())
                self.assertTrue((home / "outbound-connectors.json").is_file())
                # Re-applying idempotently without PyYAML must read back config.yaml and succeed
                res2 = runtime_connect.apply_services(data, home)
                self.assertEqual(len(res1), len(res2))
                loaded_cfg = runtime_connect._read_yaml(home / "config.yaml")
                self.assertEqual(loaded_cfg["stt"]["provider"], "groq")
                self.assertEqual(loaded_cfg["mcp_servers"]["composio"]["enabled"], True)

    def test_knowledge_base_icp_skills_and_learnings_json_gate(self):
        import reply_tracker

        # 1) All 6 skills reference the vault knowledge base for ICP/targeting/scoring
        skill_checks = {
            "outbound": ["볼트 지식베이스 먼저 읽기", ".learnings.json", "gtm-icp-brief"],
            "gtm-icp-brief": ["볼트 지식베이스 먼저 읽기", "빈 칸만"],
            "outbound-scoring": ["볼트 지식베이스 먼저 읽기", "20건 이상"],
            "lead-prospecting": ["볼트 지식베이스 먼저 읽기", "경쟁사 비교와 영업 판단.md"],
            "profile-customizer": ["볼트 지식베이스 먼저 읽기", "do-not-contact.txt"],
            "linkedin-cold-messaging": ["볼트 지식베이스 먼저 읽기", "구매 결정자"],
        }
        for skill_name, markers in skill_checks.items():
            text = (ROOT / "pack" / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
            for marker in markers:
                self.assertIn(marker, text, f"{skill_name} missing marker: {marker}")

        # 2) GTM/.learnings.json accumulates signal replies and gates weight tuning at >= 20
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            batch1 = [
                {
                    "lead_id": f"h-{i}",
                    "company": f"채용기업{i}",
                    "subject": "Re: 문의",
                    "body": "네, 미팅 가능할까요? 관심 있습니다.",
                    "signal_type": "채용 공고",
                }
                for i in range(12)
            ] + [
                {
                    "lead_id": f"f-{i}",
                    "company": f"투자기업{i}",
                    "subject": "Re: 문의",
                    "body": "지금은 시기가 아닙니다.",
                    "signal_type": "funding",
                }
                for i in range(5)
            ]
            res1 = reply_tracker.score_campaign_replies(batch1, total_sent=200, campaign_name="wave-1", vault=vault)
            self.assertEqual(res1["learnings_summary"]["eligible_signals_for_weight_tuning"], [])
            learn_json = json.loads((vault / "GTM" / ".learnings.json").read_text(encoding="utf-8"))
            self.assertEqual(learn_json["signals"]["hiring"]["net_replies"], 12)
            self.assertFalse(learn_json["signals"]["hiring"]["eligible_for_weight_tuning"])

            # Second wave pushes hiring replies to 22 (>= 20), unlocking weight tuning for hiring only
            batch2 = [
                {
                    "lead_id": f"h2-{i}",
                    "company": f"채용기업2-{i}",
                    "subject": "Re: 문의",
                    "body": "자료 먼저 부탁드립니다.",
                    "signal_type": "hiring",
                }
                for i in range(10)
            ]
            res2 = reply_tracker.score_campaign_replies(batch2, total_sent=200, campaign_name="wave-2", vault=vault)
            self.assertEqual(res2["learnings_summary"]["eligible_signals_for_weight_tuning"], ["hiring"])
            learn_json2 = json.loads((vault / "GTM" / ".learnings.json").read_text(encoding="utf-8"))
            self.assertEqual(learn_json2["signals"]["hiring"]["net_replies"], 22)
            self.assertTrue(learn_json2["signals"]["hiring"]["eligible_for_weight_tuning"])
            self.assertFalse(learn_json2["signals"]["funding"]["eligible_for_weight_tuning"])


if __name__ == "__main__":
    unittest.main()

