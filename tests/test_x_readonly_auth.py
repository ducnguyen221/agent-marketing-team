"""X identity checking uses fake profiles and fake HTTPS connections only."""
import importlib
import json
import os
import stat
from types import SimpleNamespace
from pathlib import Path

import pytest


def module():
    try:
        return importlib.import_module('scripts.social.channels.x.readonly_auth')
    except ModuleNotFoundError:
        pytest.fail('X read-only identity check is missing')


def test_identity_match_never_authorizes_or_exposes_identity():
    result = module().interpret_userinfo(200, {'data': {'id': '123', 'name': 'private'}}, expected_user_id='123')
    assert result == {'identity': 'match', 'profile_binding_verified': False,
                      'app_binding_verified': False, 'publish_authorized': False}


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (200, {'data': {'id': '456'}}, 'mismatch'),
    (200, {'data': {'id': '123'}, 'errors': [{'detail': 'bad'}]}, 'unknown'),
    (200, {'data': {'id': '123'}, 'status': 403, 'title': 'Forbidden'}, 'unknown'),
    (200, {'data': {'id': '123'}, 'error': 'invalid_token'}, 'unknown'),
    (403, {'data': {'id': '123'}}, 'unknown'),
    (200, {'data': {'id': ''}}, 'unknown'),
    (200, {'data': {'id': 123}}, 'unknown'),
])
def test_identity_requires_complete_unambiguous_response(status, body, expected):
    assert module().interpret_userinfo(status, body, expected_user_id='123')['identity'] == expected


def test_fake_transport_uses_fixed_readonly_endpoint_and_sanitizes_output(monkeypatch):
    target = module()
    calls = []
    class Response:
        status = 200
        def read(self, size):
            return b'{"data":{"id":"123","name":"private"}}'
    class Connection:
        def __init__(self, host, timeout): calls.append((host, timeout))
        def request(self, method, path, headers): calls.append((method, path, headers))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    result = target.check_userinfo('fake-token', '123')
    assert calls[0] == ('api.x.com', 10)
    assert calls[1][:2] == ('GET', '/2/users/me')
    assert result['identity'] == 'match'
    assert 'fake-token' not in str(result) and '123' not in str(result) and 'private' not in str(result)


def test_profile_uses_provider_specific_schema_and_is_not_binding(tmp_path, monkeypatch):
    target = module()
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    profile = {'schema': 'x-userinfo/1', 'provider': 'x', 'token_kind': 'oauth2_user_access_token',
               'client_id': 'fake-client', 'expected_user_id': '123', 'access_token': 'fake-token'}
    path = folder / 'x-userinfo.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    monkeypatch.setattr(target, 'check_userinfo', lambda *args: {'identity': 'match', 'profile_binding_verified': False,
        'app_binding_verified': False, 'publish_authorized': False})
    assert target.check_profile(tmp_path, 'fixture-account')['profile_binding_verified'] is False
    profile['provider'] = 'other'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError):
        target.check_profile(tmp_path, 'fixture-account')


@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
def test_non_200_response_is_not_read_or_redirected(monkeypatch, status):
    target = module()
    class Response:
        def read(self, size): pytest.fail('non-200 body was read')
    response = Response()
    response.status = status
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    assert target.check_userinfo('fake-token', '123')['identity'] == 'unknown'


@pytest.mark.parametrize('raw', [b'{"data":{"id":"123","id":"456"}}', b'{"data":NaN}',
                                 b'x' * 65537, b'\xff'], ids=['duplicate', 'nan', 'oversize', 'invalid-utf8'])
def test_malformed_or_oversize_response_is_unknown(monkeypatch, raw):
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
    assert target.check_userinfo('fake-token', '123')['identity'] == 'unknown'


def test_invalid_inputs_never_open_connection(monkeypatch):
    target = module()
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', lambda *a, **k: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_userinfo('bad\r\nheader', '123')
    with pytest.raises(ValueError): target.check_userinfo('fake-token', 'abc')


def test_cli_requires_explicit_flag_and_never_accepts_token_argument(tmp_path, monkeypatch, capsys):
    target = module()
    monkeypatch.setattr(target.Path, 'home', lambda: tmp_path)
    calls = []
    def fake(root, alias):
        calls.append((root, alias))
        return {'config_valid': True, 'identity': 'match', 'publish_authorized': False}
    monkeypatch.setattr(target, 'check_profile', fake)
    assert target.main(['--profile', 'fixture-account']) == 2
    assert calls == []
    assert target.main(['--profile', 'fixture-account', '--check-readonly']) == 0
    assert calls == [(tmp_path / '.secret', 'fixture-account')]
    with pytest.raises(SystemExit):
        target.main(['--profile', 'fixture-account', '--check-readonly', '--token', 'fake-token'])
    assert 'fake-token' not in capsys.readouterr().err


def test_hardlink_profile_is_rejected_without_transport(tmp_path, monkeypatch):
    target = module()
    valid = tmp_path / 'fixture-valid'
    valid.mkdir()
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    original = valid / 'x-userinfo.json'
    original.write_text(json.dumps({'schema': 'x-userinfo/1', 'provider': 'x',
        'token_kind': 'oauth2_user_access_token', 'client_id': 'fake-client',
        'expected_user_id': '123', 'access_token': 'fake-token'}), encoding='utf-8')
    calls = []
    monkeypatch.setattr(target, 'check_userinfo', lambda *a: calls.append('called') or {
        'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False, 'publish_authorized': False})
    assert target.check_profile(tmp_path, 'fixture-valid')['identity'] == 'match'
    assert calls == ['called']
    os.link(original, folder / 'x-userinfo.json')
    calls.clear()
    with pytest.raises(ValueError):
        target.check_profile(tmp_path, 'fixture-account')
    assert calls == []


@pytest.mark.parametrize('alias', ['../escape', 'con', 'nul', 'com1', 'a:b', 'a/b', 'UPPER', ''])
def test_unsafe_alias_rejected_before_filesystem(tmp_path, monkeypatch, alias):
    target = module()
    monkeypatch.setattr(target, '_unlinked', lambda *a, **kw: pytest.fail('filesystem'))
    with pytest.raises(ValueError):
        target.check_profile(tmp_path, alias)


def test_reparse_profile_is_rejected_before_open(tmp_path, monkeypatch):
    target = module()
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    path = folder / 'x-userinfo.json'
    path.write_text('{}', encoding='utf-8')
    original = Path.lstat
    def fake_lstat(item):
        if item == path:
            return SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400, st_nlink=1)
        return original(item)
    monkeypatch.setattr(Path, 'lstat', fake_lstat)
    monkeypatch.setattr(target.os, 'open', lambda *a, **kw: pytest.fail('open'))
    with pytest.raises(ValueError):
        target.check_profile(tmp_path, 'fixture-account')


def test_transport_error_is_sanitized(monkeypatch):
    target = module()
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): raise OSError('fake-token error')
        def close(self): raise OSError('fake-token error')
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    result = target.check_userinfo('fake-token', '123')
    assert result['identity'] == 'unknown'
    assert 'fake-token' not in str(result)
