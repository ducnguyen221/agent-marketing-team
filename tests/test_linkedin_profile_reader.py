"""Temporary synthetic profiles only; no real secret store or network."""
import json
import os
from pathlib import Path

import pytest

from scripts.social.channels.linkedin import readonly_auth


def profile():
    return {'schema': 'linkedin-userinfo/1', 'provider': 'linkedin', 'token_kind': 'oauth_access_token',
            'client_id': 'fixture-client', 'person_urn': 'urn:li:person:fixture-user',
            'access_token': 'fixture-token'}


def test_profile_runs_only_the_linkedin_readonly_probe(tmp_path, monkeypatch):
    assert hasattr(readonly_auth, 'check_profile')
    directory = tmp_path / 'fixture-account'
    directory.mkdir()
    (directory / 'linkedin-userinfo.json').write_text(json.dumps(profile()), encoding='utf-8')
    seen = []
    def probe(token, author):
        seen.append((token, author))
        return {'identity': 'match', 'app_binding_verified': False, 'publish_authorized': False}
    monkeypatch.setattr(readonly_auth, 'check_userinfo', probe)
    result = readonly_auth.check_profile(tmp_path, 'fixture-account')
    assert result == {'config_valid': True, 'identity': 'match', 'profile_binding_verified': False,
                      'app_binding_verified': False, 'publish_authorized': False}
    assert seen == [('fixture-token', 'urn:li:person:fixture-user')]


@pytest.mark.parametrize('alias', ['../other', 'x/y', 'X', 'a:b', '', 'a.', 'con.txt', 'con', 'nul', 'com1', 'lpt1'])
def test_invalid_alias_is_rejected_before_access(tmp_path, monkeypatch, alias):
    monkeypatch.setattr(readonly_auth, '_unlinked', lambda *args, **kwargs: pytest.fail('filesystem'))
    with pytest.raises(ValueError):
        readonly_auth.check_profile(tmp_path, alias)


def test_parent_traversal_root_is_rejected_before_access(tmp_path, monkeypatch):
    monkeypatch.setattr(readonly_auth, '_unlinked', lambda *args, **kwargs: pytest.fail('filesystem'))
    with pytest.raises(ValueError):
        readonly_auth.check_profile(tmp_path / '..' / 'elsewhere', 'fixture-account')


@pytest.mark.skipif(os.name != 'nt', reason='Windows path syntax')
@pytest.mark.parametrize('root', [r'\\server\share', r'\\?\C:\other', r'C:\folder:stream'])
def test_windows_unsafe_roots_never_touch_filesystem(monkeypatch, root):
    monkeypatch.setattr(readonly_auth, '_unlinked', lambda *args, **kwargs: pytest.fail('filesystem'))
    with pytest.raises(ValueError):
        readonly_auth.check_profile(Path(root), 'fixture-account')


@pytest.mark.parametrize(('field', 'bad'), [
    ('provider', 'facebook'), ('token_kind', 'id_token'), ('client_id', ''),
    ('person_urn', 'urn:li:organization:1'), ('access_token', 'bad\r\nheader'),
])
def test_wrong_profile_never_reaches_transport(tmp_path, monkeypatch, field, bad):
    directory = tmp_path / 'fixture-account'
    directory.mkdir()
    obj = profile()
    obj[field] = bad
    (directory / 'linkedin-userinfo.json').write_text(json.dumps(obj), encoding='utf-8')
    monkeypatch.setattr(readonly_auth, 'check_userinfo', lambda *a: pytest.fail('network'))
    with pytest.raises(ValueError, match='invalid or unavailable LinkedIn profile'):
        readonly_auth.check_profile(tmp_path, 'fixture-account')


def test_duplicate_keys_and_large_file_are_rejected(tmp_path, monkeypatch):
    directory = tmp_path / 'fixture-account'
    directory.mkdir()
    path = directory / 'linkedin-userinfo.json'
    monkeypatch.setattr(readonly_auth, 'check_userinfo', lambda *a: pytest.fail('network'))
    for data in ('{"provider":"linkedin","provider":"other"}', 'x' * 16385):
        path.write_text(data, encoding='utf-8')
        with pytest.raises(ValueError):
            readonly_auth.check_profile(tmp_path, 'fixture-account')


def test_linked_file_is_rejected_without_open(tmp_path, monkeypatch):
    directory = tmp_path / 'fixture-account'
    directory.mkdir()
    path = directory / 'linkedin-userinfo.json'
    path.write_text(json.dumps(profile()), encoding='utf-8')
    original = readonly_auth._unlinked
    def reject_link(value, *, directory):
        if not directory:
            raise ValueError('invalid profile location')
        return original(value, directory=directory)
    monkeypatch.setattr(readonly_auth, '_unlinked', reject_link)
    monkeypatch.setattr(readonly_auth.os, 'open', lambda *a, **kw: pytest.fail('open'))
    with pytest.raises(ValueError):
        readonly_auth.check_profile(tmp_path, 'fixture-account')


def test_errors_are_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(readonly_auth, '_unlinked', lambda *a, **k: (_ for _ in ()).throw(OSError('fixture-token')))
    with pytest.raises(ValueError) as failure:
        readonly_auth.check_profile(tmp_path, 'fixture-account')
    assert 'fixture-token' not in str(failure.value)


def test_cli_requires_explicit_action_before_opening_files(monkeypatch, capsys):
    assert hasattr(readonly_auth, 'main')
    monkeypatch.setattr(readonly_auth, 'check_profile', lambda *a: pytest.fail('access'))
    assert readonly_auth.main(['--profile', 'fixture-account']) == 2
    assert 'fixture-token' not in capsys.readouterr().err


def test_cli_uses_fixed_root_and_never_accepts_token_argument(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(readonly_auth.Path, 'home', lambda: tmp_path)
    seen = []
    def check(root, alias):
        seen.append((root, alias))
        return {'config_valid': True, 'identity': 'match', 'profile_binding_verified': False, 'app_binding_verified': False,
                'publish_authorized': False}
    monkeypatch.setattr(readonly_auth, 'check_profile', check)
    assert readonly_auth.main(['--check-readonly', '--profile', 'fixture-account']) == 0
    assert seen == [(tmp_path / '.secret', 'fixture-account')]
    assert 'match' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        readonly_auth.main(['--check-readonly', '--profile', 'fixture-account', '--token', 'fixture-token'])
    assert 'fixture-token' not in capsys.readouterr().err
