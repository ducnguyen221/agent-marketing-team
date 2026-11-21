"""TikTok read-only check with synthetic data and fake connections."""
from pathlib import Path
import json
import os
import stat
from types import SimpleNamespace

import pytest


def test_only_open_id_is_compared_without_exposing_profile_or_permission():
    module = Path(__file__).resolve().parents[1] / 'scripts/social/channels/tiktok/readonly_auth.py'
    assert module.exists(), 'TikTok read-only check is missing'
    from scripts.social.channels.tiktok.readonly_auth import interpret_userinfo
    result = interpret_userinfo(200, {'data': {'user': {'open_id': 'fake-id', 'display_name': 'private'}},
                                      'error': {'code': 'ok'}}, expected_open_id='fake-id')
    assert result == {'identity': 'match', 'profile_binding_verified': False,
                      'app_binding_verified': False, 'publish_authorized': False}


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (200, {'data': {'user': {'open_id': 'other'}}, 'error': {'code': 'ok'}}, 'mismatch'),
    (200, {'data': {'user': {'open_id': 'fake-id'}}, 'error': {'code': 'bad'}}, 'unknown'),
    (403, {'data': {'user': {'open_id': 'fake-id'}}, 'error': {'code': 'ok'}}, 'unknown'),
    (200, {'data': {'user': {'open_id': ''}}, 'error': {'code': 'ok'}}, 'unknown'),
    (200, {'data': {}, 'error': {'code': 'ok'}}, 'unknown'),
])
def test_identity_needs_valid_response_and_matching_id(status, body, expected):
    from scripts.social.channels.tiktok.readonly_auth import interpret_userinfo
    result = interpret_userinfo(status, body, expected_open_id='fake-id')
    assert result['identity'] == expected and result['publish_authorized'] is False


def test_fixed_https_request_and_sensitive_data_not_returned(monkeypatch):
    from scripts.social.channels.tiktok import readonly_auth
    calls = []
    class Response:
        status = 200
        def read(self, size):
            return b'{"data":{"user":{"open_id":"fake-id","display_name":"sensitive"}},"error":{"code":"ok"}}'
    class Connection:
        def __init__(self, host, timeout):
            calls.append((host, timeout))
        def request(self, method, path, headers):
            calls.append((method, path, headers))
        def getresponse(self):
            return Response()
        def close(self):
            pass
    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', Connection)
    result = readonly_auth.check_userinfo('fake-token', 'fake-id')
    assert calls[0] == ('open.tiktokapis.com', 10)
    assert calls[1][:2] == ('GET', '/v2/user/info/?fields=open_id')
    assert result['identity'] == 'match'
    assert 'fake-id' not in str(result) and 'fake-token' not in str(result) and 'sensitive' not in str(result)


@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
def test_non_200_never_reads_body_or_follows_redirect(monkeypatch, status):
    from scripts.social.channels.tiktok import readonly_auth
    class Response:
        def read(self, size):
            pytest.fail('unexpected read')
    response = Response()
    response.status = status
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', Connection)
    assert readonly_auth.check_userinfo('fake-token', 'fake-id')['identity'] == 'unknown'


def test_transport_error_and_close_error_are_sanitized(monkeypatch):
    from scripts.social.channels.tiktok import readonly_auth
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): raise OSError('fake-token secret error')
        def close(self): raise OSError('fake-token close error')
    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', Connection)
    assert readonly_auth.check_userinfo('fake-token', 'fake-id')['identity'] == 'unknown'


def test_tiktok_profile_uses_own_schema_only(tmp_path, monkeypatch):
    from scripts.social.channels.tiktok import readonly_auth
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    profile = {'schema': 'tiktok-userinfo/1', 'provider': 'tiktok', 'token_kind': 'oauth_access_token',
               'client_key': 'fake-key', 'expected_open_id': 'fake-id', 'access_token': 'fake-token'}
    file = folder / 'tiktok-userinfo.json'
    file.write_text(json.dumps(profile), encoding='utf-8')
    monkeypatch.setattr(readonly_auth, 'check_userinfo', lambda token, expected: {
        'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False, 'publish_authorized': False})
    assert readonly_auth.check_profile(tmp_path, 'fixture-account')['identity'] == 'match'
    profile['provider'] = 'linkedin'
    file.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError):
        readonly_auth.check_profile(tmp_path, 'fixture-account')


def test_cli_requires_explicit_flag_and_fixed_root(tmp_path, monkeypatch, capsys):
    from scripts.social.channels.tiktok import readonly_auth
    monkeypatch.setattr(readonly_auth.Path, 'home', lambda: tmp_path)
    calls = []
    def fake(root, alias):
        calls.append((root, alias))
        return {'config_valid': True, 'identity': 'match', 'publish_authorized': False}
    monkeypatch.setattr(readonly_auth, 'check_profile', fake)
    assert readonly_auth.main(['--profile', 'fixture-account']) == 2
    assert not calls
    assert readonly_auth.main(['--profile', 'fixture-account', '--check-readonly']) == 0
    assert calls == [(tmp_path / '.secret', 'fixture-account')]
    with pytest.raises(SystemExit):
        readonly_auth.main(['--profile', 'fixture-account', '--check-readonly', '--token', 'fake-token'])
    assert 'fake-token' not in capsys.readouterr().err


@pytest.mark.parametrize('alias', ['../escape', 'con', 'nul', 'com1', 'a:b', 'a/b', 'UPPER', ''])
def test_unsafe_profile_alias_rejected_before_filesystem(tmp_path, monkeypatch, alias):
    from scripts.social.channels.tiktok import readonly_auth
    monkeypatch.setattr(readonly_auth, '_unlinked', lambda *a, **kw: pytest.fail('filesystem'))
    with pytest.raises(ValueError):
        readonly_auth.check_profile(tmp_path, alias)


@pytest.mark.parametrize('data', [b'{"data":{},"data":{}}', b'{"data":NaN}', b'x' * 65537, b'\xff'],
                         ids=['duplicate', 'nan', 'oversize', 'invalid-utf8'])
def test_untrusted_response_never_infers_identity(monkeypatch, data):
    from scripts.social.channels.tiktok import readonly_auth
    class Response:
        status = 200
        def read(self, size): return data
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', Connection)
    assert readonly_auth.check_userinfo('fake-token', 'fake-id')['identity'] == 'unknown'


def test_bad_token_or_expected_id_never_opens_network(monkeypatch):
    from scripts.social.channels.tiktok import readonly_auth
    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', lambda *a, **k: pytest.fail('network'))
    with pytest.raises(ValueError):
        readonly_auth.check_userinfo('bad\r\nheader', 'fake-id')
    with pytest.raises(ValueError):
        readonly_auth.check_userinfo('fake-token', ' ')


def test_duplicate_profile_keys_refused_without_transport(tmp_path, monkeypatch):
    from scripts.social.channels.tiktok import readonly_auth
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    (folder / 'tiktok-userinfo.json').write_text('{"provider":"tiktok","provider":"other"}', encoding='utf-8')
    monkeypatch.setattr(readonly_auth, 'check_userinfo', lambda *a: pytest.fail('network'))
    with pytest.raises(ValueError):
        readonly_auth.check_profile(tmp_path, 'fixture-account')


def test_copied_profile_never_claims_account_binding(tmp_path, monkeypatch):
    from scripts.social.channels.tiktok import readonly_auth
    folder = tmp_path / 'fixture-other-account'
    folder.mkdir()
    obj = {'schema': 'tiktok-userinfo/1', 'provider': 'tiktok', 'token_kind': 'oauth_access_token',
           'client_key': 'fake-key', 'expected_open_id': 'fake-other', 'access_token': 'fake-token'}
    (folder / 'tiktok-userinfo.json').write_text(json.dumps(obj), encoding='utf-8')
    monkeypatch.setattr(readonly_auth, 'check_userinfo', lambda *a: {
        'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False, 'publish_authorized': False})
    result = readonly_auth.check_profile(tmp_path, 'fixture-other-account')
    assert result['profile_binding_verified'] is False and result['app_binding_verified'] is False


def test_hardlinked_profile_is_rejected(tmp_path, monkeypatch):
    from scripts.social.channels.tiktok import readonly_auth
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    original = tmp_path / 'original.json'
    original.write_text('{}', encoding='utf-8')
    os.link(original, folder / 'tiktok-userinfo.json')
    monkeypatch.setattr(readonly_auth, 'check_userinfo', lambda *a: pytest.fail('network'))
    with pytest.raises(ValueError):
        readonly_auth.check_profile(tmp_path, 'fixture-account')


def test_reparse_profile_rejected_before_open(tmp_path, monkeypatch):
    from scripts.social.channels.tiktok import readonly_auth
    folder = tmp_path / 'fixture-account'
    folder.mkdir()
    file = folder / 'tiktok-userinfo.json'
    file.write_text('{}', encoding='utf-8')
    real_lstat = Path.lstat
    def fake_lstat(path):
        if path == file:
            return SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400, st_nlink=1)
        return real_lstat(path)
    monkeypatch.setattr(Path, 'lstat', fake_lstat)
    monkeypatch.setattr(readonly_auth.os, 'open', lambda *a, **kw: pytest.fail('open'))
    with pytest.raises(ValueError):
        readonly_auth.check_profile(tmp_path, 'fixture-account')
