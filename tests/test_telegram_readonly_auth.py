"""Telegram getMe probe exercises only fake profiles and fake HTTPS."""
import importlib
import json
import os

import pytest


def module():
    try:
        return importlib.import_module('scripts.social.channels.telegram.readonly_auth')
    except ModuleNotFoundError:
        pytest.fail('Telegram read-only bot check is missing')


def test_matching_bot_does_not_prove_purpose_or_channel_permissions():
    result = module().interpret_bot(200, {'ok': True, 'result': {'id': 123, 'is_bot': True}}, expected_bot_id='123')
    assert result == {'identity': 'match', 'profile_binding_verified': False, 'purpose_verified': False,
                      'channel_permissions_verified': False, 'publish_authorized': False}


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (200, {'ok': True, 'result': {'id': 456, 'is_bot': True}}, 'mismatch'),
    (200, {'ok': True, 'result': {'id': 123, 'is_bot': 1}}, 'unknown'),
    (200, {'ok': True, 'result': {'id': '123', 'is_bot': True}}, 'unknown'),
    (200, {'ok': True, 'result': {'id': 123, 'is_bot': True}, 'error_code': 403}, 'unknown'),
    (200, {'ok': False, 'result': {'id': 123, 'is_bot': True}}, 'unknown'),
    (403, {'ok': True, 'result': {'id': 123, 'is_bot': True}}, 'unknown'),
])
def test_response_requires_success_and_bot_identity(status, body, expected):
    assert module().interpret_bot(status, body, expected_bot_id='123')['identity'] == expected


def test_fixed_fake_transport_does_not_return_path_or_bot_info(monkeypatch):
    target = module()
    calls = []
    class Response:
        status = 200
        def read(self, size): return b'{"ok":true,"result":{"id":123,"is_bot":true,"username":"private"}}'
    class Connection:
        def __init__(self, host, timeout): calls.append((host, timeout))
        def request(self, method, path, headers): calls.append((method, path, headers))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    result = target.check_bot('123:FAKE-token', '123')
    assert calls[0] == ('api.telegram.org', 10)
    assert calls[1][:2] == ('GET', '/bot123:FAKE-token/getMe')
    assert result['identity'] == 'match'
    assert not any(value in str(result) for value in ('FAKE-token', '123', 'private'))


def test_profile_publish_purpose_and_hardlinks_checked_before_transport(tmp_path, monkeypatch):
    target = module()
    folder = tmp_path / 'fixture-valid'
    folder.mkdir()
    path = folder / 'telegram-publish-bot-userinfo.json'
    profile = {'schema': 'telegram-publish-bot-userinfo/1', 'provider': 'telegram', 'purpose': 'publish',
               'expected_bot_id': '123', 'bot_token': '123:FAKE-token'}
    path.write_text(json.dumps(profile), encoding='utf-8')
    calls = []
    monkeypatch.setattr(target, 'check_bot', lambda *a: calls.append('called') or {
        'identity': 'match', 'profile_binding_verified': False, 'purpose_verified': False,
        'channel_permissions_verified': False, 'publish_authorized': False})
    assert target.check_profile(tmp_path, 'fixture-valid')['identity'] == 'match'
    other = tmp_path / 'fixture-other'
    other.mkdir()
    os.link(path, other / 'telegram-publish-bot-userinfo.json')
    calls.clear()
    with pytest.raises(ValueError): target.check_profile(tmp_path, 'fixture-other')
    assert calls == []


@pytest.mark.parametrize(('field', 'value'), [('purpose', 'approval'), ('provider', 'discord')])
def test_wrong_purpose_or_provider_is_rejected_before_transport(tmp_path, monkeypatch, field, value):
    target = module()
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    profile = {'schema': 'telegram-publish-bot-userinfo/1', 'provider': 'telegram', 'purpose': 'publish',
               'expected_bot_id': '123', 'bot_token': '123:FAKE-token'}
    profile[field] = value
    (folder / 'telegram-publish-bot-userinfo.json').write_text(json.dumps(profile), encoding='utf-8')
    monkeypatch.setattr(target, 'check_bot', lambda *a: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_profile(tmp_path, 'fixture-account')


@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
def test_non_200_does_not_read_or_redirect(monkeypatch, status):
    target = module()
    class Response:
        def read(self, size): pytest.fail('unexpected read')
    response = Response()
    response.status = status
    calls = []
    class Connection:
        def __init__(self, *a, **kw): calls.append('connect')
        def request(self, *a, **kw): calls.append('request')
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    assert target.check_bot('123:FAKE-token', '123')['identity'] == 'unknown'
    assert calls == ['connect', 'request']


@pytest.mark.parametrize('raw', [b'{"ok":true,"ok":true}', b'{"ok":NaN}', b'x' * 65537, b'\xff'],
                         ids=['duplicate', 'nan', 'oversize', 'invalid-utf8'])
def test_bad_response_is_unknown(monkeypatch, raw):
    target = module()
    class Response:
        status = 200
        def read(self, size): return raw
    class Connection:
        def __init__(self, *a, **kw): pass
        def request(self, *a, **kw): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    assert target.check_bot('123:FAKE-token', '123')['identity'] == 'unknown'


def test_token_path_or_transport_error_does_not_reach_output(monkeypatch, capsys):
    target = module()
    class Connection:
        def __init__(self, *a, **kw): self.debuglevel = 1
        def request(self, *a, **kw):
            assert self.debuglevel == 0
            raise OSError('/bot123:FAKE-token/getMe')
        def close(self): raise OSError('FAKE-token')
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    result = target.check_bot('123:FAKE-token', '123')
    assert result['identity'] == 'unknown'
    out = capsys.readouterr()
    assert 'FAKE-token' not in str(result) + out.out + out.err


@pytest.mark.parametrize('token', ['123:bad/path', '123:bad?query', '123:bad\r\nheader', 'bad', '0:x'])
def test_malformed_token_never_opens_network(monkeypatch, token):
    target = module()
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', lambda *a, **kw: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_bot(token, '123')


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
        target.main(['--profile', 'fixture-account', '--check-readonly', '--token', '123:FAKE-token'])
    assert 'FAKE-token' not in capsys.readouterr().err


@pytest.mark.parametrize('alias', ['../escape', 'con', 'nul', 'com1', 'a:b', 'a/b', 'UPPER', ''])
def test_bad_alias_never_reads_file(tmp_path, monkeypatch, alias):
    target = module()
    monkeypatch.setattr(target, '_unlinked', lambda *a, **kw: pytest.fail('filesystem'))
    with pytest.raises(ValueError): target.check_profile(tmp_path, alias)
