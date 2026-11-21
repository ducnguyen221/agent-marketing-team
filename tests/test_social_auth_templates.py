"""Generate placeholder templates only in a test-owned directory."""
import importlib
import json
import os
from pathlib import Path

import pytest


def tool():
    try:
        return importlib.import_module('scripts.social.init_auth_templates')
    except ModuleNotFoundError as exc:
        if exc.name == 'scripts.social.init_auth_templates':
            pytest.fail('auth template initializer is missing')
        raise


def test_generates_all_nine_platforms_with_only_empty_values(tmp_path):
    root = tmp_path / 'fake-root'
    root.mkdir()
    result = tool().create_templates(root)
    assert set(result['created']) == {'facebook', 'instagram', 'youtube', 'linkedin', 'tiktok',
                                      'threads', 'x', 'discord', 'telegram'}
    for channel in result['created']:
        data = json.loads((root / '_social-auth-templates' / f'{channel}.example.json').read_text(encoding='utf-8'))
        assert data['template_only'] is True
        assert data['platform'] == channel
        assert data['fields'] and all(value is None for value in data['fields'].values())


def test_existing_template_is_never_read_or_overwritten(tmp_path, monkeypatch):
    root = tmp_path / 'fake-root'
    target = root / '_social-auth-templates'
    target.mkdir(parents=True)
    existing = target / 'linkedin.example.json'
    existing.write_text('EXISTING-SENTINEL', encoding='utf-8')
    original_read = Path.read_text
    def guarded_read(path, *args, **kwargs):
        if path == existing:
            raise AssertionError('existing destination must not be read')
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded_read)
    result = tool().create_templates(root)
    assert 'linkedin' in result['existing_unverified']
    assert original_read(existing, encoding='utf-8') == 'EXISTING-SENTINEL'


def test_missing_root_fails_without_creating_it(tmp_path):
    root = tmp_path / 'missing-root'
    with pytest.raises(ValueError):
        tool().create_templates(root)
    assert not root.exists()


def test_symlink_template_directory_is_refused(tmp_path):
    root = tmp_path / 'fake-root'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (root / '_social-auth-templates').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlink unavailable')
    with pytest.raises(ValueError):
        tool().create_templates(root)
    assert list(outside.iterdir()) == []


def test_default_cli_does_not_touch_secret_root(monkeypatch, capsys):
    module = tool()
    calls = []
    monkeypatch.setattr(module, 'create_templates', lambda *args: calls.append('called'))
    assert module.main([]) == 2
    assert calls == []
    assert 'token' not in capsys.readouterr().out.lower()


def test_second_run_skips_every_template_without_overwriting(tmp_path):
    root = tmp_path / 'fake-root'
    root.mkdir()
    first = tool().create_templates(root)
    second = tool().create_templates(root)
    assert not first['failed'] and not second['failed']
    assert second['created'] == []
    assert set(second['existing_unverified']) == set(first['created'])


def test_write_failure_is_reported_without_leaking_exception(tmp_path, monkeypatch):
    root = tmp_path / 'fake-root'
    root.mkdir()
    original_open = os.open
    def fail_one(path, *args, **kwargs):
        if Path(path).name == 'linkedin.example.json':
            raise PermissionError('PRIVATE-SENTINEL')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(os, 'open', fail_one)
    result = tool().create_templates(root)
    assert result['failed'] == ['linkedin']
    assert 'PRIVATE-SENTINEL' not in str(result)


def test_duplicate_json_keys_cannot_smuggle_values_into_generated_template(tmp_path, monkeypatch):
    module = tool()
    template_dir = tmp_path / 'templates'
    template_dir.mkdir()
    (template_dir / 'facebook.example.json').write_text(
        '{"schema":"social-auth-template/1","template_only":true,"platform":"facebook",'
        '"fields":{"page_token":"FAKE-SENTINEL","page_token":null}}', encoding='utf-8')
    monkeypatch.setattr(module, '_SOURCE', template_dir)
    with pytest.raises(ValueError):
        module._template('facebook')


def test_source_template_size_is_checked_before_open(tmp_path, monkeypatch):
    module = tool()
    template_dir = tmp_path / 'templates'
    template_dir.mkdir()
    source = template_dir / 'facebook.example.json'
    source.write_bytes(b'x' * 16385)
    original = Path.read_bytes
    def guarded_read(path):
        if path == source:
            raise AssertionError('oversized source must not be read')
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    monkeypatch.setattr(module, '_SOURCE', template_dir)
    with pytest.raises(ValueError):
        module._template('facebook')


def test_windows_reparse_directory_is_rejected_without_open(monkeypatch, tmp_path):
    import stat
    module = tool()
    class FakeStat:
        st_mode = stat.S_IFDIR
        st_file_attributes = 0x400
    monkeypatch.setattr(Path, 'lstat', lambda *args, **kwargs: FakeStat())
    with pytest.raises(ValueError):
        module._safe_directory(tmp_path)
