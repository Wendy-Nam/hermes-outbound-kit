"""Unit tests for upgraded multi-board job, funding, tender, and overseas crawlers in sources.py."""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import src  # noqa: E402,F401

import sources  # noqa: E402


NOW = "2026-04-01T00:00:00Z"


class _FakeResp:
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None):
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, routes: dict[str, bytes | Exception | tuple[bytes, dict]]):
        self.routes = routes

    def open(self, req, timeout=20):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for prefix, outcome in self.routes.items():
            if prefix in url:
                if isinstance(outcome, Exception):
                    raise outcome
                if isinstance(outcome, tuple):
                    return _FakeResp(outcome[0], headers=outcome[1])
                return _FakeResp(outcome)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


class TestSourcesCrawlers(unittest.TestCase):
    def test_extract_tech_stack_with_korean_particles(self):
        text = "AWS, Kubernetes, Snowflake와 dbt 기반 파이프라인 운영. Python과 Kafka 우대."
        stack = sources.extract_tech_stack(text) or []
        for expected in ("AWS", "Kubernetes", "Snowflake", "dbt", "Python", "Kafka"):
            self.assertIn(expected, stack)

    def test_wanted_pagination_gzip_and_detail_enrichment(self):
        list_page_1 = json.dumps({
            "positions": [
                {
                    "id": 100 + i,
                    "position": "시니어 데이터 엔지니어" if i == 1 else f"데이터 분석가 {i}",
                    "company": {"name": "주식회사 알파데이터" if i == 1 else f"예시기업{i}"},
                    "address": {"location": "서울", "district": "강남구"},
                    "created_time": "2026-04-01",
                }
                for i in range(1, 21)
            ],
        }).encode("utf-8")
        list_page_2 = json.dumps({
            "positions": [
                {
                    "id": 201,
                    "position": "AI MLOps 엔지니어",
                    "company": {"name": "베타클라우드"},
                    "address": {"location": "경기", "district": "판교"},
                }
            ],
        }).encode("utf-8")
        detail_101 = json.dumps({
            "job": {
                "detail": {
                    "main_tasks": "Snowflake와 Airflow 파이프라인 고도화",
                    "requirements": "Python, SQL, AWS 경력 3년 이상",
                },
                "skill_tags": [{"title": "Snowflake"}, {"title": "Python"}],
            }
        }).encode("utf-8")

        opener = _FakeOpener({
            "/api/v4/jobs/101": detail_101,
            "offset=20": list_page_2,
            "/api/chaos/search/v1/results": (gzip.compress(list_page_1), {"Content-Encoding": "gzip"}),
        })
        res = sources.collect_wanted(
            "데이터 엔지니어", 25, None, NOW,
            pages=2, fetch_details=True, detail_limit=1, delay=0, opener=opener,
        )
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(res.records), 21)
        rec0 = res.records[0]
        self.assertIn("Snowflake", rec0["stack"])
        self.assertIn("Airflow", rec0["stack"])
        self.assertIn("Snowflake와 Airflow", rec0["description"])

    def test_saramin_html_parser_sample_fixture(self):
        sample_html = (ROOT / "samples" / "source-saramin.html").read_bytes()
        opener = _FakeOpener({"saramin.co.kr": sample_html})
        res = sources.collect_saramin("데이터", 20, None, NOW, pages=1, delay=0, opener=opener)
        self.assertEqual(res.status, "ok")
        self.assertGreaterEqual(len(res.records), 1)
        self.assertTrue(res.records[0]["company"])
        self.assertTrue(res.records[0]["title"])

    def test_jobkorea_next_data_parser(self):
        next_html = (
            '<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({
                "props": {
                    "pageProps": {
                        "items": [
                            {
                                "gNo": "998877",
                                "cName": "감마제조",
                                "gTitle": "스마트팩토리 PLC 엔지니어",
                                "area": "경기 화성",
                                "career": "경력 3년",
                            }
                        ]
                    }
                }
            })
            + "</script></body></html>"
        ).encode("utf-8")
        res = sources.normalize_jobkorea_html(next_html, "PLC", NOW)
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(res.records), 1)
        self.assertEqual(res.records[0]["company"], "감마제조")
        self.assertIn("998877", res.records[0]["source_id"])

    def test_jumpit_api_and_detail(self):
        list_json = json.dumps({
            "result": {
                "positions": [
                    {
                        "id": 555,
                        "title": "백엔드 플랫폼 엔지니어",
                        "companyName": "델타핀테크",
                        "locations": ["서울 강남구"],
                        "techStacks": ["Python", "Kafka", "AWS"],
                    }
                ]
            }
        }).encode("utf-8")
        detail_json = json.dumps({
            "result": {
                "responsibility": "결제 정산 파이프라인 구축",
                "qualifications": "Kotlin, Spring, PostgreSQL",
                "techStacks": [{"stack": "PostgreSQL"}],
            }
        }).encode("utf-8")
        opener = _FakeOpener({
            "/api/position/555": detail_json,
            "/api/positions": list_json,
        })
        res = sources.collect_jumpit("백엔드", 20, None, NOW, pages=1, fetch_details=True, delay=0, opener=opener)
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(res.records), 1)
        self.assertIn("Kafka", res.records[0]["stack"])
        self.assertIn("PostgreSQL", res.records[0]["stack"])

    def test_greeting_ats_normalization(self):
        html = (
            '<html><body><a href="/o/12345">데이터 플랫폼 엔지니어 (Snowflake / AWS)</a>'
            '<a href="/o/12346">세일즈 매니저</a></body></html>'
        ).encode("utf-8")
        res = sources.normalize_greeting_html(html, "ex", "예시테크", NOW)
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(res.records), 2)
        self.assertIn("greeting", res.records[0]["source"])
        self.assertIn("Snowflake", res.records[0]["stack"])

    def test_multi_board_dedupe_and_partial_ok(self):
        wanted_json = json.dumps({
            "positions": [{
                "id": 1,
                "position": "데이터 엔지니어",
                "company": {"name": "(주)알파데이터"},
                "address": {"location": "서울"},
            }]
        }).encode("utf-8")
        jumpit_json = json.dumps({
            "result": {
                "positions": [
                    {
                        "id": 2,
                        "title": "데이터 엔지니어",
                        "companyName": "알파데이터",
                        "locations": ["서울"],
                        "techStacks": ["Airflow", "Snowflake"],
                    },
                    {
                        "id": 3,
                        "title": "AI 리서치 엔지니어",
                        "companyName": "신규스타트업",
                        "locations": ["판교"],
                        "techStacks": ["PyTorch"],
                    },
                ]
            }
        }).encode("utf-8")
        opener = _FakeOpener({
            "wanted.co.kr": wanted_json,
            "api.jumpit.co.kr": jumpit_json,
            "saramin.co.kr": urllib.error.HTTPError("https://www.saramin.co.kr/", 403, "Forbidden", {}, None),
        })
        res = sources.collect_jobs_multi(
            providers=["wanted", "jumpit", "saramin"],
            queries=["데이터 엔지니어"],
            retrieved_at=NOW,
            pages=1,
            fetch_details=False,
            partial_ok=True,
            delay=0,
            opener=opener,
        )
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(res.records), 2)
        merged = next(r for r in res.records if "알파데이터" in r["company"])
        self.assertIn("Snowflake", merged["stack"])
        self.assertTrue(any("saramin" in e.lower() for e in res.errors))

    def test_g2b_tender_normalization_and_missing_key(self):
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "items": [
                        {
                            "bidNtceNo": "20260401001",
                            "bidNtceOrd": "00",
                            "bidNtceNm": "2026년 공공데이터 AI 플랫폼 고도화 용역",
                            "dminsttNm": "한국예시진흥원",
                            "ntceInsttNm": "조달청",
                            "presmptPrce": "350000000",
                            "bidNtceDt": "2026-04-01 09:00:00",
                            "bidClseDt": "2026-04-15 18:00:00",
                            "bidNtceDtlUrl": "https://www.g2b.go.kr/example/1",
                        }
                    ]
                },
            }
        }
        res = sources.normalize_g2b_items(payload, NOW)
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(res.records), 1)
        self.assertEqual(res.records[0]["record_type"], "procurement")
        self.assertEqual(res.records[0]["company"], "한국예시진흥원")
        self.assertIn("350000000", res.records[0]["description"])

        missing_res = sources.collect_tenders_g2b("AI", NOW)
        self.assertEqual(missing_res.status, "failed")

    def test_overseas_rss_xml_and_doctype_rejection(self):
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Global Partner News</title>
          <item>
            <title>AcmeCloud expands enterprise AI distribution into Korea</title>
            <link>https://news.example.com/acme-korea</link>
            <description>Seeking local B2B reseller partners in Seoul.</description>
            <pubDate>Tue, 01 Apr 2026 00:00:00 GMT</pubDate>
          </item>
        </channel></rss>"""
        res = sources.normalize_rss_xml(rss, "https://news.example.com/rss", NOW)
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(res.records), 1)
        self.assertEqual(res.records[0]["record_type"], "overseas_partner")

        xxe = b"<!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><rss/>"
        bad = sources.normalize_rss_xml(xxe, "https://news.example.com/rss", NOW)
        self.assertEqual(bad.status, "invalid_response")

    def test_apply_config_filters(self):
        res = sources.SourceResult(
            status="ok",
            source="test-board",
            records=[
                {"company": "알파AI", "title": "데이터 엔지니어", "description": "Python AWS", "location": "서울", "stack": ["AWS"]},
                {"company": "베타", "title": "데이터 인턴", "description": "체험형 인턴", "location": "서울", "stack": []},
                {"company": "감마", "title": "매장 관리", "description": "오프라인 매장", "location": "제주", "stack": []},
            ],
        )
        filtered = sources.apply_config_filters(
            res, {"job_keywords": "데이터, AWS", "exclude_keywords": "인턴", "region": "서울"}, "jobs"
        )
        self.assertEqual(filtered.status, "ok")
        self.assertEqual(len(filtered.records), 1)
        self.assertEqual(filtered.records[0]["company"], "알파AI")


if __name__ == "__main__":
    unittest.main()
