"""Discord bot identity check, exercised only with fake profiles and transport."""
import importlib
import json
import os

import pytest


def module():
    try:
        return importlib.import_module('scripts.social.channels.discord.readonly_auth')
    except ModuleNotFoundError:
        pytest.fail('Discord bot read-only check is missing')


def test_matching_bot_id_does_not_claim_channel_or_publish_access():
    result = module().interpret_bot(200, {'id': '123', 'bot': True, 'username': 'private'}, expected_bot_id='123')
    assert result == {'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False,
                      'channel_access_verified': False, 'publish_authorized': False}


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (200, {'id': '456', 'bot': True}, 'mismatch'),
    (200, {'id': '123', 'bot': False}, 'unknown'),
    (200, {'id': '123', 'bot': 1}, 'unknown'),
    (200, {'id': '123'}, 'unknown'),
    (200, {'id': '123', 'bot': True, 'message': 'error', 'code': 1}, 'unknown'),
    (200, {'id': '123', 'bot': True, 'status': 403, 'title': 'Forbidden'}, 'unknown'),
    (200, {'id': 123, 'bot': True}, 'unknown'),
    (403, {'id': '123', 'bot': True}, 'unknown'),
])
def test_bot_response_requires_consistent_bot_identity(status, body, expected):
    assert module().interpret_bot(status, body, expected_bot_id='123')['identity'] == expected


def test_bot_transport_fixed_readonly_and_output_sanitized(monkeypatch):
    target = module()
    calls = []
    class Response:
        status = 200
        def read(self, size): return b'{"id":"123","bot":true,"username":"private"}'
    class Connection:
        def __init__(self, host, timeout): calls.append((host, timeout))
        def request(self, method, path, headers): calls.append((method, path, headers))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    result = target.check_bot('fake-token', '123')
    assert calls[0] == ('discord.com', 10)
    assert calls[1][:2] == ('GET', '/api/v10/users/@me')
    assert calls[1][2]['Authorization'] == 'Bot fake-token'
    assert result['identity'] == 'match'
    assert not any(value in str(result) for value in ('fake-token', '123', 'private'))


def test_snowflake_upper_bound_and_invalid_expected_identity():
    target = module()
    top = str(2**64 - 1)
    overflow = str(2**64)
    assert target.interpret_bot(200, {'id': top, 'bot': True}, expected_bot_id=top)['identity'] == 'match'
    assert target.interpret_bot(200, {'id': overflow, 'bot': True}, expected_bot_id=top)['identity'] == 'unknown'
    with pytest.raises(ValueError): target.interpret_bot(200, {'id': top, 'bot': True}, expected_bot_id=overflow)


def test_profile_schema_is_distinct_and_file_hardlinks_rejected(tmp_path, monkeypatch):
    target = module()
    folder = tmp_path / 'fixture-valid'
    folder.mkdir()
    path = folder / 'discord-bot-userinfo.json'
    path.write_text(json.dumps({'schema': 'discord-bot-userinfo/1', 'provider': 'discord',
        'token_kind': 'bot_token', 'application_id': '456', 'expected_bot_id': '123', 'bot_token': 'fake-token'}),
        encoding='utf-8')
    calls = []
    monkeypatch.setattr(target, 'check_bot', lambda *a: calls.append('called') or {
        'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False,
        'channel_access_verified': False, 'publish_authorized': False})
    assert target.check_profile(tmp_path, 'fixture-valid')['identity'] == 'match'
    folder2 = tmp_path / 'fixture-other'
    folder2.mkdir()
    os.link(path, folder2 / 'discord-bot-userinfo.json')
    calls.clear()
    with pytest.raises(ValueError): target.check_profile(tmp_path, 'fixture-other')
    assert calls == []


def test_profile_rejects_application_id_overflow_before_transport(tmp_path, monkeypatch):
    target = module()
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    (folder / 'discord-bot-userinfo.json').write_text(json.dumps({'schema': 'discord-bot-userinfo/1',
        'provider': 'discord', 'token_kind': 'bot_token', 'application_id': str(2**64),
        'expected_bot_id': '123', 'bot_token': 'fake-token'}), encoding='utf-8')
    monkeypatch.setattr(target, 'check_bot', lambda *a: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_profile(tmp_path, 'fixture-account')


@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
def test_non_200_never_reads_or_redirects(monkeypatch, status):
    target = module()
    class Response:
        def read(self, size): pytest.fail('unexpected read')
    response = Response()
    response.status = status
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    assert target.check_bot('fake-token', '123')['identity'] == 'unknown'


@pytest.mark.parametrize('raw', [b'{"id":"123","id":"456","bot":true}', b'{"bot":NaN}',
                                 b'x' * 65537, b'\xff'], ids=['duplicate', 'nan', 'oversize', 'invalid-utf8'])
def test_bad_response_is_unknown(monkeypatch, raw):
    target = module()
    class Response:
        status = 200
        def read(self, size): return raw
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    assert target.check_bot('fake-token', '123')['identity'] == 'unknown'


def test_invalid_token_does_not_open_network(monkeypatch):
    target = module()
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', lambda *a, **kw: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_bot('bad\r\nheader', '123')
    with pytest.raises(ValueError): target.check_bot('fake-token', 'invalid')


def test_cli_requires_explicit_flag_and_rejects_token_argument(tmp_path, monkeypatch, capsys):
    target = module()
    monkeypatch.setattr(target.Path, 'home', lambda: tmp_path)
    calls = []
    def fake(root, alias):
        calls.append((root, alias))
        return {'config_valid': True, 'identity': 'match', 'publish_authorized': False}
    monkeypatch.setattr(target, 'check_profile', fake)
    assert target.main(['--profile', 'fixture-account']) == 2
    assert not calls
    assert target.main(['--profile', 'fixture-account', '--check-readonly']) == 0
    assert calls == [(tmp_path / '.secret', 'fixture-account')]
    with pytest.raises(SystemExit):
        target.main(['--profile', 'fixture-account', '--check-readonly', '--token', 'fake-token'])
    assert 'fake-token' not in capsys.readouterr().err


@pytest.mark.parametrize('alias', ['../escape', 'con', 'nul', 'com1', 'a:b', 'a/b', 'UPPER', ''])
def test_invalid_alias_never_reads_file(tmp_path, monkeypatch, alias):
    target = module()
    monkeypatch.setattr(target, '_unlinked', lambda *a, **kw: pytest.fail('filesystem'))
    with pytest.raises(ValueError): target.check_profile(tmp_path, alias)
