"""YouTube channel identity probe uses fake profiles and transport only."""
import importlib
import json
import os

import pytest


def module():
    try:
        return importlib.import_module('scripts.social.channels.youtube.readonly_auth')
    except ModuleNotFoundError:
        pytest.fail('YouTube channel read-only check is missing')


CHANNEL = 'UCabcdefghijklmnopqrstuv'
OTHER = 'UCabcdefghijklmnopqrstuX'


def test_matching_channel_does_not_assert_publish_rights():
    result = module().interpret_channels(200, {'items': [{'id': CHANNEL}]}, expected_channel_id=CHANNEL)
    assert result == {'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False,
                      'channel_permissions_verified': False, 'publish_authorized': False}


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (200, {'items': [{'id': OTHER}]}, 'mismatch'),
    (200, {'items': []}, 'unknown'),
    (200, {'items': [{'id': OTHER}, {'id': CHANNEL}]}, 'match'),
    (200, {'items': [{'id': CHANNEL}], 'nextPageToken': 'more'}, 'match'),
    (200, {'items': [{'id': OTHER}], 'nextPageToken': 'more'}, 'unknown'),
    (200, {'items': [{'id': CHANNEL}, {'id': CHANNEL}]}, 'unknown'),
    (200, {'items': [{'id': CHANNEL}, {'id': 'bad'}]}, 'unknown'),
    (200, {'items': [{'id': CHANNEL}], 'error': {'code': 403}}, 'unknown'),
    (200, {'items': [{'id': CHANNEL}], 'code': 403, 'message': 'Forbidden'}, 'unknown'),
    (403, {'items': [{'id': CHANNEL}]}, 'unknown'),
])
def test_ambiguous_channel_responses_are_not_success(status, body, expected):
    assert module().interpret_channels(status, body, expected_channel_id=CHANNEL)['identity'] == expected


def test_fixed_fake_transport_returns_no_token_or_channel(monkeypatch):
    target = module()
    calls = []
    class Response:
        status = 200
        def read(self, size): return json.dumps({'items': [{'id': CHANNEL}]}).encode()
    class Connection:
        def __init__(self, host, timeout): calls.append((host, timeout))
        def request(self, method, path, headers): calls.append((method, path, headers))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', Connection)
    result = target.check_channel('fake-token', CHANNEL)
    assert calls[0] == ('www.googleapis.com', 10)
    assert calls[1][:2] == ('GET', '/youtube/v3/channels?part=id&mine=true&maxResults=50&fields=items%28id%29%2CnextPageToken')
    assert result['identity'] == 'match'
    assert 'fake-token' not in str(result) and CHANNEL not in str(result)


def test_valid_profile_is_read_from_test_root_and_hardlink_rejected(tmp_path, monkeypatch):
    target = module()
    folder = tmp_path / 'fixture-valid'
    folder.mkdir()
    path = folder / 'youtube-channel-userinfo.json'
    path.write_text(json.dumps({'schema': 'youtube-channel-userinfo/1', 'provider': 'youtube',
        'token_kind': 'oauth_access_token', 'client_id': 'fake-client', 'expected_channel_id': CHANNEL,
        'access_token': 'fake-token'}), encoding='utf-8')
    calls = []
    monkeypatch.setattr(target, 'check_channel', lambda *a: calls.append('called') or {
        'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False,
        'channel_permissions_verified': False, 'publish_authorized': False})
    assert target.check_profile(tmp_path, 'fixture-valid')['identity'] == 'match'
    second = tmp_path / 'fixture-other'
    second.mkdir()
    os.link(path, second / 'youtube-channel-userinfo.json')
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
    assert target.check_channel('fake-token', CHANNEL)['identity'] == 'unknown'


@pytest.mark.parametrize('raw', [b'{"items":[],"items":[]}', b'{"items":NaN}',
                                 b'x' * 65537, b'\xff'], ids=['duplicate', 'nan', 'oversize', 'invalid-utf8'])
def test_malformed_response_is_unknown(monkeypatch, raw):
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
    assert target.check_channel('fake-token', CHANNEL)['identity'] == 'unknown'


def test_invalid_token_and_channel_never_open_connection(monkeypatch):
    target = module()
    monkeypatch.setattr(target.http.client, 'HTTPSConnection', lambda *a, **kw: pytest.fail('network'))
    with pytest.raises(ValueError): target.check_channel('bad\r\nheader', CHANNEL)
    with pytest.raises(ValueError): target.check_channel('fake-token', 'bad')


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
    with pytest.raises(SystemExit):
        target.main(['--profile', 'fixture-account', '--check-readonly', '--token', 'fake-token'])
    assert 'fake-token' not in capsys.readouterr().err


@pytest.mark.parametrize('alias', ['../escape', 'con', 'nul', 'com1', 'a:b', 'a/b', 'UPPER', ''])
def test_invalid_alias_rejected_before_filesystem(tmp_path, monkeypatch, alias):
    target = module()
    monkeypatch.setattr(target, '_unlinked', lambda *a, **kw: pytest.fail('filesystem'))
    with pytest.raises(ValueError): target.check_profile(tmp_path, alias)
