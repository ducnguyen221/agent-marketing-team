"""Instagram Facebook Login identity check using fake profiles and transport."""
import importlib
import json
import os

import pytest


def module():
    try:
        return importlib.import_module('scripts.social.channels.instagram.readonly_auth')
    except ModuleNotFoundError:
        pytest.fail('Instagram Facebook Login read-only check is missing')


def test_matching_page_and_instagram_do_not_authorize_publishing():
    result = module().interpret_link(200, {'id': '123', 'instagram_business_account': {'id': '456'}},
                                     expected_page_id='123', expected_instagram_id='456')
    assert result == {'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False,
                      'token_type_verified': False, 'publish_authorized': False}


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (200, {'id': '123', 'instagram_business_account': {'id': '789'}}, 'mismatch'),
    (200, {'id': '999', 'instagram_business_account': {'id': '456'}}, 'unknown'),
    (200, {'id': '123'}, 'unknown'), (200, {'id': '123', 'instagram_business_account': None}, 'unknown'),
    (200, {'id': '123', 'instagram_business_account': {'id': '456'}, 'error': {'code': 190}}, 'unknown'),
    (200, {'id': '123', 'instagram_business_account': {'id': '456', 'error': {'code': 1}}}, 'unknown'),
    (403, {'id': '123', 'instagram_business_account': {'id': '456'}}, 'unknown'),
])
def test_link_is_unknown_if_missing_unexpected_or_ambiguous(status, body, expected):
    assert module().interpret_link(status, body, expected_page_id='123', expected_instagram_id='456')['identity'] == expected


def test_fake_transport_uses_page_path_and_no_credential_in_output(monkeypatch):
    target = module()
    calls = []
    class Response:
        status = 200
        def read(self, size): return b'{"id":"123","instagram_business_account":{"id":"456"}}'
    class Connection:
        def __init__(self, host, timeout): calls.append((host, timeout))
        def request(self, method, path, headers): calls.append((method, path, headers))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    result = target.check_link('fake-token', '123', '456', api_version='v27.0')
    assert calls[0] == ('graph.facebook.com', 10)
    assert calls[1][:2] == ('GET', '/v27.0/123?fields=id%2Cinstagram_business_account%7Bid%7D')
    assert calls[1][2]['Authorization'] == 'Bearer fake-token'
    assert result['identity'] == 'match'
    assert not any(value in str(result) for value in ('fake-token', '123', '456'))


def test_provider_specific_profile_and_hardlink_rejection(tmp_path, monkeypatch):
    target = module()
    folder = tmp_path / 'fixture-valid'
    folder.mkdir()
    path = folder / 'instagram-facebook-userinfo.json'
    path.write_text(json.dumps({'schema': 'instagram-facebook-userinfo/1', 'provider': 'instagram',
        'login_product': 'facebook_login', 'token_kind': 'facebook_user_access_token', 'app_id': '789',
        'expected_page_id': '123', 'expected_instagram_id': '456', 'api_version': 'v27.0',
        'access_token': 'fake-token'}), encoding='utf-8')
    calls = []
    monkeypatch.setattr(target, 'check_link', lambda *a, **kw: calls.append('called') or {
        'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False,
        'token_type_verified': False, 'publish_authorized': False})
    assert target.check_profile(tmp_path, 'fixture-valid')['identity'] == 'match'
    other = tmp_path / 'fixture-other'
    other.mkdir()
    os.link(path, other / 'instagram-facebook-userinfo.json')
    calls.clear()
    with pytest.raises(ValueError): target.check_profile(tmp_path, 'fixture-other')
    assert calls == []


@pytest.mark.parametrize(('field', 'bad'), [('login_product', 'instagram_login'), ('token_kind', 'page_access_token')])
def test_wrong_login_or_token_type_refused_before_transport(tmp_path, monkeypatch, field, bad):
    target = module()
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    profile = {'schema': 'instagram-facebook-userinfo/1', 'provider': 'instagram',
        'login_product': 'facebook_login', 'token_kind': 'facebook_user_access_token', 'app_id': '789',
        'expected_page_id': '123', 'expected_instagram_id': '456', 'api_version': 'v27.0', 'access_token': 'fake-token'}
    profile[field] = bad
    (folder / 'instagram-facebook-userinfo.json').write_text(json.dumps(profile), encoding='utf-8')
    monkeypatch.setattr(target, 'check_link', lambda *a, **kw: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_profile(tmp_path, 'fixture-account')


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
    assert target.check_link('fake-token', '123', '456', api_version='v27.0')['identity'] == 'unknown'


@pytest.mark.parametrize('raw', [b'{"id":"123","id":"456"}',
                                 b'{"id":"123","instagram_business_account":{"id":"456","id":"789"}}',
                                 b'{"id":NaN}', b'x' * 65537, b'\xff'],
                         ids=['duplicate', 'nested-duplicate', 'nan', 'oversize', 'invalid-utf8'])
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
    assert target.check_link('fake-token', '123', '456', api_version='v27.0')['identity'] == 'unknown'


def test_invalid_token_ids_or_version_never_open_network(monkeypatch):
    target = module()
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', lambda *a, **kw: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_link('bad\r\nheader', '123', '456', api_version='v27.0')
    with pytest.raises(ValueError): target.check_link('fake-token', '123/evil', '456', api_version='v27.0')
    with pytest.raises(ValueError): target.check_link('fake-token', '123', 'bad', api_version='v27.0')
    with pytest.raises(ValueError): target.check_link('fake-token', '123', '456', api_version='v27.0/../me')


def test_cli_requires_flag_and_refuses_token_argument(tmp_path, monkeypatch, capsys):
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
    with pytest.raises(SystemExit): target.main(['--profile', 'fixture-account', '--check-readonly', '--token', 'fake-token'])
    assert 'fake-token' not in capsys.readouterr().err


@pytest.mark.parametrize('alias', ['../escape', 'con', 'nul', 'com1', 'a:b', 'a/b', 'UPPER', ''])
def test_bad_alias_never_reads_file(tmp_path, monkeypatch, alias):
    target = module()
    monkeypatch.setattr(target, '_unlinked', lambda *a, **kw: pytest.fail('filesystem'))
    with pytest.raises(ValueError): target.check_profile(tmp_path, alias)
