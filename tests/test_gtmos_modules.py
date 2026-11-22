"""Comprehensive tests for GTMOS-aligned modules:
- copy_guard.py (spam/cliche/placeholder linter + 1-4 touch sequence)
- linkedin_outbound.py (ICP -> mocked Apify Company & People REST API -> warming & <=300-char connect/DM -> Vault)
- distributor_finder.py (overseas direct B2B end-user & distributor HTML/CSV -> 4-axis scoring -> EN/JA/DE drafts + LinkedIn handoff)
- reply_tracker.py (11-label classification + mocked Jev + auto-suppression -> DNC + Results/LEARNINGS)
- meeting_and_health.py (pre-meeting 1-page brief, post-meeting recap, mocked MX/SPF/DKIM/DMARC DNS health)
"""
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

import copy_guard  # noqa: E402
import distributor_finder  # noqa: E402
import kit  # noqa: E402
import linkedin_outbound  # noqa: E402
import meeting_and_health  # noqa: E402
import profile_presets  # noqa: E402
import reply_tracker  # noqa: E402


class _FakeResp:
    def __init__(self, payload: Any):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self._buf = io.BytesIO(raw)
        self.status = 200
        self.headers = {}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RouteOpener:
    def __init__(self, routes: dict[str, Any]):
        self.routes = routes
        self.seen_urls: list[str] = []

    def open(self, req, timeout=20):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.seen_urls.append(url)
        for key, payload in self.routes.items():
            if key in url:
                return _FakeResp(payload)
        raise AssertionError(f"Unexpected URL in test: {url}")


class TestCopyGuard(unittest.TestCase):
    def test_lint_catches_cliche_spam_and_placeholders(self):
        bad = copy_guard.lint_copy(
            "안녕하세요 [이름]님! 보통 이 포지션을 뽑는 시점에 혁신적인 솔루션으로 100% 보장 드립니다!!",
            subject="놓치지 마세요! 무료 컨설팅!",
            language="ko",
        )
        self.assertFalse(bad["passed"])
        self.assertGreaterEqual(len(bad["issues"]), 2)

        bad_en = copy_guard.lint_copy(
            "Hi {{company}}, I hope this finds you well! Just following up to circle back on our free trial.",
            subject="Urgent deal!",
            language="en",
        )
        self.assertFalse(bad_en["passed"])

    def test_multitouch_sequence_passes_guardrails(self):
        cfg = kit.validate(profile_presets.apply_preset_to_config(
            "b2b-saas",
            {"sender_name": "김영업", "sender_company": "예시데이터", "sender_contact": "sales@example.com"},
        ))
        seq = copy_guard.build_multitouch_sequence(
            {"company": "알파데이터", "title": "데이터 엔지니어 채용"},
            cfg,
            touches=4,
            language="ko",
        )
        self.assertEqual(len(seq), 4)
        for item in seq:
            self.assertTrue(item["qa"]["passed"], msg=f"Touch {item['touch']} failed QA: {item['qa']}")


class TestLinkedInApifyOutbound(unittest.TestCase):
    def test_icp_apify_company_and_people_pipeline_to_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            vault = root / "vault"
            home.mkdir()
            (home / ".env").write_text("APIFY_TOKEN=test-apify-fixture\n", encoding="utf-8")

            opener = _RouteOpener({
                "acme~li-company": [
                    {
                        "companyName": "AlphaCloud Corp",
                        "industry": "SaaS, AI",
                        "employeeCount": 240,
                        "location": "Seoul",
                        "website": "https://alphacloud.example.com",
                        "linkedinUrl": "https://www.linkedin.com/company/alphacloud",
                        "description": "Snowflake and AWS enterprise data platform",
                    },
                    {
                        "companyName": "ExistingClientDNC",
                        "industry": "SaaS",
                        "employeeCount": 500,
                        "location": "Seoul",
                    },
                ],
                "acme~li-people": [
                    {
                        "firstName": "Minho",
                        "lastName": "Kim",
                        "jobTitle": "Head of Data Engineering",
                        "companyName": "AlphaCloud Corp",
                        "location": "Seoul",
                        "linkedinUrl": "https://www.linkedin.com/in/minho-example",
                        "recentPost": "We just migrated our warehouse to Snowflake.",
                    },
                    {
                        "fullName": "Intern Person",
                        "jobTitle": "Data Engineering Intern",
                        "companyName": "AlphaCloud Corp",
                        "location": "Seoul",
                    },
                    {
                        "fullName": "DNC Lead",
                        "jobTitle": "VP Engineering",
                        "companyName": "ExistingClientDNC",
                        "location": "Seoul",
                    },
                ],
            })

            cfg = kit.validate(profile_presets.apply_preset_to_config(
                "b2b-saas",
                {
                    "job_keywords": "Head of Data, VP Engineering, CTO",
                    "keywords": "SaaS, AI, Data",
                    "region": "Seoul",
                    "exclude_keywords": "Intern",
                    "sender_name": "김영업",
                    "sender_company": "예시데이터",
                    "do_not_contact": ["ExistingClientDNC"],
                },
            ))

            res = linkedin_outbound.run_linkedin_pipeline(
                cfg,
                home=home,
                vault=vault,
                apify_company_actor="acme/li-company",
                apify_people_actor="acme/li-people",
                opener=opener,
            )
            self.assertEqual(res["companies_count"], 2)
            # Intern excluded by title, ExistingClientDNC skipped by DNC -> 1 decision-maker kept
            self.assertEqual(res["contacts_count"], 1)
            self.assertEqual(res["skipped_dnc"], ["ExistingClientDNC"])
            item = res["items"][0]
            self.assertTrue(item["plan"]["warming_required"])
            self.assertLessEqual(item["plan"]["connect_chars"], 300)
            self.assertTrue(item["plan"]["connect_qa"]["passed"])
            self.assertTrue((vault / "LinkedIn" / "Queue.md").is_file())
            self.assertFalse(res["automatic_send"])


class TestOverseasEndUserAndDistributor(unittest.TestCase):
    def test_direct_b2b_end_user_mode_with_multilang_and_linkedin_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "targets.csv"
            vault = root / "vault"
            with csv_path.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["Company", "Country", "Category", "Website", "Description"])
                w.writerow([
                    "AutoWerk GmbH", "DE", "manufacturing, automation",
                    "https://autowerk.example.de",
                    "Automotive manufacturing plant in Munich using SAP, MES, PLC; hiring automation engineers.",
                ])
                w.writerow([
                    "Tokyo Precision KK", "JP", "manufacturing, semiconductor",
                    "https://tokyoprecision.example.jp",
                    "Listed factory group in Tokyo expanding ISO quality automation line.",
                ])

            cfg = kit.validate(profile_presets.apply_preset_to_config(
                "overseas-b2b-direct",
                {"sender_name": "Kim", "sender_company": "ExampleAI", "sender_contact": "sales@example.com"},
            ))
            res = distributor_finder.run_distributor_pipeline(
                cfg,
                mode="end_user",
                exhibitors_file=csv_path,
                target_countries=["DE", "JP"],
                vault=vault,
            )
            self.assertEqual(res["mode"], "end_user")
            self.assertEqual(res["candidates_count"], 2)
            locales = {i["candidate"]["country"]: i["outreach"]["locale"] for i in res["items"]}
            self.assertEqual(locales["DE"], "de")
            self.assertEqual(locales["JP"], "ja")
            # Direct B2B end-user draft must NOT talk about distributor MOQ/margin
            de_item = next(i for i in res["items"] if i["candidate"]["country"] == "DE")
            self.assertNotIn("MOQ", de_item["outreach"]["touch_1"])
            self.assertTrue(res["linkedin_handoff"]["target_companies"])
            self.assertTrue((vault / "Overseas-B2B" / "Pipeline.md").is_file())

    def test_distributor_mode_html_extraction_and_scoring(self):
        html = b"""
        <html><body>
          <div class="distributor-card">
            <h3>MedTech Vertrieb GmbH</h3>
            <p>Authorized medical device distributor in Germany (Munich). CE &amp; ISO 13485 certified, B2B service center.</p>
            <a href="https://medtech-vertrieb.example.de">Website</a>
            <span>sales@example.org</span>
          </div>
        </body></html>
        """
        opener = _RouteOpener({"competitor.example.com/distributors": html})
        cfg = kit.validate(profile_presets.apply_preset_to_config(
            "overseas-distributor",
            {"product": "medical imaging device", "keywords": "medical, distributor, CE", "sender_name": "Kim", "sender_company": "ExampleMed"},
        ))
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            res = distributor_finder.run_distributor_pipeline(
                cfg,
                mode="distributor",
                distributor_urls=["https://competitor.example.com/distributors"],
                target_countries=["DE"],
                competitor_brands=["CompBrand"],
                required_certs=["CE"],
                vault=vault,
                opener=opener,
            )
            self.assertEqual(res["candidates_count"], 1)
            item = res["items"][0]
            self.assertEqual(item["candidate"]["country"], "DE")
            self.assertGreaterEqual(item["score"]["total"], 70)
            self.assertEqual(item["outreach"]["locale"], "de")
            self.assertTrue((vault / "Distributors" / "Pipeline.md").is_file())


class TestReplyTrackerAndMeetingHealth(unittest.TestCase):
    def test_reply_11_label_scoring_jev_and_auto_suppression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            vault = root / "vault"
            home.mkdir()
            (home / ".env").write_text("TYPESAFE_API_KEY=test-jev-fixture\n", encoding="utf-8")

            jev_opener = _RouteOpener({
                "api.typesafe.ai/v1/systemone": {
                    "model": "jev-latest",
                    "answers": {
                        "intent": {"type": "choice", "choice": "positive_soft", "confidence": 0.89},
                        "needs_suppression": {"type": "noul", "noul": 0.02},
                    },
                    "usage": {"input_tokens": 90, "output_tokens": 0},
                }
            })
            replies = [
                {"lead_id": "l1", "company": "관심기업A", "email": "a@example.com", "subject": "Re: 확인", "body": "다음 주 화요일 미팅 가능합니다.", "angle": "hiring"},
                {"lead_id": "l2", "company": "수신거부B", "email": "b@example.com", "subject": "Re: 확인", "body": "수신거부 요청합니다. 리스트에서 제외해주세요.", "angle": "hiring"},
                {"lead_id": "l3", "company": "바운스C", "email": "c@example.com", "subject": "Undeliverable", "body": "550 5.1.1 Address not found", "angle": "hiring"},
                {"lead_id": "l4", "company": "부재중D", "email": "d@example.com", "subject": "Auto-reply", "body": "현재 휴가 중으로 부재중입니다.", "angle": "hiring"},
                {"lead_id": "l5", "company": "모호E", "email": "e@example.com", "subject": "Re: 확인", "body": "일단 내용 확인했습니다.", "angle": "funding"},
            ]
            res = reply_tracker.score_campaign_replies(
                replies,
                total_sent=100,
                campaign_name="q2-test",
                home=home,
                vault=vault,
                apply_suppression=True,
                use_jev=True,
                opener=jev_opener,
            )
            self.assertEqual(res["positive_replies"], 2)  # l1 (local) + l5 (Jev positive_soft)
            self.assertEqual(res["ooo_excluded"], 1)
            self.assertEqual(res["bounces_excluded"], 1)
            dnc_text = (home / "do-not-contact.txt").read_text(encoding="utf-8")
            self.assertIn("수신거부B", dnc_text)
            self.assertIn("바운스C", dnc_text)
            self.assertTrue((vault / "GTM" / "Results.md").is_file())
            self.assertTrue((vault / "GTM" / "LEARNINGS.md").is_file())

    def test_meeting_prep_post_and_domain_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            cfg = kit.validate(profile_presets.apply_preset_to_config(
                "b2b-saas", {"sender_name": "김영업", "sender_company": "예시데이터", "sender_contact": "sales@example.com"}
            ))
            prep = meeting_and_health.generate_meeting_prep(
                "알파데이터", attendees=["김팀장 (Data Lead)"], vault=vault, config=cfg
            )
            self.assertTrue(Path(prep["vault_note"]).is_file())
            self.assertIn("핵심 질문 3개", prep["markdown"])

            post = meeting_and_health.generate_post_meeting(
                "알파데이터",
                "현재 Airflow 수작업 유지보수 병목이 큼\n다음 단계: 금요일까지 PoC 범위 문서 공유드리기로 합의",
                attendee="김팀장",
                config=cfg,
                vault=vault,
            )
            self.assertTrue(Path(post["vault_note"]).is_file())
            self.assertTrue(post["qa"]["passed"])
            self.assertFalse(post["automatic_send"])

            def _mock_dns(name: str, rtype: str) -> list[str]:
                if rtype == "MX" and name == "example.com":
                    return ["10 aspmx.l.google.com."]
                if rtype == "TXT" and name == "example.com":
                    return ["v=spf1 include:_spf.google.com ~all"]
                if rtype == "TXT" and name == "_dmarc.example.com":
                    return ["v=DMARC1; p=quarantine; pct=100"]
                if rtype == "TXT" and name == "google._domainkey.example.com":
                    return ["v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ"]
                return []

            health = meeting_and_health.check_domain_health("sales@example.com", resolver=_mock_dns)
            self.assertEqual(health["status"], "healthy")
            self.assertEqual(health["score"], 100)


if __name__ == "__main__":
    unittest.main()
