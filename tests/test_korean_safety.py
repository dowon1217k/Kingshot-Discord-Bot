"""Offline contracts for the Korean alliance fork."""
import asyncio
import json
import ssl
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cogs import gift_redemption as gr, gift_state_resolver as resolver
from cogs.runtime_policy import live_redemption_enabled, sharing_url, secure_service_url
from cogs.i18n import tr


@pytest.mark.parametrize('label', ['Code', 'code', '교환코드', '쿠폰', '코드'])
@pytest.mark.parametrize('colon', [':', '：'])
def test_detects_codes_in_content_and_embeds(label, colon):
    text = f'**{label}{colon}** `ABC123`'
    assert gr._extract_content_codes(text) == ['ABC123']
    msg = SimpleNamespace(embeds=[SimpleNamespace(title=None, description=text, fields=[])])
    assert gr._extract_embed_codes(msg) == ['ABC123']


def test_disabled_game_paths_never_touch_session_or_cog(monkeypatch):
    monkeypatch.delenv('KINGSHOT_ENABLE_LIVE_REDEMPTION', raising=False)
    assert not live_redemption_enabled()
    cog, session = Mock(), Mock()
    assert asyncio.run(gr.claim_giftcode_rewards_wos(cog, 1, 'ABC')) == 'ERROR'
    assert asyncio.run(gr.redeem_giftcode_once(cog, 1, 'ABC', 1, session)) == 'ERROR'
    assert asyncio.run(resolver._probe(cog, session, 1, 1, 'ABC')) == 'error'
    assert asyncio.run(gr.validate_gift_code_immediately(cog, 'ABC')) == (None, tr('gift.disabled'))
    assert cog.mock_calls == session.mock_calls == []


@pytest.mark.parametrize('url', ['', 'http://example.com/api', 'https://user:pass@example.com/api'])
def test_sharing_rejects_missing_or_unsafe_urls(monkeypatch, url):
    monkeypatch.setenv('KINGSHOT_ENABLE_CODE_SHARING', '1')
    monkeypatch.setenv('KINGSHOT_CODE_SHARING_URL', url)
    assert sharing_url() is None


def test_sharing_requires_both_operator_choices(monkeypatch):
    monkeypatch.setenv('KINGSHOT_CODE_SHARING_URL', 'https://example.com/api')
    assert sharing_url() is None
    monkeypatch.setenv('KINGSHOT_ENABLE_CODE_SHARING', '1')
    assert sharing_url() == 'https://example.com/api'


def test_disabled_sharing_methods_never_access_db_or_http():
    from cogs.gift_operationsapi import GiftCodeAPI
    api = GiftCodeAPI.__new__(GiftCodeAPI)
    for call in (api.sync_with_api(), api.add_giftcode('ABC'), api.remove_giftcode('ABC'), api.check_giftcode('ABC')):
        assert asyncio.run(call) is False


def test_tls_verification_remains_enabled():
    ctx = ssl.create_default_context()
    assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
    source = Path('cogs/gift_operationsapi.py').read_text()
    assert 'CERT_NONE' not in source and 'check_hostname = False' not in source
    assert 'allow_redirects=False' in source


def test_remote_http_rejected_local_test_server_allowed():
    assert not secure_service_url('http://example.com')
    assert secure_service_url('https://example.com')
    assert secure_service_url('http://127.0.0.1:8080')


def test_translation_catalog_keys_resolve():
    import ast
    catalog = json.loads(Path('cogs/locales/ko.json').read_text())
    for path in Path('cogs').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr':
                key = node.args[0]
                if isinstance(key, ast.Constant):
                    assert key.value in catalog, (path, key.value)


def test_opted_in_redemption_posts_signed_payload_without_redirects():
    cog = SimpleNamespace(wos_encrypt_key='test-key', wos_giftcode_url='https://example.com/api',
                          giftlog=Mock(), logger=Mock())
    response = SimpleNamespace(status_code=200, headers={}, json=lambda: {'msg': 'SUCCESS'}, text='')
    session = SimpleNamespace(post=Mock(return_value=response))
    assert asyncio.run(gr.redeem_giftcode_once(cog, 123, 'ABC', 259, session)) == 'SUCCESS'
    kwargs = session.post.call_args.kwargs
    assert kwargs['allow_redirects'] is False
    assert kwargs['data']['fid'] == '123' and kwargs['data']['cdk'] == 'ABC'
    assert kwargs['data']['kid'] == '259' and kwargs['data']['sign']


def test_disabled_channel_validation_preserves_pending_code_and_history(monkeypatch):
    import sqlite3
    monkeypatch.delenv('KINGSHOT_ENABLE_LIVE_REDEMPTION', raising=False)
    conn = sqlite3.connect(':memory:')
    conn.executescript('CREATE TABLE gift_codes (giftcode TEXT PRIMARY KEY, date TEXT, validation_status TEXT);'
                       'CREATE TABLE user_giftcodes (fid INTEGER, giftcode TEXT, status TEXT);'
                       "INSERT INTO user_giftcodes VALUES (123, 'OLDER', 'SUCCESS');")
    cog = SimpleNamespace(cursor=conn.cursor(), conn=conn, logger=Mock())
    asyncio.run(gr.handle_gift_validate_process(cog, {'id': 1, 'details': {'giftcode': 'ABC'}}))
    assert conn.execute('SELECT giftcode, validation_status FROM gift_codes').fetchall() == [('ABC', 'pending')]
    assert conn.execute('SELECT * FROM user_giftcodes').fetchall() == [(123, 'OLDER', 'SUCCESS')]
    conn.close()
