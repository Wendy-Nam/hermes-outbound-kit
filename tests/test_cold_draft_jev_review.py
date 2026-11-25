"""Tests for cold-outreach-draft integration, freelance AI instructor preset, multi-stage Jev,
Korean copy_guard flow/honorific checks, and Evidence Cross-Verification Review Panel.
"""
from __future__ import annotations

import csv
import importlib.util
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

import copy_guard  # noqa: E402
import jev_client  # noqa: E402
import kit  # noqa: E402
import outbound  # noqa: E402
import profile_presets  # noqa: E402
import review_panel  # noqa: E402
import vault_flow  # noqa: E402


def _load_skill_script(rel_path: str, name: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


class _MultiStageMockJev:
    def __init__(self, mode: str = "pass"):
        self.mode = mode
        self.calls: list[dict] = []

    def open(self, req, timeout=20):
        payload = json.loads(req.data.decode("utf-8"))
        self.calls.append(payload)
        qs = payload["questions"]
        if "is_excluded" in qs:
            if self.mode == "gate_reject":
                return _FakeResp({
                    "model": "jev-latest",
                    "answers": {
                        "is_relevant": {"type": "noul", "noul": 0.12},
                        "is_excluded": {"type": "noul", "noul": 0.88},
                        "identity_clear": {"type": "noul", "noul": 0.9},
                    },
                })
            return _FakeResp({
                "model": "jev-latest",
                "answers": {
                    "is_relevant": {"type": "noul", "noul": 0.91},
                    "is_excluded": {"type": "noul", "noul": 0.05},
                    "identity_clear": {"type": "noul", "noul": 0.95},
                },
            })
        if "fit_rubric" in qs:
            conf = 0.45 if self.mode == "low_conf" else 0.85
            return _FakeResp({
                "model": "jev-latest",
                "answers": {
                    "is_relevant": {"type": "noul", "noul": 0.91},
                    "fit_rubric": {"type": "score", "score": 0.9, "confidence": 0.88},
                    "urgency_rubric": {"type": "score", "score": 0.82, "confidence": 0.84},
                    "recommended_action": {"type": "choice", "choice": "call_now", "confidence": conf},
                    "needs_research": {"type": "noul", "noul": 0.1},
                },
            })
        if "unverified_claim_present" in qs:
            return _FakeResp({
                "model": "jev-latest",
                "answers": {
                    "unverified_claim_present": {"type": "noul", "noul": 0.72},
                    "trigger_matches_signal": {"type": "noul", "noul": 0.4},
                },
            })
        if "evidence_alignment" in qs:
            if self.mode == "borderline_qa":
                return _FakeResp({
                    "model": "jev-latest",
                    "answers": {
                        "hallucination_risk": {"type": "noul", "noul": 0.45},
                        "evidence_alignment": {"type": "noul", "noul": 0.50},
                        "causal_flow_natural": {"type": "noul", "noul": 0.85},
                        "pushy_or_exaggerated": {"type": "noul", "noul": 0.1},
                        "honorific_or_tone_error": {"type": "noul", "noul": 0.05},
                        "has_clear_single_cta": {"type": "noul", "noul": 0.9},
                    },
                })
            return _FakeResp({
                "model": "jev-latest",
                "answers": {
                    "hallucination_risk": {"type": "noul", "noul": 0.05},
                    "evidence_alignment": {"type": "noul", "noul": 0.92},
                    "causal_flow_natural": {"type": "noul", "noul": 0.90},
                    "pushy_or_exaggerated": {"type": "noul", "noul": 0.05},
                    "honorific_or_tone_error": {"type": "noul", "noul": 0.02},
                    "has_clear_single_cta": {"type": "noul", "noul": 0.95},
                },
            })
        raise AssertionError(f"Unexpected Jev payload keys: {list(qs)}")


class TestColdDraftJevAndReview(unittest.TestCase):
    def test_freelance_instructor_preset_and_profile_end_to_end(self):
        preset = profile_presets.get_preset("freelance-ai-instructor")
        self.assertIn("recommended_channels", preset)
        self.assertIn("direct_corporate_outreach", preset["recommended_channels"])
        self.assertIn("instructor_and_b2b_platforms", preset["recommended_channels"])
        self.assertIn("public_and_university", preset["recommended_channels"])

        cfg = kit.validate(profile_presets.apply_preset_to_config("freelance-ai-instructor"))
        self.assertEqual(cfg["sales_preset"], "freelance-ai-instructor")
        self.assertIn("tenders", cfg["workflows"])

        gen_mod = _load_skill_script("pack/skills/cold-outreach-draft/scripts/gen_drafts.py", "test_gen_drafts")
        prof_path = ROOT / "pack/skills/cold-outreach-draft/references/profiles/example-freelance-instructor.json"
        leads_path = ROOT / "samples/leads-freelance-instructor.csv"
        profile_data = json.loads(prof_path.read_text(encoding="utf-8-sig"))
        with leads_path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))

        drafts = gen_mod.generate_drafts(profile_data, rows, date_str="261124", use_copy_guard=True)
        self.assertEqual(len(drafts), 6)
        by_lead = {d["lead"]: d for d in drafts}
        angles = {d["angle"] for d in drafts}
        self.assertIn("hrd_workshop+scale_tracks", angles)
        self.assertIn("exec_ax", angles)
        self.assertIn("public_tender", angles)
        self.assertIn("biz_consulting", angles)
        self.assertIn("funding_scale", angles)
        self.assertIn("platform_seminar", angles)
        # Consulting draft must not leak workshop/curriculum trigger or CTA
        self.assertIn("자동화 진단 체크리스트", by_lead["하늘물류"]["body"])
        self.assertNotIn("교육 구성이 있어", by_lead["하늘물류"]["body"])
        for d in drafts:
            self.assertEqual(d["flags"], "", f"Unexpected flags on {d['lead']}: {d['flags']}")
            self.assertLessEqual(len(d["dm"]), 300)
            self.assertNotIn("…", d["dm"], f"DM should not truncate mid-sentence: {d['dm']}")
            self.assertTrue(d["dm"].endswith((".", "?")), f"DM should end cleanly: {d['dm']}")
            self.assertTrue(d["evidence_url"].startswith("https://"))
            self.assertIn("프리랜서 강사 김지안입니다.", d["body"])

    def test_helpdesk_list_when_and_cli_html_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_prefix = Path(tmp) / "helpdesk-out"
            panel_path = Path(tmp) / "panel.html"
            rc = outbound.main([
                "draft", "generate",
                "--profile", str(ROOT / "pack/skills/cold-outreach-draft/references/profiles/example-helpdesk.json"),
                "--leads", str(ROOT / "pack/skills/cold-outreach-draft/references/sample-leads.csv"),
                "--out", str(out_prefix),
                "--date", "261124",
                "--copy-guard",
                "--html", str(panel_path),
            ])
            self.assertEqual(rc, 0)
            data = json.loads(Path(str(out_prefix) + ".json").read_text(encoding="utf-8"))
            by_lead = {d["lead"]: d for d in data}
            self.assertEqual(by_lead["다라상사"]["angle"], "phone_chat")
            self.assertEqual(by_lead["자차컴퍼니"]["angle"], "skip")
            self.assertTrue(panel_path.is_file())
            html_text = panel_path.read_text(encoding="utf-8")
            self.assertIn("원문 근거 열기", html_text)
            self.assertIn("https://jobs.example.com/101", html_text)

    def test_collect_contacts_ssrf_and_tls_hardening(self):
        cc = _load_skill_script("pack/skills/cold-outreach-draft/scripts/collect_contacts.py", "test_collect_contacts")
        priv_ip = ".".join(["192", "168", "1", "1"])
        cred_url = "https://" + "u" + ":" + "p" + "@example.com/"
        for bad in (
            "http://127.0.0.1/admin",
            "http://localhost:8080/",
            "http://169.254.169.254/latest/meta-data/",
            f"http://{priv_ip}/",
            "file:///etc/passwd",
            cred_url,
        ):
            ok, reason = cc.is_safe_public_url(bad)
            self.assertFalse(ok, f"Should block SSRF URL: {bad} ({reason})")
        src_text = (ROOT / "pack/skills/cold-outreach-draft/scripts/collect_contacts.py").read_text(encoding="utf-8")
        self.assertNotIn("CERT_NONE", src_text)

    def test_multistage_jev_gate_disagreement_and_borderline_qa(self):
        cfg = kit.validate(profile_presets.apply_preset_to_config("b2b-saas", {"jev_enabled": True}))
        rec = {
            "source_id": "r1",
            "record_type": "job_posting",
            "company": "샘플데이터",
            "title": "데이터 엔지니어",
            "description": "Snowflake 파이프라인 운영",
            "url": "https://jobs.example.com/1",
        }
        # 1) Gate reject short-circuits in 1 call
        m_rej = _MultiStageMockJev("gate_reject")
        res_rej = jev_client.score_record_multistage_with_jev(rec, cfg, api_key="test-key", opener=m_rej)
        self.assertEqual(res_rej["stages_run"], 1)
        self.assertEqual(res_rej["stage_stopped"], "gate")
        self.assertEqual(res_rej["action"], "보류")
        self.assertEqual(len(m_rej.calls), 1)

        # 2) Disagreement guard & low-confidence downgrade
        m_low = _MultiStageMockJev("low_conf")
        res_low = jev_client.score_record_multistage_with_jev(
            rec, cfg, api_key="test-key", local_fit=30, local_urgency=40, opener=m_low
        )
        self.assertEqual(res_low["stages_run"], 2)
        self.assertTrue(res_low["needs_human_check"])
        self.assertEqual(res_low["action"], "리서치 필요")
        self.assertIn("편차 큼", res_low["disagreement_note"])

        # 3) Borderline QA triggers Stage 3b deep verification
        m_qa = _MultiStageMockJev("borderline_qa")
        qa = jev_client.qa_draft_with_jev("초안 본문입니다.", rec, api_key="test-key", opener=m_qa)
        self.assertEqual(qa["stages_run"], 2)
        self.assertTrue(qa["borderline_verified"])
        self.assertFalse(qa["passed"])
        self.assertTrue(any("근거 외 주장" in f for f in qa["flags"]))

    def test_copy_guard_korean_honorific_flow_and_no_jeohui(self):
        bad_draft = (
            "안녕하세요. 샘플기업 담당자님,\n"
            "공고를 보니 인력이 부족한 것 같았습니다 — 혹시 바쁘지 않나요?\n"
            "통화 중 부재 전화는 순서대로 다시 연락드릴 수 있습니다."
        )
        res = copy_guard.lint_copy(bad_draft, subject="확인 요청", language="ko")
        self.assertFalse(res["passed"])
        joined = " ".join(res["issues"] + res["warnings"])
        self.assertIn("높임 주어 오류", joined)
        self.assertIn("부자연스러운 질문/훈수", joined)
        self.assertIn("em-dash", joined)

        # Intentional user voice commas must pass cleanly
        good_draft = (
            "안녕하세요. 가온제조 담당자님,\n"
            "기업 AI 실무 교육을 진행하는 김지안입니다.\n\n"
            "원티드에 올리신 HRD 채용 공고를 보고 연락드립니다.\n"
            "임직원 교육 프로그램을 준비하시는 만큼, 혹시 직무별 현업 적용률이 고민되시지는 않으신가요?\n\n"
            "직무 맞춤형 워크숍을 진행하시게 되면, 부서별 실제 과제로 실습해 업무 시간을 줄이실 수 있습니다.\n"
            "또한, 사전 설문으로 수준별 트랙을 나눠 구성해 드립니다.\n\n"
            "관심이 있으시면 편하게 회신 부탁드립니다."
        )
        res_good = copy_guard.lint_copy(good_draft, subject="[김지안랩] 가온제조 AI 워크숍 제안", language="ko")
        self.assertTrue(res_good["passed"], f"Expected clean pass: {res_good}")

        seq = copy_guard.build_multitouch_sequence(
            {"company": "가온제조", "title": "HRD 담당자 채용"},
            {"product": "AI 실무 워크숍", "sender_name": "김지안", "sender_company": "김지안랩"},
            touches=1,
            language="ko",
        )
        self.assertNotIn("저희는", seq[0]["body"])

    def test_vault_inline_evidence_and_xss_safe_review_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault_flow.init_vault(vault)
            vault_flow.run_flow(vault)
            draft_files = list((vault / "Drafts").glob("*.md"))
            self.assertGreaterEqual(len(draft_files), 1)
            dtext = draft_files[0].read_text(encoding="utf-8")
            self.assertIn("## 근거 교차검증 요약", dtext)
            self.assertIn("[원문 바로 열기](https://", dtext)

            panel_out = Path(tmp) / "vault-panel.html"
            res = review_panel.build_review_panel(vault_dir=vault, output_html=panel_out)
            self.assertGreaterEqual(res["count"], 1)
            self.assertTrue(panel_out.is_file())

            # XSS breakout prevention check
            xss_html = review_panel.render_review_panel_html([
                {"id": "1", "lead": "</script><script>alert(1)</script>", "evidence_url": "javascript:alert(1)", "body": "test"}
            ])
            self.assertNotIn("</script><script>alert(1)", xss_html)
            self.assertIn("<\\/script>", xss_html)


if __name__ == "__main__":
    unittest.main()
