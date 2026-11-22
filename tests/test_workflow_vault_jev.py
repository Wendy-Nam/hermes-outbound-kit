"""End-to-end tests for workflow.py, 2-axis scoring, unified Vault + GTM CRM, DNC, CSV safety, and optional Jev."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import src  # noqa: E402,F401

import jev_client  # noqa: E402
import kit  # noqa: E402
import profile  # noqa: E402
import profile_presets  # noqa: E402
import style_analyzer  # noqa: E402
import workflow  # noqa: E402


class _FakeResp:
    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))
        self.status = 200
        self.headers = {}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _MockJevOpener:
    def __init__(self):
        self.calls: list[dict] = []

    def open(self, req, timeout=20):
        payload = json.loads(req.data.decode("utf-8"))
        self.calls.append(payload)
        qs = payload["questions"]
        if "is_relevant" in qs:
            return _FakeResp({
                "model": "jev-latest",
                "answers": {
                    "is_relevant": {"type": "noul", "noul": 0.92},
                    "fit_rubric": {"type": "score", "score": 0.85, "confidence": 0.88},
                    "urgency_rubric": {"type": "score", "score": 0.78, "confidence": 0.81},
                    "recommended_action": {"type": "choice", "choice": "call_now", "confidence": 0.84},
                    "needs_research": {"type": "noul", "noul": 0.12},
                },
                "usage": {"input_tokens": 210, "output_tokens": 0},
            })
        return _FakeResp({
            "model": "jev-latest",
            "answers": {
                "hallucination_risk": {"type": "noul", "noul": 0.05},
                "pushy_or_exaggerated": {"type": "noul", "noul": 0.1},
                "has_clear_single_cta": {"type": "noul", "noul": 0.92},
            },
            "usage": {"input_tokens": 180, "output_tokens": 0},
        })


class TestWorkflowVaultAndJev(unittest.TestCase):
    def test_e2e_2axis_scoring_dnc_diff_gtm_crm_and_formula_safe_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            out = root / "out"
            vault = root / "vault"
            cfg_path = root / "setup.json"
            csv_in = root / "input.csv"
            csv_out = root / "export.csv"

            with csv_in.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["company", "title", "url", "location", "stack", "description"])
                writer.writerow([
                    "알파데이터랩",
                    "시니어 데이터 엔지니어",
                    "https://jobs.example.com/1",
                    "서울 강남",
                    "Snowflake, Airflow, AWS, Python",
                    "시리즈 B SaaS 데이터 플랫폼 구축",
                ])
                writer.writerow([
                    "기존고객DNC",
                    "AI 엔지니어",
                    "https://jobs.example.com/2",
                    "서울",
                    "Python, AWS",
                    "이미 계약한 고객사",
                ])
                writer.writerow([
                    "=CMD('calc')",
                    "데이터 분석가",
                    "https://jobs.example.com/3",
                    "판교",
                    "SQL, BigQuery",
                    "수식 주입 테스트 회사명",
                ])

            cfg = kit.validate(profile_presets.apply_preset_to_config(
                "b2b-saas",
                {
                    "scenario": "job_signal",
                    "source_mode": "file",
                    "source_path": str(csv_in),
                    "sender_name": "김영업",
                    "sender_company": "예시데이터",
                    "sender_contact": "sales@example.com",
                    "do_not_contact": ["기존고객DNC"],
                },
            ))
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            profile.sync_profile_to_home(cfg, home, force=True)

            style = style_analyzer.analyze_sent_emails([
                {
                    "subject": "짧은 확인",
                    "body": "담당자님 안녕하세요. 짧게 연락드립니다.\n참고 자료 1장 먼저 보내드릴까요?\n고맙습니다.",
                }
            ])
            style_analyzer.save_style_to_home(style, home)

            res1 = workflow.run(
                str(cfg_path), str(home), str(out), str(vault),
                scenario="job_signal", source_mode="file", source_path=str(csv_in),
                draft_mode="template", drafts_file=None, export_csv=str(csv_out),
            )
            run1 = res1["runs"][0]
            self.assertEqual(run1["source_status"], "ok")
            self.assertEqual(len(run1["skipped_dnc"]), 1)
            self.assertEqual(len(run1["records"]), 2)
            self.assertEqual(run1["vault"]["diff"]["new"], 2)

            pipeline_md = vault / "GTM" / "Pipeline.md"
            self.assertTrue(pipeline_md.is_file())
            self.assertIn("알파데이터랩", pipeline_md.read_text(encoding="utf-8"))

            gtm_acct = vault / "GTM" / "Accounts" / "알파데이터랩.md"
            self.assertTrue(gtm_acct.is_file())
            orig = gtm_acct.read_text(encoding="utf-8")
            edited = orig.replace('status: "발굴"', 'status: "접촉"').replace(
                "<!-- user-notes:start -->\n\n<!-- user-notes:end -->",
                "<!-- user-notes:start -->\n미팅 요청 보냄\n<!-- user-notes:end -->",
            )
            gtm_acct.write_text(edited, encoding="utf-8")

            res2 = workflow.run(
                str(cfg_path), str(home), str(out), str(vault),
                scenario="job_signal", source_mode="file", source_path=str(csv_in),
                draft_mode="template", drafts_file=None,
            )
            run2 = res2["runs"][0]
            self.assertEqual(run2["vault"]["diff"]["new"], 0)
            self.assertEqual(run2["vault"]["diff"]["unchanged"], 2)
            after = gtm_acct.read_text(encoding="utf-8")
            self.assertIn('status: "접촉"', after)
            self.assertIn("미팅 요청 보냄", after)

            exported_text = csv_out.read_text(encoding="utf-8-sig")
            self.assertIn("'=CMD('calc')", exported_text)

            draft_files = list((vault / "Drafts").glob("*.md"))
            self.assertGreaterEqual(len(draft_files), 1)
            draft_body = draft_files[0].read_text(encoding="utf-8")
            self.assertIn("발송 전 내 말로 바꿀 1줄 메모", draft_body)
            self.assertNotIn("보통 이 포지션을 뽑는 시점에", draft_body)

    def test_jev_client_scoring_qa_and_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            (home / ".env").write_text("JEV_API_KEY=test-jev-key-123\n", encoding="utf-8")
            self.assertEqual(jev_client.resolve_api_key(home), "test-jev-key-123")

            mock_opener = _MockJevOpener()
            cfg = kit.validate(profile_presets.apply_preset_to_config(
                "b2b-saas", {"jev_enabled": True, "jev_qa_drafts": True}
            ))
            rec = {
                "source_id": "rec-1",
                "record_type": "job_posting",
                "company": "알파데이터",
                "title": "데이터 엔지니어",
                "description": "Snowflake와 AWS 파이프라인 운영",
                "stack": ["Snowflake", "AWS"],
                "url": "https://jobs.example.com/1",
            }
            scored = jev_client.score_record_with_jev(rec, cfg, api_key="test-jev-key-123", opener=mock_opener)
            self.assertEqual(scored["action"], "지금 콜")
            self.assertEqual(scored["fit_score"], 85)
            self.assertAlmostEqual(scored["relevance_prob"], 0.92)

            qa = jev_client.qa_draft_with_jev("알파데이터 담당자님, 공고 보고 짧게 연락드립니다.", rec, api_key="test-jev-key-123", opener=mock_opener)
            self.assertTrue(qa["passed"])
            self.assertAlmostEqual(qa["cta_clarity"], 0.92)
            self.assertEqual(len(mock_opener.calls), 2)

            jev_scores = workflow.score_records([rec], cfg, home=home, use_jev=True, jev_opener=mock_opener)
            self.assertIn("jev", jev_scores["rec-1"])
            self.assertAlmostEqual(jev_scores["rec-1"]["jev"]["relevance_prob"], 0.92)
            local_scores = workflow.score_records([rec], dict(cfg, jev_enabled=False), home=home, use_jev=False)
            self.assertNotIn("jev", local_scores["rec-1"])
            self.assertIn("fit_score", local_scores["rec-1"])


if __name__ == "__main__":
    unittest.main()
