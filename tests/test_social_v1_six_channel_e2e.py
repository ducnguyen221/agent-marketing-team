"""Exercise a packaged synthetic V1 publication across six social destinations."""
import copy
import json
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch, simulate_v1_fixture_batch


def sample():
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    return json.loads(path.read_text(encoding='utf-8'))


def test_one_v1_publication_runs_six_distinct_synthetic_destinations(monkeypatch):
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('unexpected network'))
    result = simulate_v1_fixture_batch(**sample())
    assert [item['platform'] for item in result['items']] == [
        'facebook', 'youtube', 'instagram', 'tiktok', 'linkedin', 'threads']
    assert [item['state'] for item in result['items']] == [
        'submitting', 'submitting', 'submitting', 'submitting', 'submitting', 'prepared']
    assert result['items'][5]['grant_version'] is None
    assert result['items'][2]['source_binding']['anchor'] == 'post:reel'
    assert result['items'][3]['source_binding']['anchor'] == 'post:youtube_short'
    tiktok = result['items'][3]['candidate']
    assert tiktok['request']['path'] == '/v2/post/publish/video/init/'
    assert tiktok['request']['body']['post_info']['privacy_level'] == 'SELF_ONLY'
    assert tiktok['consent_digest_fixture'] == sample()['entries'][3]['args']['direct']['consent_digest_fixture']
    assert result['items'][4]['source_binding']['anchor'] == 'post:facebook_post'
    assert result['items'][5]['source_notes']['first_comment_omitted'] is True
    assert result['items'][4]['candidate']['request']['body']['commentary'] != result['items'][5]['candidate']['request']['params']['text']
    assert result['events'][1]['due'] == [0, 1, 2, 3, 4]
    assert result['events'][1]['invalid'] == []


def test_cli_runs_packaged_six_channel_example():
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'simulate-v1-batch'],
                            input=path.read_text(encoding='utf-8'), text=True, encoding='utf-8',
                            capture_output=True, check=False)
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output['items']) == 6 and output['items'][5]['state'] == 'prepared'


def test_bad_last_destination_leaves_destination_ledger_empty():
    data = copy.deepcopy(sample())
    data['entries'][5]['args']['target']['threads_user_id'] = '999'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_v1_facebook_text_to_persistent_linkedin_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('unexpected network'))
    fixture = sample()
    path = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(path)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=fixture['source'], publication=fixture['publication'],
                                          entries=[fixture['entries'][4]])
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T04:00:00Z')
        ledger.finish_linkedin_fixture(item, attempt=attempt, status=201,
                                       headers=[('x-restli-id', 'urn:li:share:456')])
    finally:
        con.close()
    con = sqlite3.connect(path)
    try:
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.get(item)['state'] == 'accepted'
        assert ledger.get_linkedin_fixture_receipt(item)['post_urn'] == 'urn:li:share:456'
    finally:
        con.close()
