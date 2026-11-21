"""Offline preview CLI accepts a batch but never submits a post."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts' / 'pipeline' / 'postiz_preview.py'


def run_preview(value):
    return subprocess.run([sys.executable, str(CLI)], input=json.dumps(value, ensure_ascii=False),
                          text=True, encoding='utf-8', capture_output=True, cwd=ROOT, timeout=10)


def test_preview_cli_builds_two_platform_candidates_without_network():
    batch = [
        {'ref': 'one', 'integration_id': 'int-1', 'provider': 'threads', 'content': 'Xin chào',
         'uploaded_media': [], 'mode': 'schedule', 'date_utc': '2026-11-20T03:00:00Z',
         'settings': {'__type': 'threads'}},
        {'ref': 'two', 'integration_id': 'int-2', 'provider': 'discord', 'content': 'Tin mới',
         'uploaded_media': [], 'mode': 'schedule', 'date_utc': '2026-11-20T04:00:00Z',
         'settings': {'__type': 'discord', 'channel': '123'}},
    ]
    completed = run_preview(batch)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['mode'] == 'preview_only'
    assert [item['ref'] for item in result['items']] == ['one', 'two']
    assert result['items'][1]['candidate']['posts'][0]['integration']['id'] == 'int-2'


def test_preview_cli_rejects_invalid_batch_without_printing_input():
    completed = run_preview([{'ref': 'private-data-sentinel'}])
    assert completed.returncode != 0
    assert 'private-data-sentinel' not in completed.stdout + completed.stderr


def test_preview_cli_rejects_duplicate_json_keys():
    completed = subprocess.run([sys.executable, str(CLI)], input='[{"ref":"one","ref":"two"}]',
                               text=True, encoding='utf-8', capture_output=True, cwd=ROOT, timeout=10)
    assert completed.returncode == 2
    assert not completed.stdout


def test_preview_cli_rejects_duplicate_nested_json_keys():
    raw = '[{"settings":{"__type":"threads","__type":"discord"}}]'
    completed = subprocess.run([sys.executable, str(CLI)], input=raw, text=True,
                               encoding='utf-8', capture_output=True, cwd=ROOT, timeout=10)
    assert completed.returncode == 2
    assert not completed.stdout
    assert 'discord' not in completed.stderr


def test_preview_cli_rejects_oversized_input():
    completed = subprocess.run([sys.executable, str(CLI)], input=' ' * 2_200_001,
                               text=True, encoding='utf-8', capture_output=True, cwd=ROOT, timeout=10)
    assert completed.returncode == 2
    assert not completed.stdout


def test_preview_cli_help_does_not_need_stdin():
    completed = subprocess.run([sys.executable, str(CLI), '--help'], input='', text=True,
                               capture_output=True, cwd=ROOT, timeout=10)
    assert completed.returncode == 0
    assert 'preview' in completed.stdout.lower()


def test_preview_cli_rejects_unknown_arguments_even_with_valid_input():
    batch = [{'ref': 'one', 'integration_id': 'int', 'provider': 'threads', 'content': 'Hello',
              'uploaded_media': [], 'mode': 'draft', 'date_utc': '2026-11-20T03:00:00Z',
              'settings': {'__type': 'threads'}}]
    completed = subprocess.run([sys.executable, str(CLI), '--file', 'ignored'], input=json.dumps(batch), text=True,
                               capture_output=True, cwd=ROOT, timeout=10)
    assert completed.returncode == 2
    assert not completed.stdout


def test_preview_cli_rejects_non_utf8_without_echoing():
    completed = subprocess.run([sys.executable, str(CLI)], input=b'\xff', capture_output=True, cwd=ROOT, timeout=10)
    assert completed.returncode == 2
    assert not completed.stdout
