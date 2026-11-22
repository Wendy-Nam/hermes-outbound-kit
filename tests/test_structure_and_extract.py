"""Tests for clean src/ layout, outbound.py CLI, OMH/OmniRoute independence,
Firecrawl JS rendering fallback, and image JD / brochure OCR/Vision extraction.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src  # noqa: E402,F401
import distributor_finder  # noqa: E402
import installer  # noqa: E402
import kit  # noqa: E402
import outbound  # noqa: E402
import profile_bootstrap  # noqa: E402
import runtime_connect  # noqa: E402
import server_access  # noqa: E402
import services  # noqa: E402
import sources  # noqa: E402
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
        raise AssertionError(f"Unexpected URL in mock opener: {url}")


class TestStructureAndIndependence(unittest.TestCase):
    def test_outbound_cli_help_and_validate(self):
        self.assertNotIn("omh", outbound.COMMANDS)
        self.assertNotIn("omniroute", outbound.COMMANDS)
        proc = subprocess.run(
            [sys.executable, str(ROOT / "outbound.py"), "validate", "--config", str(ROOT / "setup.example.json")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_setup_rejects_removed_omh_and_omniroute_fields(self):
        base = json.loads((ROOT / "setup.example.json").read_text(encoding="utf-8"))
        kit.validate(base)
        for removed in ("omh_enabled", "omniroute_enabled", "routing_bindings_path"):
            bad = dict(base)
            bad[removed] = False if removed.endswith("_enabled") else ""
            with self.assertRaises(ValueError):
                kit.validate(bad)

    def test_installer_plan_has_no_omh_or_routing_steps(self):
        base = json.loads((ROOT / "setup.example.json").read_text(encoding="utf-8"))
        planned = installer.plan(base, Path("/tmp/test-home"), Path("/tmp/test-out"))
        step_ids = [s["id"] for s in planned["steps"]]
        self.assertNotIn("omh", step_ids)
        self.assertNotIn("routing", step_ids)
        self.assertNotIn("optional_components", planned)

    def test_server_deploy_bundle_members_match_new_src_layout(self):
        members = server_access._bundle_members(ROOT)
        rels = {p.relative_to(ROOT).as_posix() for p in members}
        self.assertIn("outbound.py", rels)
        self.assertIn("src/core/kit.py", rels)
        self.assertIn("src/core/web_extract.py", rels)
        self.assertIn("scripts/build_bundle.py", rels)
        self.assertFalse(any("omh_setup" in r or "omniroute_setup" in r for r in rels))


class TestFirecrawlAndWebExtract(unittest.TestCase):
    def test_firecrawl_service_registered_and_probeable(self):
        self.assertIn("firecrawl", services.SERVICES)
        self.assertIn("firecrawl", kit.CHOICES["services"])
        opener = _RoutingOpener({
            "https://api.firecrawl.dev/v1/team/credit-usage": (
                json.dumps({"success": True, "data": {"remainingCredits": 500}}).encode("utf-8"),
                "application/json",
            )
        })
        res = services.probe("firecrawl", "test-firecrawl-key-123456", opener=opener)
        self.assertTrue(res["auth_valid"])
        self.assertEqual(res["service"], "firecrawl")
        _updates, connectors, _rows = runtime_connect._desired({"services": ["firecrawl", "jev"]})
        self.assertEqual(connectors["firecrawl"]["key_env"], "FIRECRAWL_API_KEY")
        self.assertEqual(connectors["jev"]["key_env"], "TYPESAFE_API_KEY")

    def test_js_shell_detection(self):
        spa = '<html><head><title>App</title></head><body><div id="root"></div><script src="/bundle.js"></script><noscript>Please enable JavaScript</noscript></body></html>'
        rich = "<html><body><h1>회사 소개</h1><p>" + ("제조 설비 자동화 MES 솔루션 공급 사례입니다. " * 25) + "</p></body></html>"
        self.assertTrue(web_extract.looks_like_js_shell(spa))
        self.assertFalse(web_extract.looks_like_js_shell(rich))

    def test_profile_bootstrap_fetch_website_firecrawl_fallback_and_missing_key(self):
        spa_html = b'<html><head><title>SPA Co</title></head><body><div id="__next"></div><script src="/a.js"></script></body></html>'
        fc_body = json.dumps({
            "success": True,
            "data": {
                "markdown": "# Acme Robotics\n\n스마트팩토리 비전 검사 및 MES 연동 솔루션을 공급합니다.",
                "metadata": {"title": "Acme Robotics"},
            },
        }).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            # 1) Without FIRECRAWL_API_KEY -> records transparent js_rendered_empty hint
            opener_no_key = _RoutingOpener({"https://spa.example.com": (spa_html, "text/html")})
            with mock.patch.dict(os.environ, {"FIRECRAWL_API_KEY": "", "HERMES_HOME": str(home)}, clear=False):
                doc_no_key = profile_bootstrap.fetch_website(
                    "https://spa.example.com/", "company_site", max_subpages=0, home=home, opener=opener_no_key
                )
            self.assertIn("js_rendered_empty", doc_no_key.error)

            # 2) With FIRECRAWL_API_KEY in $HERMES_HOME/.env -> renders via Firecrawl
            (home / ".env").write_text("FIRECRAWL_API_KEY=test-fc-key-999999\n", encoding="utf-8")
            opener_with_fc = _RoutingOpener({
                "https://spa.example.com": (spa_html, "text/html"),
                "https://api.firecrawl.dev/v1/scrape": (fc_body, "application/json"),
            })
            with mock.patch.dict(os.environ, {"FIRECRAWL_API_KEY": "", "HERMES_HOME": str(home)}, clear=False):
                doc = profile_bootstrap.fetch_website(
                    "https://spa.example.com/", "company_site", max_subpages=0, home=home, opener=opener_with_fc
                )
            self.assertEqual(doc.status, "ok")
            self.assertIn("스마트팩토리 비전 검사", doc.text)

    def test_distributor_finder_firecrawl_spa_fallback(self):
        spa_html = b'<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
        rendered_html = (
            "<html><body><div class='partner'><h3>Bavaria MedTech GmbH</h3>"
            "<p>Munich, Germany. Authorized Distributor for medical robotics. info@example.com</p>"
            "</div></body></html>"
        )
        fc_body = json.dumps({"success": True, "data": {"html": rendered_html, "markdown": ""}}).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".env").write_text("FIRECRAWL_API_KEY=test-fc-key-888888\n", encoding="utf-8")
            opener = _RoutingOpener({
                "https://vendor.example.com/distributors": (spa_html, "text/html"),
                "https://api.firecrawl.dev/v1/scrape": (fc_body, "application/json"),
            })
            with mock.patch.dict(os.environ, {"FIRECRAWL_API_KEY": "", "HERMES_HOME": str(home)}, clear=False):
                items, errors = distributor_finder.fetch_distributor_pages(
                    ["https://vendor.example.com/distributors"],
                    target_countries=["DE"],
                    home=home,
                    opener=opener,
                )
            self.assertEqual(errors, [])
            self.assertTrue(any("Bavaria MedTech" in it["company"] for it in items))

    def test_image_brochure_and_image_job_ocr_vision_and_fallback(self):
        # Minimal 1x1 PNG bytes
        tiny_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        vision_resp = json.dumps({
            "choices": [{
                "message": {
                    "content": "채용 직무: 데이터 엔지니어\n필수 기술: Python, Airflow, Snowflake, AWS"
                }
            }]
        }).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            img_file = home / "brochure.png"
            img_file.write_bytes(tiny_png)

            # 1) No tesseract and no Vision API key -> transparent ocr_unavailable
            with mock.patch("shutil.which", return_value=None), mock.patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "", "OPENROUTER_API_KEY": "", "HERMES_HOME": str(home)},
                clear=False,
            ):
                doc_unavail = profile_bootstrap.read_brochure(img_file, home=home)
            self.assertEqual(doc_unavail.status, "ocr_unavailable")
            self.assertIn("tesseract", doc_unavail.error)

            # 2) With OPENAI_API_KEY -> Vision API extracts image brochure text
            (home / ".env").write_text("OPENAI_API_KEY=test-openai-vision-key-123\n", encoding="utf-8")
            opener = _RoutingOpener({
                "https://api.openai.com/v1/chat/completions": (vision_resp, "application/json"),
                "https://cdn.example.com/jd/poster-01.png": (tiny_png, "image/png"),
            })
            with mock.patch("shutil.which", return_value=None), mock.patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "", "OPENROUTER_API_KEY": "", "HERMES_HOME": str(home)},
                clear=False,
            ):
                doc_ok = profile_bootstrap.read_brochure(img_file, home=home, opener=opener)
                self.assertEqual(doc_ok.status, "ok")
                self.assertIn("Airflow", doc_ok.text)

                # 3) Image-only job posting enrichment via sources.enrich_image_job()
                jd_html = (
                    '<html><body>'
                    '<img src="/static/logo.png">'
                    '<img src="https://cdn.example.com/jd/poster-01.png">'
                    '</body></html>'
                )
                urls = sources.extract_job_image_urls(jd_html, base_url="https://jobs.example.com/view/1")
                self.assertEqual(urls, ["https://cdn.example.com/jd/poster-01.png"])
                rec = {"title": "데이터 엔지니어", "url": "https://jobs.example.com/view/1", "description": "", "stack": []}
                enriched = sources.enrich_image_job(rec, html_text=jd_html, home=home, opener=opener)
                self.assertEqual(enriched["ocr_status"], "ok")
                self.assertEqual(enriched["ocr_provider"], "openai_vision")
                self.assertIn("Airflow", enriched["stack"])
                self.assertIn("Snowflake", enriched["stack"])


if __name__ == "__main__":
    unittest.main()
