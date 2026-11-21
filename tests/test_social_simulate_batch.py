"""End-to-end multi-channel simulation confined to disposable memory."""
import json
import socket
import subprocess
import sys

import pytest

from test_social_multichannel_sqlite import entries, source


def events():
    return [{'action': 'grant', 'entries': [{'index': 0, 'version': 1}, {'index': 1, 'version': 1}]},
            {'action': 'revoke', 'index': 0, 'version': 1},
            {'action': 'scan', 'now': '2026-11-20T04:00:00Z'},
            {'action': 'claim', 'index': 1, 'version': 1, 'now': '2026-11-20T04:00:00Z'}]


def test_simulation_runs_synthetic_lifecycle_without_network(monkeypatch):
    from scripts.social.multichannel_fixture import simulate_fixture_batch
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network'))
    result = simulate_fixture_batch(source=source(), entries=entries(), events=events())
    assert result['fixture_only'] is True
    assert result['events'][2]['due'] == [1]
    assert result['items'][0]['state'] == 'prepared' and result['items'][0]['version'] == 2
    assert result['items'][1]['state'] == 'submitting'
    assert result['items'][1]['candidate']['request']['params']['caption'] == 'Video Instagram'


def test_empty_events_never_auto_grants():
    from scripts.social.multichannel_fixture import simulate_fixture_batch
    result = simulate_fixture_batch(source=source(), entries=entries(), events=[])
    assert all(item['grant_version'] is None and item['state'] == 'prepared' for item in result['items'])


@pytest.mark.parametrize('event', [{'action': 'grant', 'entries': [{'index': True, 'version': 1}]},
                                  {'action': 'claim', 'index': 1, 'version': 1, 'now': '2026-11-20T04:00:00Z'},
                                  {'action': 'scan', 'now': 'invalid'}, {'action': 'unknown'},
                                  {'action': 'revoke', 'index': 5, 'version': 1}])
def test_invalid_or_unauthorized_fixture_event_fails(event):
    from scripts.social.multichannel_fixture import simulate_fixture_batch
    with pytest.raises(ValueError):
        simulate_fixture_batch(source=source(), entries=entries(), events=[event])


def test_cli_simulation_is_memory_only_and_returns_states():
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'simulate-batch'],
                            input=json.dumps({'source': source(), 'entries': entries(), 'events': events()}),
                            text=True, encoding='utf-8', capture_output=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)['items'][1]['state'] == 'submitting'


def test_simulation_tiktok_inbox_exposes_fake_video_identity():
    from scripts.social.multichannel_fixture import simulate_fixture_batch
    item = {'platform': 'tiktok', 'args': {'key': {'station_id': 'fixture-station', 'channel_id': 'fixture-channel',
        'campaign_id': 'fixture-campaign', 'content_id': 'fixture-content', 'post_id': 'fixture-tt', 'platform': 'tiktok',
        'account_id': 'fixture-tiktok-account-1', 'destination_id': 'fixture-tiktok-profile-1', 'occurrence_key': 'fixture-slot'},
        'target': {'account_id': 'fixture-tiktok-account-1', 'destination_id': 'fixture-tiktok-profile-1',
                   'creator_id': 'fixture-tiktok-creator-1'}, 'anchor': 'post:tiktok_post', 'mode': 'INBOX',
        'scheduled_at': '2026-11-20T03:00:00Z', 'video_size': 4194304, 'chunk_size': 4194304,
        'media_id': 'fixture-video-a', 'media_sha256_fixture': 'a' * 64}}
    result = simulate_fixture_batch(source=source() + '## post:tiktok_post\nVideo giả\n', entries=[item], events=[])
    media = result['items'][0]['fixture_media']
    assert media == {'source_anchor': 'post:tiktok_post', 'media_id': 'fixture-video-a',
                     'media_sha256_fixture': 'a' * 64, 'suggested_caption': 'Video giả'}


def test_simulation_scans_equal_times_in_input_order():
    from scripts.social.multichannel_fixture import simulate_fixture_batch
    items = entries()
    items[1]['args']['scheduled_at'] = items[0]['args']['scheduled_at']
    actions = [events()[0], {'action': 'scan', 'now': '2026-11-20T03:00:00Z'}]
    for _ in range(4):
        assert simulate_fixture_batch(source=source(), entries=items, events=actions)['events'][1]['due'] == [0, 1]


def test_simulation_freezes_event_membership_before_copy():
    from scripts.social.multichannel_fixture import simulate_fixture_batch
    class MutatingList(list):
        def __deepcopy__(self, memo):
            return []
    result = simulate_fixture_batch(source=source(), entries=entries(), events=MutatingList([events()[0]]))
    assert len(result['events']) == 1


def test_packaged_six_channel_example_executes_and_preserves_fake_states():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/six_channel_simulation.json'
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'simulate-batch'],
                            input=path.read_text(encoding='utf-8'), text=True, encoding='utf-8',
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert {item['platform'] for item in data['items']} == {'facebook', 'instagram', 'linkedin', 'threads', 'tiktok', 'youtube'}
    assert data['events'][2]['due'] == [1, 2, 3, 4, 5]
    assert data['items'][0]['grant_version'] is None
    assert data['items'][1]['state'] == 'submitting'
    assert all(item['state'] == 'prepared' for item in data['items'][2:])
