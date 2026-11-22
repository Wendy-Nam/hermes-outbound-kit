#!/usr/bin/env python3
"""Sales role/industry presets and no-code scoring profile compiler.

Allows sales reps across diverse industries (B2B SaaS, HR/Recruiting,
Manufacturing/Smart Factory, Marketing/Commerce, Logistics/Trade,
Cloud/Security, Fintech/Finance, Public B2G, Consulting/Custom) to customize
sourcing queries, Fit x Urgency scoring criteria, and outreach tone without
hand-editing regular expressions.
"""
from __future__ import annotations
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401

import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PRESET_DIR = ROOT / "pack" / "presets"

VALID_TONES = ("formal", "consultative", "concise", "friendly")
VALID_CHANNELS = ("email", "linkedin", "call")


def _preset_dirs(home: str | Path | None = None) -> list[Path]:
    dirs: list[Path] = []
    if home:
        custom = Path(home).expanduser().absolute() / "presets"
        if custom.is_dir():
            dirs.append(custom)
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        env_dir = Path(env_home).expanduser().absolute() / "presets"
        if env_dir.is_dir() and env_dir not in dirs:
            dirs.append(env_dir)
    if PRESET_DIR.is_dir() and PRESET_DIR not in dirs:
        dirs.append(PRESET_DIR)
    return dirs


def list_presets(home: str | Path | None = None) -> list[dict[str, Any]]:
    """Return all available presets sorted by display order (user presets override built-in)."""
    seen: dict[str, dict[str, Any]] = {}
    for directory in reversed(_preset_dirs(home)):
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and isinstance(data.get("id"), str) and data["id"].strip():
                seen[data["id"]] = data
    return sorted(seen.values(), key=lambda item: (int(item.get("order", 99)), item["id"]))


def preset_ids(home: str | Path | None = None) -> tuple[str, ...]:
    return tuple(item["id"] for item in list_presets(home))


def get_preset(preset_id: str, home: str | Path | None = None) -> dict[str, Any]:
    if not preset_id:
        raise ValueError("preset_id가 필요합니다.")
    for item in list_presets(home):
        if item["id"] == preset_id:
            return json.loads(json.dumps(item))
    available = ", ".join(preset_ids(home))
    raise ValueError(f"알 수 없는 프리셋입니다: {preset_id} (가능한 값: {available})")


def split_terms(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(v).strip() for v in value]
    elif isinstance(value, str):
        raw_items = [part.strip() for part in re.split(r"[,;/|\n]+", value)]
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if len(item) >= 2 and item.casefold() not in seen:
            seen.add(item.casefold())
            out.append(item)
    return out


def _terms_to_regex(terms: list[str]) -> str:
    cleaned = [re.escape(t.strip()) for t in terms if isinstance(t, str) and t.strip()]
    return "|".join(dict.fromkeys(cleaned))


def _tier_bands(tiers: dict[str, Any] | list[Any] | None, fallback: list[list[Any]]) -> list[list[Any]]:
    """Convert friendly {high: [...], medium: [...], low: [...]} or raw [[rx, ratio]] to bands."""
    if not tiers:
        return [list(row) for row in fallback]
    if isinstance(tiers, list):
        valid = []
        for row in tiers:
            if isinstance(row, (list, tuple)) and len(row) == 2 and isinstance(row[0], str) and row[0].strip():
                valid.append([row[0].strip(), float(row[1])])
        return valid or [list(row) for row in fallback]
    if isinstance(tiers, dict):
        bands: list[list[Any]] = []
        for tier_key, ratio in (("high", 1.0), ("medium", 0.65), ("low", 0.3)):
            items = split_terms(tiers.get(tier_key))
            if items:
                bands.append([_terms_to_regex(items), ratio])
        return bands or [list(row) for row in fallback]
    return [list(row) for row in fallback]


def default_scoring_base() -> dict[str, Any]:
    """Generic neutral scoring baseline suitable when no preset is selected."""
    return {
        "_설명": [
            "아웃바운드 계정 스코어링 기준(적합도 x 긴급도). 모르는 축은 감점이 아니라 분모에서 뺀다.",
            "점수 = 100 * sum(가중치 * 비율) / sum(적용된 가중치)",
        ],
        "cutoff": {
            "call_now": 70,
            "nurture": 45,
            "min_coverage": 0.4,
        },
        "fit": {
            "weights": {
                "revenue_model": 25,
                "industry": 35,
                "size": 20,
                "tech_stack": 20,
            },
            "revenue_model_bands": [
                ["구독|SaaS|subscription|MRR|ARR|B2B|엔터프라이즈|정기계약", 1.0],
                ["플랫폼|중개|마켓플레이스|라이선스|솔루션", 0.8],
                ["제조|유통|수출|커머스|브랜드|병원|공공|용역", 0.6],
            ],
            "industry_bands": [
                ["SaaS|소프트웨어|클라우드|AI|데이터|핀테크", 0.8],
                ["이커머스|물류|제조|헬스|바이오|교육|마케팅", 0.7],
                ["공공|기관|협회|건설|유통", 0.6],
            ],
            "size_bands": [
                ["유니콘|상장|코스피|코스닥|대기업|[1-9][0-9]{3,}명", 1.0],
                ["시리즈\\s*[CD]|스케일업|중견기업|[3-9][0-9]{2}명", 0.9],
                ["시리즈\\s*[AB]|프리\\s*A|중소기업|[5-9][0-9]명|1[0-9]{2}명|2[0-9]{2}명", 0.75],
                ["시드|seed|스타트업|[1-4][0-9]명", 0.5],
            ],
            "tech_stack_bands": [
                ["Salesforce|HubSpot|Snowflake|BigQuery|AWS|GCP|Azure|SAP|ERP", 0.9],
                ["Slack|Notion|Jira|Python|Kubernetes|Docker|Tableau|GA4", 0.7],
                ["엑셀|수기|레거시|온프레미스", 0.4],
            ],
        },
        "urgency": {
            "weights": {
                "exec_signal": 20,
                "funding": 25,
                "hiring": 30,
                "event_signal": 15,
                "competitor": 10,
            },
            "exec_bands": [
                ["도입|전환|확장|투자|자동화|글로벌|신사업|혁신", 1.0],
                ["효율화|생산성|개선|고도화|성장", 0.65],
                ["검토 중|관심|장기적으로", 0.3],
            ],
            "funding_bands": [
                ["시리즈\\s*[C-Z]|Series\\s*[C-Z]|프리\\s*IPO|[0-9]{3,}\\s*억", 1.0],
                ["시리즈\\s*B|Series\\s*B|[5-9][0-9]\\s*억", 0.9],
                ["시리즈\\s*A|Series\\s*A|프리\\s*A|[1-4][0-9]\\s*억", 0.75],
                ["시드|seed|엔젤|브릿지|투자\\s*유치|지원사업|조달|입찰", 0.5],
            ],
            "hiring_bands": [
                ["팀장|리드|매니저|총괄|헤드|디렉터|엔지니어|담당자", 0.85],
                ["기획|운영|영업|마케팅|개발|분석", 0.65],
                ["어시스턴트|보조|단기", 0.3],
            ],
            "event_bands": [
                ["대표|CEO|CTO|CDO|CIO|CFO|CHRO|부사장|본부장|임원", 1.0],
                ["팀장|리드|매니저|실장", 0.65],
                ["실무|담당|연구원", 0.35],
            ],
            "competitor_bands": [
                ["경쟁사|타사 솔루션|리플레이스|교체|전환 검토|비교", 1.0],
                ["인접 벤더|파트너사|세미나|박람회|전시회", 0.6],
            ],
            "recency_decay": [
                [30, 1.0],
                [90, 0.75],
                [180, 0.45],
                [365, 0.2],
            ],
        },
    }


def compile_sales_profile(config: dict[str, Any], home: str | Path | None = None) -> dict[str, Any]:
    """Compile a full account_score.py-compatible sales-profile.json from setup.json + preset."""
    profile = default_scoring_base()
    preset_id = str(config.get("sales_preset") or "").strip()
    preset: dict[str, Any] | None = None
    if preset_id and preset_id != "custom":
        try:
            preset = get_preset(preset_id, home)
        except ValueError:
            preset = None

    if preset and isinstance(preset.get("scoring"), dict):
        ps = preset["scoring"]
        if isinstance(ps.get("cutoff"), dict):
            profile["cutoff"].update(ps["cutoff"])
        for axis in ("fit", "urgency"):
            if isinstance(ps.get(axis), dict):
                if isinstance(ps[axis].get("weights"), dict):
                    profile[axis]["weights"].update(ps[axis]["weights"])
                for key, value in ps[axis].items():
                    if key.endswith("_bands") and isinstance(value, list):
                        profile[axis][key] = [list(row) for row in value]
                if axis == "urgency" and isinstance(ps[axis].get("recency_decay"), list):
                    profile[axis]["recency_decay"] = [list(row) for row in ps[axis]["recency_decay"]]

    # Apply structured no-code overrides from config.scoring_profile if provided
    custom = config.get("scoring_profile")
    if isinstance(custom, dict):
        if isinstance(custom.get("cutoff"), dict):
            for k in ("call_now", "nurture", "min_coverage"):
                if k in custom["cutoff"]:
                    profile["cutoff"][k] = custom["cutoff"][k]
        if isinstance(custom.get("fit_weights"), dict):
            for k, v in custom["fit_weights"].items():
                if k in profile["fit"]["weights"]:
                    profile["fit"]["weights"][k] = int(v)
        if isinstance(custom.get("urgency_weights"), dict):
            for k, v in custom["urgency_weights"].items():
                if k in profile["urgency"]["weights"]:
                    profile["urgency"]["weights"][k] = int(v)
        band_mapping = (
            ("fit", "industry_bands", custom.get("industry_tiers")),
            ("fit", "tech_stack_bands", custom.get("tech_stack_tiers")),
            ("fit", "revenue_model_bands", custom.get("revenue_model_tiers")),
            ("fit", "size_bands", custom.get("size_tiers")),
            ("urgency", "hiring_bands", custom.get("hiring_tiers")),
            ("urgency", "exec_bands", custom.get("exec_tiers")),
            ("urgency", "competitor_bands", custom.get("competitor_tiers")),
        )
        for axis, band_key, tier_val in band_mapping:
            if tier_val:
                profile[axis][band_key] = _tier_bands(tier_val, profile[axis][band_key])

    # Always boost the rep's explicit keywords / customer / job_keywords to top priority
    icp_terms = split_terms(config.get("keywords")) + split_terms(config.get("funding_keywords"))
    if icp_terms:
        rx = _terms_to_regex(icp_terms[:16])
        if rx and (not profile["fit"]["industry_bands"] or profile["fit"]["industry_bands"][0][0] != rx):
            profile["fit"]["industry_bands"].insert(0, [rx, 1.0])

    job_terms = split_terms(config.get("job_keywords")) + split_terms(config.get("jobs_query"))
    if job_terms:
        rx = _terms_to_regex(job_terms[:16])
        if rx and (not profile["urgency"]["hiring_bands"] or profile["urgency"]["hiring_bands"][0][0] != rx):
            profile["urgency"]["hiring_bands"].insert(0, [rx, 1.0])

    profile["meta"] = {
        "sales_preset": preset_id or "custom",
        "preset_name": preset.get("name", "사용자 직접 설정") if preset else "사용자 직접 설정",
        "product": str(config.get("product") or ""),
        "customer": str(config.get("customer") or ""),
    }
    return profile


def apply_preset_to_config(preset_id: str, overrides: dict[str, Any] | None = None,
                           home: str | Path | None = None) -> dict[str, Any]:
    """Build a complete secret-free setup.json dict pre-filled from a preset."""
    preset = get_preset(preset_id, home)
    overrides = overrides or {}
    scenario = overrides.get("scenario") or preset.get("default_scenario", "job_signal")
    workflow_map = {
        "job_signal": ["jobs"],
        "funding_signal": ["funding"],
        "tender_watch": ["tenders"],
        "overseas_partner": ["overseas"],
    }
    workflows = overrides.get("workflows") or preset.get("default_workflows") or workflow_map.get(scenario, ["jobs"])
    if workflow_map.get(scenario, ["jobs"])[0] not in workflows:
        workflows = [workflow_map[scenario][0], *[w for w in workflows if w != workflow_map[scenario][0]]]

    outreach = preset.get("outreach") or {}
    providers = list(preset.get("default_jobs_providers") or ["wanted", "saramin"])
    base: dict[str, Any] = {
        "version": 1,
        "target": "desktop",
        "install_location": "local",
        "os_hint": "auto",
        "desktop_mode": "terminal",
        "runtime_mode": "native",
        "model_provider": "auto",
        "model_auth": "later",
        "channel": "none",
        "telegram_owner": "",
        "discord_owner": "",
        "sales_preset": preset["id"],
        "campaign_name": f"{preset['name']} 아웃바운드 캠페인",
        "scenario": scenario,
        "workflows": workflows,
        "product": preset.get("product_example", ""),
        "customer": preset.get("customer_example", ""),
        "value_proposition": preset.get("value_proposition", ""),
        "proof_points": preset.get("proof_points", ""),
        "keywords": preset.get("keywords", ""),
        "job_keywords": preset.get("job_keywords", ""),
        "funding_keywords": preset.get("funding_keywords", ""),
        "region": preset.get("region", "대한민국"),
        "exclude_keywords": preset.get("exclude_keywords", "인턴, 아르바이트, 단기"),
        "source_mode": "sample",
        "source_path": "",
        "jobs_provider": "",
        "jobs_providers": providers,
        "jobs_query": preset.get("jobs_query", ""),
        "jobs_pages": 2,
        "jobs_fetch_details": True,
        "jobs_partial_ok": True,
        "funding_enrich_hiring": True,
        "ats_provider": "",
        "ats_board": "",
        "ats_company": "",
        "ats_targets_path": "",
        "draft_language": outreach.get("language", "ko"),
        "draft_mode": "template",
        "drafts_path": "",
        "outreach_tone": outreach.get("tone", "consultative"),
        "outreach_channel": outreach.get("channel", "email"),
        "sender_name": "",
        "sender_company": "",
        "sender_role": "",
        "sender_contact": "",
        "sender_cta": outreach.get("cta", ""),
        "do_not_contact": [],
        "services": [],
        "vault_mode": "new",
        "vault_path": "~/Documents/Hermes-GTM",
    }
    base.update({k: v for k, v in overrides.items() if v is not None})
    # Ensure live job_signal has explicit jobs_provider when source_mode == "live"
    if base.get("source_mode") == "live" and base.get("scenario") == "job_signal" and not base.get("jobs_provider"):
        base["jobs_provider"] = "multi" if len(base.get("jobs_providers") or []) > 1 else (
            (base.get("jobs_providers") or ["wanted"])[0]
        )
    return base
