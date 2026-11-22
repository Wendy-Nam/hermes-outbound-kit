#!/usr/bin/env python3
"""Portable configuration and isolated Hermes pack installer. Python 3.10+."""
from pathlib import Path as _BootPath
import sys as _boot_sys
if str(_BootPath(__file__).resolve().parents[2]) not in _boot_sys.path:
    _boot_sys.path.insert(0, str(_BootPath(__file__).resolve().parents[2]))
import src as _src_bootstrap  # noqa: E402,F401
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
import paths

import profile_presets

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {'version', 'target', 'channel', 'telegram_owner', 'discord_owner',
          'product', 'customer', 'keywords', 'services', 'workflows', 'job_keywords',
          'funding_keywords', 'region', 'exclude_keywords', 'vault_mode', 'vault_path',
          'install_location', 'os_hint', 'runtime_mode', 'install_home',
          'server_host', 'server_port', 'server_user', 'ssh_key_path', 'ssh_key_action',
          'ssh_auth', 'model_provider', 'model_auth', 'telegram_mode',
          'discord_guild_id', 'discord_channel_id', 'discord_message_content_intent',
          'webshare_allowed_target', 'groq_audio_consent', 'apify_actor_name',
          'apify_budget_usd', 'composio_apps', 'vault_existing_approved',
          'vault_collision_policy', 'review_human_approval', 'review_terms_costs',
          'review_no_secrets', 'webshare_policy_ack', 'apify_cost_ack', 'composio_scope_ack',
          'scenario', 'source_mode', 'source_path',
          'ats_provider', 'ats_board', 'ats_company', 'ats_targets_path',
          'jobs_provider', 'jobs_providers', 'jobs_query', 'jobs_pages',
          'jobs_fetch_details', 'jobs_partial_ok', 'funding_enrich_hiring',
          'tender_type', 'g2b_keywords', 'overseas_rss_urls',
          'sales_preset', 'value_proposition', 'proof_points',
          'end_user_persona', 'buyer_persona', 'common_misconception',
          'reality_differentiator', 'partial_entry_offer',
          'outreach_tone', 'outreach_channel',
          'sender_name', 'sender_company', 'sender_role', 'sender_contact', 'sender_cta',
          'do_not_contact', 'scoring_profile',
          'jev_enabled', 'jev_model', 'jev_min_relevance', 'jev_qa_drafts',
          'campaign_name', 'draft_language',
          'draft_mode', 'desktop_mode', 'schedule_enabled', 'schedule_frequency',
          'schedule_time', 'timezone', 'output_path', 'gateway_enabled',
          'service_apply_enabled', 'drafts_path'}
CHOICES = {'services': {'webshare', 'groq', 'apify', 'composio', 'jev', 'firecrawl'},
           'workflows': {'jobs', 'funding', 'tenders', 'overseas'},
           'jobs_providers': {'wanted', 'saramin', 'jobkorea', 'jumpit', 'ats', 'ats_batch', 'greeting'}}
BOOL_FIELDS = {'discord_message_content_intent', 'groq_audio_consent',
               'vault_existing_approved', 'review_human_approval',
               'review_terms_costs', 'review_no_secrets', 'webshare_policy_ack',
               'apify_cost_ack', 'composio_scope_ack',
               'schedule_enabled', 'gateway_enabled', 'service_apply_enabled',
               'jobs_fetch_details', 'jobs_partial_ok', 'funding_enrich_hiring',
               'jev_enabled', 'jev_qa_drafts'}
ENUM_FIELDS = {'install_location': {'local', 'remote'},
               'os_hint': {'auto', 'macos', 'windows', 'linux'},
               'runtime_mode': {'native', 'wsl2'},
               'ssh_key_action': {'existing', 'generate'},
               'ssh_auth': {'existing_key', 'generate_key', 'password_bootstrap'},
               'telegram_mode': {'direct', 'group'},
               'vault_collision_policy': {'preview_stop'},
               'scenario': {'job_signal', 'funding_signal', 'tender_watch', 'overseas_partner'},
               'source_mode': {'sample', 'file', 'live'},
               'ats_provider': {'', 'greenhouse', 'lever', 'ashby', 'greeting'},
               'jobs_provider': {'', 'ats', 'ats_batch', 'wanted', 'saramin', 'jobkorea',
                                 'jumpit', 'greeting', 'both', 'multi', 'all'},
               'draft_mode': {'template', 'hermes', 'provided'},
               'draft_language': {'ko', 'en'},
               'outreach_tone': {'', 'formal', 'consultative', 'concise', 'friendly'},
               'outreach_channel': {'', 'email', 'linkedin', 'call'},
               'tender_type': {'', 'all', 'servc', 'thng', 'cnstwk', 'frgcpt'},
               'desktop_mode': {'app', 'terminal'},
               'schedule_frequency': {'daily', 'hourly'}}
SCORING_PROFILE_KEYS = {
    'cutoff', 'fit_weights', 'urgency_weights',
    'industry_tiers', 'tech_stack_tiers', 'revenue_model_tiers',
    'size_tiers', 'hiring_tiers', 'exec_tiers', 'competitor_tiers',
}


def _validate_scoring_profile(sp):
    if not isinstance(sp, dict) or set(sp) - SCORING_PROFILE_KEYS:
        raise ValueError('scoring_profile: 지원하지 않는 채점 설정 항목이 포함되어 있습니다.')
    if 'cutoff' in sp:
        cutoff = sp['cutoff']
        if not isinstance(cutoff, dict) or set(cutoff) - {'call_now', 'nurture', 'min_coverage'}:
            raise ValueError('scoring_profile.cutoff 형식이 잘못되었습니다.')
        for k in ('call_now', 'nurture'):
            if k in cutoff and (not isinstance(cutoff[k], (int, float)) or isinstance(cutoff[k], bool) or not 0 <= cutoff[k] <= 100):
                raise ValueError(f'scoring_profile.cutoff.{k}: 0~100 숫자가 필요합니다.')
        if 'min_coverage' in cutoff:
            mc = cutoff['min_coverage']
            if not isinstance(mc, (int, float)) or isinstance(mc, bool) or not 0 <= mc <= 1:
                raise ValueError('scoring_profile.cutoff.min_coverage: 0~1 사이 숫자가 필요합니다.')
    for wkey, allowed in (('fit_weights', {'revenue_model', 'industry', 'size', 'tech_stack'}),
                          ('urgency_weights', {'exec_signal', 'funding', 'hiring', 'event_signal', 'competitor'})):
        if wkey in sp:
            weights = sp[wkey]
            if not isinstance(weights, dict) or set(weights) - allowed:
                raise ValueError(f'scoring_profile.{wkey}: 지원하지 않는 축 이름입니다.')
            for k, v in weights.items():
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 100:
                    raise ValueError(f'scoring_profile.{wkey}.{k}: 0~100 숫자가 필요합니다.')
    for tkey in SCORING_PROFILE_KEYS - {'cutoff', 'fit_weights', 'urgency_weights'}:
        if tkey in sp:
            val = sp[tkey]
            if not isinstance(val, (dict, list)):
                raise ValueError(f'scoring_profile.{tkey}: dict 또는 list가 필요합니다.')


def validate(data):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ValueError('지원하지 않는 설정 필드입니다. 토큰/키를 setup.json에 넣지 마세요.')
    if type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('version must be 1')
    if data.get('target') not in ('desktop', 'server'):
        raise ValueError('desktop/server를 선택하세요.')
    if data.get('channel') not in ('none', 'telegram', 'discord', 'both'):
        raise ValueError('채널 선택이 잘못되었습니다.')
    for key, choices in CHOICES.items():
        values = data.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or v not in choices for v in values) or len(values) != len(set(values)):
            raise ValueError(f'{key}: 지원하는 항목을 중복 없이 선택하세요.')
    if data.get('vault_mode', 'none') not in ('none', 'new', 'existing'):
        raise ValueError('vault_mode: none/new/existing 중 선택하세요.')
    for key in BOOL_FIELDS:
        if key in data and type(data[key]) is not bool:
            raise ValueError(f'{key}: true/false 값이 필요합니다.')
    for key, choices in ENUM_FIELDS.items():
        if key in data and (not isinstance(data[key], str) or data[key] not in choices):
            raise ValueError(f'{key}: 지원하지 않는 선택입니다.')
    if 'sales_preset' in data and data['sales_preset']:
        preset_val = data['sales_preset']
        allowed_presets = {'custom', *profile_presets.preset_ids()}
        if not isinstance(preset_val, str) or preset_val not in allowed_presets:
            raise ValueError(f'sales_preset: 지원하지 않는 프리셋입니다 ({preset_val}).')
    if 'server_port' in data and (type(data['server_port']) is not int or not 1 <= data['server_port'] <= 65535):
        raise ValueError('server_port: 1~65535 숫자가 필요합니다.')
    if 'jobs_pages' in data and (type(data['jobs_pages']) is not int or not 1 <= data['jobs_pages'] <= 5):
        raise ValueError('jobs_pages: 1~5 정수가 필요합니다.')
    if 'jev_min_relevance' in data:
        jmr = data['jev_min_relevance']
        if not isinstance(jmr, (int, float)) or isinstance(jmr, bool) or not 0 <= jmr <= 1:
            raise ValueError('jev_min_relevance: 0~1 사이 숫자가 필요합니다.')
    apps = data.get('composio_apps', [])
    if not isinstance(apps, list) or len(apps) > 20 or any(not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9 _-]{1,60}', s) for s in apps):
        raise ValueError('composio_apps: 앱 이름 목록만 허용합니다.')
    dnc = data.get('do_not_contact', [])
    if not isinstance(dnc, list) or len(dnc) > 500 or any(
        not isinstance(s, str) or len(s) > 200 or any(ord(c) < 32 for c in s) for s in dnc
    ):
        raise ValueError('do_not_contact: 회사명 문자열 목록(최대 500개)만 허용합니다.')
    if 'scoring_profile' in data and data['scoring_profile'] is not None:
        _validate_scoring_profile(data['scoring_profile'])
    non_string_fields = {'version', *CHOICES, *BOOL_FIELDS, 'server_port', 'jobs_pages',
                         'jev_min_relevance', 'composio_apps', 'do_not_contact', 'scoring_profile'}
    for key in FIELDS - non_string_fields:
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > 1000 or any(ord(c) < 32 for c in value):
            raise ValueError(f'{key}: 한 줄 텍스트만 입력하세요 (1000자 이하).')
    if data.get('install_location') == 'remote':
        if data.get('target') != 'server':
            raise ValueError('원격 설치는 target=server여야 합니다.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', data.get('server_host', '')):
            raise ValueError('server_host: URL이 아닌 서버 IP/호스트명이 필요합니다.')
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]{0,63}', data.get('server_user', '')):
            raise ValueError('server_user: SSH 사용자명이 필요합니다.')
    for key in ('discord_guild_id', 'discord_channel_id'):
        if data.get(key) and not re.fullmatch(r'[1-9][0-9]{3,24}', data[key]):
            raise ValueError(f'{key}: 숫자 ID가 필요합니다.')
    if data.get('apify_budget_usd') and not re.fullmatch(r'\d{1,6}(\.\d{1,2})?', data['apify_budget_usd']):
        raise ValueError('apify_budget_usd: 0 이상 금액을 입력하세요.')
    if data.get('schedule_time') and not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', data['schedule_time']):
        raise ValueError('schedule_time: 예를 들어 09:00처럼 입력하세요.')
    scenario_workflow = {'job_signal':'jobs', 'funding_signal':'funding',
                         'tender_watch':'tenders', 'overseas_partner':'overseas'}
    if data.get('scenario') and data.get('workflows') and scenario_workflow[data['scenario']] not in data['workflows']:
        raise ValueError('선택한 시나리오와 업무 종류가 달라요. 같은 업무를 선택해주세요.')
    if data.get('source_mode') == 'file' and not data.get('source_path', '').strip():
        raise ValueError('파일 자료로 진행하려면 source_path를 지정해주세요.')
    if data.get('source_mode') == 'file' and Path(data['source_path']).suffix.lower() not in {'.csv','.json'}:
        raise ValueError('자료 파일은 CSV 또는 JSON으로 선택해주세요.')
    jobs_provider = data.get('jobs_provider', '')
    jobs_providers = data.get('jobs_providers', [])
    jobs_query = data.get('jobs_query', '').strip()
    live_jobs = data.get('scenario') == 'job_signal' and data.get('source_mode') == 'live'
    if len(jobs_query) > 200:
        raise ValueError('채용 사이트 검색어는 200자 이하로 입력해주세요.')
    if live_jobs:
        effective_providers = list(jobs_providers) if jobs_providers else []
        if not effective_providers:
            if jobs_provider == 'both':
                effective_providers = ['wanted', 'saramin']
            elif jobs_provider == 'all':
                effective_providers = ['wanted', 'saramin', 'jobkorea', 'jumpit']
            elif jobs_provider and jobs_provider != 'multi':
                effective_providers = [jobs_provider]
            elif data.get('ats_provider'):
                effective_providers = ['ats']
        if not effective_providers:
            raise ValueError('실시간 채용 신호에 사용할 공개 채용 사이트를 선택해주세요.')
        if 'ats' in effective_providers:
            if (not data.get('ats_provider') or not data.get('ats_board', '').strip()
                    or not data.get('ats_company', '').strip()):
                raise ValueError('단일 ATS 조회에는 게시판 종류, 공개 식별자, 회사 이름이 필요합니다.')
        search_boards = {'wanted', 'saramin', 'jobkorea', 'jumpit'}
        if any(p in search_boards for p in effective_providers) and not jobs_query:
            raise ValueError('원티드/사람인/잡코리아/점핏 조회에는 직무·기술 검색어(jobs_query)가 필요합니다.')
    if data.get('draft_mode') == 'provided' and not data.get('drafts_path', '').strip():
        raise ValueError('작성한 AI 초안을 가져오려면 drafts_path에 JSON 파일을 지정해주세요.')
    if data.get('install_location') == 'remote' and data.get('desktop_mode') == 'app':
        raise ValueError('원격 서버에서는 desktop_mode=terminal로 설정해주세요.')
    for channel in channels(data):
        if not re.fullmatch(r'[1-9][0-9]{3,24}', data.get(channel + '_owner', '')):
            raise ValueError(f'{channel}: 본인의 숫자 사용자 ID가 필요합니다.')
    for key in ('product', 'customer'):
        if not data.get(key, '').strip():
            raise ValueError(f'{key}를 입력하세요.')
    return data


def channels(data):
    return ['telegram', 'discord'] if data.get('channel') == 'both' else (
        [] if data.get('channel') == 'none' else [data.get('channel')])


def load(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def preserve_write(path, text, *, private=False):
    """Create only or verify identical content; never overwrite user changes."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f'심볼릭 링크 대상은 지원하지 않습니다: {path.name}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding='utf-8') != text:
            raise ValueError(f'기존 파일을 보존했습니다: {path}. 새 경로를 선택하세요.')
        return
    with path.open('x', encoding='utf-8') as stream:
        stream.write(text)
    if private and os.name == 'posix':
        os.chmod(path, 0o600)


def _seed_sales_profile(data, home):
    """설치 답변과 직군 프리셋으로 사용자용 채점 기준(sales-profile.json)을 처음 한 번 만든다."""
    target = home / 'sales-profile.json'
    if target.exists():
        return
    profile = profile_presets.compile_sales_profile(data, home)
    profile.setdefault('_설명', []).append(
        '설치 답변(프리셋·keywords·job_keywords·scoring_profile)으로 자동 생성했다. 자유롭게 고쳐도 재설치 때 덮지 않는다.'
    )
    preserve_write(target, json.dumps(profile, ensure_ascii=False, indent=2) + '\n', private=True)


def _seed_sender_profile(data, home):
    """발신자 프로필 필드가 있으면 sender-profile.json을 처음 한 번 생성한다."""
    target = home / 'sender-profile.json'
    if target.exists():
        return
    sender = {
        'name': data.get('sender_name') or '',
        'company': data.get('sender_company') or '',
        'role': data.get('sender_role') or '',
        'contact': data.get('sender_contact') or '',
        'cta': data.get('sender_cta') or '',
        'tone': data.get('outreach_tone') or 'consultative',
        'channel': data.get('outreach_channel') or 'email',
        'value_proposition': data.get('value_proposition') or '',
        'proof_points': data.get('proof_points') or '',
    }
    if any(sender[k] for k in ('name', 'company', 'contact', 'cta', 'value_proposition')):
        preserve_write(target, json.dumps(sender, ensure_ascii=False, indent=2) + '\n', private=True)


def _seed_dnc(data, home):
    """연락 금지 목록(do_not_contact)이 있으면 do-not-contact.txt를 처음 한 번 생성한다."""
    target = home / 'do-not-contact.txt'
    dnc = [item.strip() for item in (data.get('do_not_contact') or []) if isinstance(item, str) and item.strip()]
    if target.exists() or not dnc:
        return
    header = '# 연락 금지(Do-Not-Contact) 회사 목록 — 한 줄에 한 회사\n'
    preserve_write(target, header + '\n'.join(dict.fromkeys(dnc)) + '\n', private=True)


def _seed_ats_targets(home):
    """사용자 수정용 ats-targets.json 사본을 $HERMES_HOME에 처음 한 번 복사한다."""
    target = home / 'ats-targets.json'
    source = ROOT / 'pack' / 'skills' / 'ats-search' / 'data' / 'ats-targets.json'
    if target.exists() or not source.exists():
        return
    preserve_write(target, source.read_text(encoding='utf-8'), private=True)


def install(data, home):
    home = Path(home).expanduser().absolute()
    if any(p.is_symlink() for p in (home, *home.parents)):
        raise ValueError('설치 경로에 심볼릭 링크가 있습니다.')
    home.mkdir(parents=True, exist_ok=True)
    if os.name == 'posix':
        os.chmod(home, 0o700)
    managed = {home / 'outbound-profile.json': json.dumps(data, ensure_ascii=False, indent=2) + '\n'}
    for src in sorted((ROOT / 'pack').rglob('*')):
        if src.is_file() and '__pycache__' not in src.parts and src.suffix != '.pyc':
            managed[home / src.relative_to(ROOT / 'pack')] = src.read_text(encoding='utf-8')
    for path, content in managed.items():
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('설치 대상 링크는 지원하지 않습니다.')
        if path.exists() and path.read_text(encoding='utf-8') != content:
            raise ValueError(f'기존 변경을 보존했습니다: {path}')
    for path, content in managed.items():
        preserve_write(path, content, private=(path.name == 'outbound-profile.json'))
    _seed_sales_profile(data, home)
    _seed_sender_profile(data, home)
    _seed_dnc(data, home)
    _seed_ats_targets(home)
    print('스킬 팩 설치 완료. 모델/채널 연결은 아직 별도 확인이 필요합니다.')


def check_token(channel, token):
    if not token or any(c.isspace() for c in token):
        raise ValueError('토큰 형식을 확인하세요.')
    if channel == 'telegram':
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
            raise ValueError('Telegram 토큰 형식이 잘못되었습니다.')
        req = urllib.request.Request('https://api.telegram.org/bot' + token + '/getMe')
    else:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', token):
            raise ValueError('Discord 토큰 형식이 잘못되었습니다.')
        req = urllib.request.Request('https://discord.com/api/v10/users/@me',
                                     headers={'Authorization': 'Bot ' + token})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(req, timeout=15) as response:
            body = json.load(response)
        valid = body.get('ok') and body.get('result', {}).get('is_bot') if channel == 'telegram' else body.get('bot')
        if not valid:
            raise ValueError('bot response invalid')
    except Exception:
        raise ValueError(f'{channel} 연결 확인 실패. 토큰·네트워크를 확인하세요.') from None


def connect(data, home):
    path = Path(home).expanduser().absolute() / '.env'
    if not channels(data):
        print('로컬 대화 모드: 채널 토큰이 필요하지 않습니다.')
        return
    if any(p.is_symlink() for p in path.parents):
        raise ValueError('비밀값 저장 경로에 심볼릭 링크가 있습니다.')
    if path.is_symlink():
        raise ValueError('비밀값 저장 파일이 심볼릭 링크입니다.')
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    values = {}
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        if key in values:
            raise ValueError(f'.env에 중복 키가 있습니다: {key}')
        values[key] = value
    updates, reused = {}, []
    for channel in channels(data):
        prefix = channel.upper()
        token_key, owner_key = prefix + '_BOT_TOKEN', prefix + '_ALLOWED_USERS'
        token_present, owner_present = token_key in values, owner_key in values
        if token_present != owner_present or (token_present and not values[token_key]):
            raise ValueError(f'{channel} 설정이 일부만 있습니다. 기존 값을 보존했습니다. gateway setup으로 복구하세요.')
        if token_present:
            if values[owner_key] != data[channel + '_owner']:
                raise ValueError(f'{channel} 기존 허용 사용자와 setup.json이 다릅니다. 기존 값을 보존했습니다.')
            reused.append(channel)
            continue
        token = getpass.getpass(channel + ' Bot token (화면에 표시되지 않음): ')
        check_token(channel, token)
        updates[token_key] = token
        updates[owner_key] = data[channel + '_owner']
    if updates:
        # Shared with optional services: cross-platform interprocess lock, additive merge,
        # fsync and atomic replacement. A concurrent writer or existing binding is refused.
        from services import merge_env_additive
        merge_env_additive(path.parent, updates)
    elif path.exists() and os.name == 'posix':
        # A resumed configuration may predate the atomic writer. Tighten its mode without
        # reading, validating or replacing the existing token value.
        from services import env_lock
        with env_lock(path.parent):
            if path.is_symlink():
                raise ValueError('비밀값 저장 파일이 심볼릭 링크입니다.')
            os.chmod(path, 0o600)
    detail = []
    if updates:
        detail.append('새 토큰 확인·저장')
    if reused:
        detail.append('기존 설정 보존(재검증 안 함): ' + ', '.join(reused))
    print('채널 설정 완료 (' + '; '.join(detail) + '). 실제 메시지는 gateway 시작 후 확인하세요.')


def sample(data, output):
    rows = json.loads((ROOT / 'samples/accounts.json').read_text(encoding='utf-8'))
    result = []
    for row in rows:
        known = [v for v in row['fit'].values() if v is not None]
        row['coverage'] = len(known) / len(row['fit'])
        row['fit_score'] = round(sum(known) / len(known) * 100) if known else None
        row['decision'] = 'review' if row['coverage'] >= 0.66 else 'research_needed'
        result.append(row)
    result.sort(key=lambda r: (r['decision'] == 'review', r['fit_score'] or 0), reverse=True)
    out = Path(output)
    preserve_write(out / 'accounts.json', json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    draft = '# 합성 데이터 실습 — 실제 조사/모델 생성 결과 아님\n\n'
    for row in result:
        if row['decision'] == 'review':
            draft += (f"## {row['name']} — 검토용 템플릿\n"
                      f"제안: {data['product']}\n대상 조건: {data['customer']}\n"
                      f"샘플 신호: {row['signal']}\n"
                      '초안: 안녕하세요. 위 신호와 관련해 저희 제안이 도움이 될지 확인하고 싶습니다. '
                      '간단한 소개 자료를 보내드려도 괜찮을까요?\n'
                      '검토: 실제 출처·회사·연락 대상은 별도 확인. 자동 발송 없음.\n\n')
    preserve_write(out / 'drafts.md', draft)
    print('샘플 3건 평가 완료: accounts.json / drafts.md (합성 데이터, 모델 호출 없음)')


def hermes(home, command):
    executable = paths.resolve_hermes(home, required=False)
    if not executable:
        raise ValueError('Hermes가 없습니다. docs/PREPARE.md와 설치 지원 SKILL.md를 따라 엔진을 설치하세요.')
    env = dict(os.environ, HERMES_HOME=str(Path(home).expanduser().absolute()))
    return subprocess.call([str(executable), *command], env=env)


def main():
    parser = argparse.ArgumentParser(description='Hermes Outbound Kit')
    parser.add_argument('action', choices=['wizard', 'setup', 'validate', 'install', 'connect', 'sample', 'model', 'chat', 'gateway', 'doctor'])
    parser.add_argument('--config', default=str(ROOT / 'setup.json'))
    parser.add_argument('--home')
    parser.add_argument('--output', default=str(ROOT / 'output'))
    args = parser.parse_args()
    try:
        args.home = str(paths.normalize_home(args.home))
        if args.action == 'wizard':
            webbrowser.open((ROOT / 'wizard.html').as_uri())
            print('입력 화면을 열었습니다. setup.json을 이 키트 폴더에 저장하세요.')
        elif args.action in ('model', 'chat', 'gateway', 'doctor'):
            return hermes(args.home, ['gateway', 'run'] if args.action == 'gateway' else [args.action])
        else:
            data = load(args.config)
            if data.get('install_location') == 'remote' and args.action != 'validate':
                raise ValueError('원격 서버 설정을 이 컴퓨터에 적용하지 않습니다. installer.py plan과 server_access.py를 먼저 사용하세요.')
            if args.action == 'setup':
                import installer
                return installer.main(['setup', '--config', args.config, '--home', args.home,
                                       '--output', args.output])
            elif args.action == 'validate':
                print('설정 검사 통과 (비밀값 없음)')
            elif args.action == 'install':
                install(data, args.home)
            elif args.action == 'connect':
                connect(data, args.home)
            else:
                sample(data, args.output)
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print('오류: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
