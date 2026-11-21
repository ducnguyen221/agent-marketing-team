"""Facebook Page identity probe uses fake profiles and transport only."""
import importlib
import json
import os

import pytest


def module():
    try:
        return importlib.import_module('scripts.social.channels.facebook.readonly_auth')
    except ModuleNotFoundError:
        pytest.fail('Facebook Page read-only check is missing')


def test_matching_id_does_not_prove_page_token_or_publish_rights():
    result = module().interpret_identity(200, {'id': '123'}, expected_page_id='123')
    assert result == {'identity': 'match', 'page_token_verified': False, 'profile_binding_verified': False,
                      'app_binding_verified': False, 'publish_authorized': False}


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (200, {'id': '456'}, 'mismatch'), (200, {'id': 123}, 'unknown'),
    (200, {'id': '123', 'error': {'code': 190}}, 'unknown'),
    (200, {'id': '123', 'status': 403}, 'unknown'), (403, {'id': '123'}, 'unknown'),
])
def test_error_or_ambiguous_response_never_succeeds(status, body, expected):
    assert module().interpret_identity(status, body, expected_page_id='123')['identity'] == expected


def test_fixed_fake_transport_returns_no_token_or_page_id(monkeypatch):
    target = module()
    calls = []
    class Response:
        status = 200
        def read(self, size): return b'{"id":"123"}'
    class Connection:
        def __init__(self, host, timeout): calls.append((host, timeout))
        def request(self, method, path, headers): calls.append((method, path, headers))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    result = target.check_identity('fake-token', '123', api_version='v27.0')
    assert calls[0] == ('graph.facebook.com', 10)
    assert calls[1][:2] == ('GET', '/v27.0/me?fields=id')
    assert calls[1][2]['Authorization'] == 'Bearer fake-token'
    assert result['identity'] == 'match'
    assert 'fake-token' not in str(result) and '123' not in str(result)


def test_valid_profile_and_hardlink_blocked_before_transport(tmp_path, monkeypatch):
    target = module()
    folder = tmp_path / 'fixture-valid'
    folder.mkdir()
    path = folder / 'facebook-page-userinfo.json'
    path.write_text(json.dumps({'schema': 'facebook-page-userinfo/1', 'provider': 'facebook',
        'token_kind': 'page_access_token', 'app_id': '456', 'expected_page_id': '123',
        'api_version': 'v27.0', 'access_token': 'fake-token'}), encoding='utf-8')
    calls = []
    monkeypatch.setattr(target, 'check_identity', lambda *a, **kw: calls.append('called') or {
        'identity': 'match', 'page_token_verified': False, 'profile_binding_verified': False,
        'app_binding_verified': False, 'publish_authorized': False})
    assert target.check_profile(tmp_path, 'fixture-valid')['identity'] == 'match'
    second = tmp_path / 'fixture-other'
    second.mkdir()
    os.link(path, second / 'facebook-page-userinfo.json')
    calls.clear()
    with pytest.raises(ValueError): target.check_profile(tmp_path, 'fixture-other')
    assert calls == []


@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
def test_non_200_does_not_read_or_redirect(monkeypatch, status):
    target = module()
    class Response:
        def read(self, size): pytest.fail('unexpected read')
    response = Response()
    response.status = status
    class Connection:
        def __init__(self, *a, **kw): pass
        def request(self, *a, **kw): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    assert target.check_identity('fake-token', '123', api_version='v27.0')['identity'] == 'unknown'


@pytest.mark.parametrize('raw', [b'{"id":"123","id":"456"}', b'{"id":NaN}', b'x' * 65537, b'\xff'],
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
    assert target.check_identity('fake-token', '123', api_version='v27.0')['identity'] == 'unknown'


def test_bad_token_version_or_page_id_never_opens_network(monkeypatch):
    target = module()
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', lambda *a, **kw: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_identity('bad\r\nheader', '123', api_version='v27.0')
    with pytest.raises(ValueError): target.check_identity('fake-token', 'bad', api_version='v27.0')
    with pytest.raises(ValueError): target.check_identity('fake-token', '123', api_version='v27.0/../me')


def test_cli_requires_flag_and_rejects_token_argument(tmp_path, monkeypatch, capsys):
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
def test_bad_alias_never_reads_file(tmp_path, monkeypatch, alias):
    target = module()
    monkeypatch.setattr(target, '_unlinked', lambda *a, **kw: pytest.fail('filesystem'))
    with pytest.raises(ValueError): target.check_profile(tmp_path, alias)
