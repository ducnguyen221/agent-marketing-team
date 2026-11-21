"""Agent-facing simulation of JSON fixture delivery, never real network."""
import json
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def payload():
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    ig = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    li = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    key = dict(li['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    tg = {'platform': 'telegram', 'args': {'key': key, 'target': {'chat_id': '-100123', 'purpose': 'publish'},
          'chat_id': '-100123', 'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Bài riêng cho Telegram'}}
    return {'source': data['source'], 'publication': data['publication'], 'entries': [ig, li, tg],
            'now': '2026-11-20T04:00:00Z', 'grant_fixture': True,
            'fakes': [{'platform': 'instagram', 'container_id': '101', 'status': 'FINISHED', 'media_id': None},
                      {'platform': 'linkedin', 'post_urn': 'urn:li:share:303', 'outcome': 'accepted'},
                      {'platform': 'telegram', 'response': {'message_id': 404,
                        'chat': {'id': -100123, 'type': 'channel'}, 'text': 'Bài riêng cho Telegram'}}]}


def test_json_simulation_is_offline_and_reports_three_destinations(monkeypatch):
    from scripts.social.json_session_simulation import simulate_json_dispatch

    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite'))
    result = simulate_json_dispatch(**payload())
    assert result['fixture_only'] is True
    assert [item['state'] for item in result['items']] == ['unknown', 'accepted', 'accepted']
    assert result['items'][1]['receipt']['post_urn'] == 'urn:li:share:303'
    assert result['items'][2]['receipt']['message_id'] == '404'
    assert 'source' not in json.dumps(result, ensure_ascii=False)


def test_json_simulation_cli_accepts_synthetic_input():
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'simulate-json-dispatch'],
                            input=json.dumps(payload(), ensure_ascii=False), text=True, encoding='utf-8',
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert [item['state'] for item in json.loads(result.stdout)['items']] == ['unknown', 'accepted', 'accepted']


def test_json_simulation_cli_rejects_missing_fake_platform_without_traceback():
    data = {'source': 'x', 'publication': {}, 'entries': [{}], 'fakes': [{}], 'now': '2026-11-20T04:00:00Z'}
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'simulate-json-dispatch'],
                            input=json.dumps(data), text=True, encoding='utf-8', capture_output=True, timeout=20)
    assert result.returncode == 2
    assert result.stdout == '' and result.stderr == 'invalid fixture request\n'
