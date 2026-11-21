"""Synthetic V1 publication previews without a SQLite connection."""
import copy
import json
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch


def test_six_channel_file_preview_matches_existing_fixture_without_sqlite(monkeypatch):
    from scripts.social import multichannel_fixture

    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    original = copy.deepcopy(data)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'],
                                       entries=data['entries'])
        expected = [json.loads(ledger.get(item)['snapshot_json'])['payload'] for item in ids]
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite connection'))
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    preview = multichannel_fixture.preview_v1_file_batch(
        source=data['source'], publication=data['publication'], entries=data['entries'])
    assert [item['snapshot'] for item in preview['items']] == expected
    assert data == original


def test_v1_file_preview_rejects_duplicate_destination():
    from scripts.social.multichannel_fixture import preview_v1_file_batch

    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    duplicate = copy.deepcopy(data['entries'][0])
    duplicate['args']['key']['account_id'] = 'fixture-other-account'
    with pytest.raises(ValueError):
        preview_v1_file_batch(source=data['source'], publication=data['publication'],
                              entries=[data['entries'][0], duplicate])


def test_v1_file_preview_rejects_duplicate_anchor_in_unselected_posts():
    from scripts.social.multichannel_fixture import preview_v1_file_batch

    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    post = copy.deepcopy(data['publication']['posts'][0])
    post['post_id'] = 'fixture-extra-post'
    data['publication']['posts'].append(post)
    linkedin = next(item for item in data['entries'] if item['platform'] == 'linkedin')
    with pytest.raises(ValueError):
        preview_v1_file_batch(source=data['source'], publication=data['publication'], entries=[linkedin])


def test_v1_file_preview_cli_returns_six_candidates():
    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    payload = {key: data[key] for key in ('source', 'publication', 'entries')}
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'preview-v1-file-batch'],
                            input=json.dumps(payload, ensure_ascii=False), text=True, encoding='utf-8',
                            capture_output=True, check=False)
    assert result.returncode == 0
    assert len(json.loads(result.stdout)['items']) == 6


@pytest.mark.parametrize('filename', [
    'v1_facebook_to_discord_simulation.json', 'v1_facebook_to_telegram_simulation.json',
    'v1_facebook_to_x_simulation.json', 'v1_facebook_to_x_image_simulation.json',
    'v1_facebook_to_x_video_simulation.json', 'v1_to_telegram_image_simulation.json',
    'v1_to_telegram_video_simulation.json', 'v1_facebook_x_image_batch.json',
    'v1_facebook_x_video_batch.json',
])
def test_v1_file_preview_matches_existing_media_and_text_fixtures(filename, monkeypatch):
    from scripts.social.multichannel_fixture import preview_v1_file_batch

    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' / filename)
                      .read_text(encoding='utf-8'))
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'],
                                       entries=data['entries'])
        expected = [json.loads(ledger.get(item)['snapshot_json'])['payload'] for item in ids]
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite connection'))
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    result = preview_v1_file_batch(source=data['source'], publication=data['publication'], entries=data['entries'])
    assert [item['snapshot'] for item in result['items']] == expected
