"""Unit tests for sales presets, profile.py, brochure/website bootstrap, and personal sent-mailbox style analyzer."""
from __future__ import annotations

from email.message import EmailMessage
import io
import json
import mailbox
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kit  # noqa: E402
import profile  # noqa: E402
import profile_bootstrap  # noqa: E402
import profile_presets  # noqa: E402
import style_analyzer  # noqa: E402

SCORER_DIR = ROOT / "pack" / "skills" / "outbound-scoring" / "scripts"
if str(SCORER_DIR) not in sys.path:
    sys.path.insert(0, str(SCORER_DIR))
import account_score  # noqa: E402


class _FakeJevResp:
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


class _FakeOpener:
    def __init__(self, payload: dict):
        self.payload = payload

    def open(self, req, timeout=20):
        return _FakeJevResp(self.payload)


def _make_docx(path: Path, paragraphs: list[str]) -> None:
    xml_paras = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{xml_paras}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))


def _make_pptx(path: Path, slides: list[list[str]]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for idx, lines in enumerate(slides, 1):
            p_nodes = "".join(f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in lines)
            slide_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f"<p:cSld><p:spTree><p:sp><p:txBody>{p_nodes}</p:txBody></p:sp></p:spTree></p:cSld>"
                "</p:sld>"
            )
            zf.writestr(f"ppt/slides/slide{idx}.xml", slide_xml.encode("utf-8"))


class TestPresetsAndProfile(unittest.TestCase):
    def test_all_eight_presets_validate_and_compile_to_account_score(self):
        presets = profile_presets.list_presets()
        self.assertGreaterEqual(len(presets), 8)
        for p in presets:
            cfg = profile_presets.apply_preset_to_config(p["id"], {"sender_name": "김영업"})
            validated = kit.validate(cfg)
            self.assertEqual(validated["sales_preset"], p["id"])
            compiled = profile_presets.compile_sales_profile(validated)
            self.assertIn("fit", compiled)
            self.assertIn("urgency", compiled)
            res = account_score.evaluate(
                {
                    "company": "예시기업",
                    "industry": p["keywords"],
                    "revenue_model": "B2B SaaS 제조 공공",
                    "size": "150명 시리즈 B",
                    "tech_stack": "AWS, SAP, MES, Python, Snowflake",
                    "signals": {"roles": [p["job_keywords"].split(",")[0].strip()]},
                },
                compiled,
            )
            self.assertIn(res["action"], {"지금 콜", "콜 예약", "너처링", "리서치 필요", "보류"})

    def test_profile_sync_dnc_ats_and_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            cfg = kit.validate(profile_presets.apply_preset_to_config(
                "manufacturing-smartfactory",
                {
                    "sender_name": "김영업",
                    "sender_company": "예시비전",
                    "sender_contact": "sales@example.com",
                    "do_not_contact": ["기존고객A"],
                },
            ))
            synced = profile.sync_profile_to_home(cfg, home, force=True)
            self.assertEqual(synced["sales-profile.json"], "updated")
            self.assertEqual(synced["sender-profile.json"], "updated")
            self.assertIn("synced", synced["do-not-contact.txt"])

            dnc = profile.manage_dnc(home, add=["경쟁사B"], remove=["기존고객A"])
            self.assertEqual(dnc, ["경쟁사B"])

            ats = profile.manage_ats_targets(home, add_specs=["greeting:demo-board:예시기업"], remove_tokens=[])
            self.assertTrue(any(t["ats"] == "greeting" and t["token"] == "demo-board" for t in ats))

            prev = profile.preview_profile(cfg, home=home)
            self.assertGreaterEqual(len(prev["previews"]), 1)
            self.assertIn("발송 전 내 말로 바꿀 1줄 메모", prev["previews"][0]["draft"])


class TestBrochureAndWebsiteBootstrap(unittest.TestCase):
    def test_bootstrap_docx_pptx_and_competitor_auto_dnc(self):
        with tempfile.TemporaryDirectory() as tmp:
            brochure_docx = Path(tmp) / "product.docx"
            comp_pptx = Path(tmp) / "competitor.pptx"
            _make_docx(brochure_docx, [
                "예시비전 스마트팩토리 AI 비전검사 소개서",
                "제조 라인의 육안 검사 불량 유출을 줄이고 MES와 PLC 연동으로 공정 품질 이력을 자동 집계합니다.",
                "주요 대상: 반도체·2차전지·자동차부품 중견 제조기업의 생산기술 및 품질관리 팀.",
                "도입 전 샘플 이미지 기반 사전 검증 PoC 결과를 먼저 제공합니다.",
            ])
            _make_pptx(comp_pptx, [
                ["경쟁비전솔루션", "제조 검사 장비 및 레거시 온프레미스 검사기", "반도체 품질관리"],
            ])
            res = profile_bootstrap.bootstrap_profile(
                brochures=[str(brochure_docx)],
                competitor_brochures=[str(comp_pptx)],
                home=Path(tmp) / "home",
            )
            self.assertEqual(res["recommended_preset"]["id"], "manufacturing-smartfactory")
            self.assertIn("MES", res["extracted"]["tech_stack"])
            self.assertIn("PLC", res["extracted"]["tech_stack"])
            self.assertIn("경쟁비전솔루션", res["auto_dnc_suggestions"])
            self.assertIn("경쟁비전솔루션", res["config"]["do_not_contact"])
            self.assertIn("## 4. 경쟁사 분석", res["insights_markdown"])

    def test_bootstrap_with_mocked_jev_refinement(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            (home / ".env").write_text("TYPESAFE_API_KEY=test-jev-fixture-key\n", encoding="utf-8")

            jev_opener = _FakeOpener({
                "model": "jev-latest",
                "answers": {
                    "preset": {"type": "choice", "choice": "cloud-security-it", "confidence": 0.91},
                    "target_segment": {"type": "choice", "choice": "midmarket", "confidence": 0.85},
                    "recommended_tone": {"type": "choice", "choice": "concise", "confidence": 0.88},
                },
                "usage": {"input_tokens": 120, "output_tokens": 0},
            })

            res = profile_bootstrap.bootstrap_profile(
                inline_text="클라우드 보안 ISMS-P 심사 증적 자동화 및 AWS Kubernetes 설정 감사 솔루션",
                home=home,
                use_jev=True,
                opener=jev_opener,
            )
            self.assertEqual(res["recommended_preset"]["id"], "cloud-security-it")
            self.assertEqual(res["config"]["outreach_tone"], "concise")
            self.assertIn("jev_classification", res)


class TestPersonalSentMailboxStyleAnalyzer(unittest.TestCase):
    def test_mbox_eml_analysis_and_strict_pii_redaction(self):
        fake_phone = "-".join(["010", "9876", "5432"])
        with tempfile.TemporaryDirectory() as tmp:
            mbox_path = Path(tmp) / "Sent.mbox"
            box = mailbox.mbox(mbox_path)
            samples = [
                (
                    "[예시테크] 데이터 파이프라인 관련 확인",
                    f"김철수 담당자님, 안녕하세요. 예시테크 이영업 매니저입니다.\n\n"
                    f"데이터 엔지니어 공고 보고 짧게 연락드립니다.\n"
                    f"- Snowflake 적재 자동화\n- 리포팅 수작업 단축\n\n"
                    f"혹시 참고 자료 1장 먼저 보내드려도 될까요?\n\n"
                    f"감사합니다.\n이영업 매니저 | sales@example.com | {fake_phone}",
                ),
                (
                    "[예시테크] AI 플랫폼 운영 관련 확인",
                    f"박영희 팀장님, 안녕하세요. 예시테크 이영업 매니저입니다.\n\n"
                    f"MLOps 공고 보고 짧게 연락드립니다.\n"
                    f"- 배포 파이프라인 간소화\n- 비용 모니터링 정리\n\n"
                    f"지금 보시는 과제가 아니면 패스하셔도 되고, 짧은 정리본만 보내드릴까요?\n\n"
                    f"감사합니다.\n이영업 매니저 | sales@example.com | {fake_phone}",
                ),
                (
                    "Re: 기존 미팅 감사",
                    "답장 메일은 기본적으로 제외되어야 합니다. 충분한 길이의 본문 텍스트입니다.",
                ),
            ]
            for subj, body in samples:
                msg = EmailMessage()
                msg["Subject"] = subj
                msg["From"] = "rep@example.com"
                msg["To"] = "prospect@example.org"
                msg.set_content(body)
                box.add(msg)
            box.flush()
            box.close()

            loaded = style_analyzer.load_mbox_messages(mbox_path, limit=10, skip_replies=True)
            self.assertEqual(len(loaded), 2)
            style = style_analyzer.analyze_sent_emails(loaded)
            self.assertEqual(style["emails_analyzed"], 2)
            self.assertEqual(style["language"], "ko")
            self.assertGreaterEqual(style["structure"]["bullet_usage_rate"], 0.9)
            self.assertTrue(style["privacy"]["pii_redacted"])
            self.assertFalse(style["privacy"]["raw_emails_stored"])

            serialized = json.dumps(style, ensure_ascii=False)
            self.assertNotIn(fake_phone, serialized)
            self.assertNotIn("sales@example.com", serialized)

            home = Path(tmp) / "home"
            cfg_path = Path(tmp) / "setup.json"
            cfg_path.write_text(json.dumps(kit.validate(profile_presets.apply_preset_to_config("b2b-saas"))), encoding="utf-8")
            saved = style_analyzer.save_style_to_home(style, home, cfg_path)
            self.assertTrue(Path(saved["writing_style"]).is_file())
            self.assertTrue(Path(saved["updated_config"]).is_file())


if __name__ == "__main__":
    unittest.main()
