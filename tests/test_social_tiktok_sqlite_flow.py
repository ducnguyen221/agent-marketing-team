"""Synthetic TikTok marketing-to-SQLite exercises; no provider calls."""
import json
import sqlite3
import socket
from pathlib import Path

import pytest


def key():
    return {'station_id': 'fixture-station', 'channel_id': 'fixture-channel', 'campaign_id': 'fixture-campaign',
            'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'tiktok',
            'account_id': 'fixture-tiktok-account-123', 'destination_id': 'fixture-tiktok-profile-123',
            'occurrence_key': 'fixture-slot'}


def target():
    return {'account_id': 'fixture-tiktok-account-123', 'destination_id': 'fixture-tiktok-profile-123',
            'creator_id': 'fixture-tiktok-creator-123'}


def base():
    return {'key': key(), 'target': target(), 'source': '## post:tiktok_post\nBài giả\n', 'anchor': 'post:tiktok_post',
            'mode': 'INBOX', 'scheduled_at': '2026-11-20T03:00:00Z', 'video_size': 4194304,
            'chunk_size': 4194304, 'media_id': 'fixture-video', 'media_sha256_fixture': 'a' * 64}


def direct_options():
    from scripts.social.channels.tiktok.direct import fixture_consent_digest
    creator = {'fixture_only': True, 'fixture_creator_id': 'fixture-tiktok-creator-123',
               'fixture_revision': 'fixture-revision', 'privacy_level_options': ['SELF_ONLY'],
               'comment_disabled': True, 'duet_disabled': True, 'stitch_disabled': True,
               'max_video_post_duration_sec': 60}
    post = {'title': 'Bài giả', 'privacy_level': 'SELF_ONLY', 'disable_comment': True, 'disable_duet': True,
            'disable_stitch': True, 'brand_content_toggle': False, 'brand_organic_toggle': False}
    digest = fixture_consent_digest(video_size=4194304, chunk_size=4194304, duration_sec=30, creator=creator,
                                    post_info=post, media_sha256_fixture='a' * 64)
    return {'mode': 'DIRECT', 'creator': creator, 'creator_revision': 'fixture-revision', 'duration_sec': 30,
            'post_info': post, 'consent_fixture': True, 'consent_digest_fixture': digest}


def test_prepare_uses_one_identity_snapshot_when_caller_mutates(monkeypatch):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social import tiktok_fixture_flow as flow

    args = base()
    original_builder = flow.build_tiktok_fixture_snapshot

    def change_caller_key_after_build(**kwargs):
        result = original_builder(**kwargs)
        args['key']['content_id'] = 'fixture-other'
        return result

    monkeypatch.setattr(flow, 'build_tiktok_fixture_snapshot', change_caller_key_after_build)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = flow.prepare_tiktok_fixture(ledger, **args)
        assert ledger.get(intent)['content_id'] == 'fixture-content'


def test_inbox_intent_preserves_caption_as_suggestion_without_posting(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'scripts/social/tiktok_fixture_flow.py'
    assert path.exists(), 'TikTok SQLite fixture flow is missing'
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_tiktok_fixture(ledger, key=key(), target=target(), source='## post:tiktok_post\nBài giả\n',
             anchor='post:tiktok_post', mode='INBOX', scheduled_at='2026-11-20T03:00:00Z',
             video_size=4194304, chunk_size=4194304, media_id='fixture-video', media_sha256_fixture='a' * 64)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['suggested_caption'] == 'Bài giả'
        assert 'post_info' not in payload['candidate']['request']['body']
        assert ledger.get(item)['grant_version'] is None
    finally:
        con.close()


def test_direct_candidate_binds_source_media_and_due_schedule(tmp_path, monkeypatch):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = {**base(), **direct_options()}
        item = prepare_tiktok_fixture(ledger, **args)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['candidate']['request']['body']['post_info']['title'] == 'Bài giả'
        assert payload['media_sha256_fixture'] == 'a' * 64
        ledger.approve(item, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == [item]
        assert ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('change', ['caption', 'media', 'target', 'schedule', 'inbox_options', 'metadata'])
def test_mismatched_or_ambiguous_inputs_do_not_create_intent(tmp_path, change):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = {**base(), **direct_options()}
        if change == 'caption': args['source'] = '## post:tiktok_post\nKhác\n'
        elif change == 'media': args['media_sha256_fixture'] = 'b' * 64
        elif change == 'target': args['target'] = {**target(), 'creator_id': 'fixture-tiktok-creator-other'}
        elif change == 'schedule': args['scheduled_at'] = 'tomorrow'
        elif change == 'inbox_options': args['mode'] = 'INBOX'
        else: args['source'] = '---\nschema: content/1\ncontent_id: fixture-other\ncampaign_id: fixture-campaign\n---\n## post:tiktok_post\nBài giả\n'
        with pytest.raises(ValueError):
            prepare_tiktok_fixture(ledger, **args)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_inbox_does_not_claim_published_or_autoapprove(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_tiktok_fixture(ledger, **base())
        assert prepare_tiktok_fixture(ledger, **base()) == item
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert ledger.get(item)['state'] == 'prepared'
    finally:
        con.close()


def test_distinct_anchors_with_identical_text_cannot_share_same_intent(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        source = '## post:tiktok_post\nSame\n## post:tiktok_post#2\nSame\n'
        args = {**base(), 'source': source}
        item = prepare_tiktok_fixture(ledger, **args)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['source_anchor'] == 'post:tiktok_post'
        with pytest.raises(ValueError, match='conflict'):
            prepare_tiktok_fixture(ledger, **{**args, 'anchor': 'post:tiktok_post#2'})
    finally:
        con.close()


@pytest.mark.parametrize('text', ['\u200d', '\u0301', ' \u200d '])
def test_inbox_rejects_invisible_only_caption(tmp_path, text):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_tiktok_fixture(ledger, **{**base(), 'source': '## post:tiktok_post\n' + text + '\n'})
    finally:
        con.close()


def test_direct_normalizes_windows_caption_and_retains_raw_source_hash(tmp_path):
    import hashlib
    from scripts.social.channels.tiktok.direct import fixture_consent_digest
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        options = direct_options()
        options['post_info']['title'] = 'Một\n👩\u200d💻'
        options['consent_digest_fixture'] = fixture_consent_digest(video_size=4194304, chunk_size=4194304,
            duration_sec=30, creator=options['creator'], post_info=options['post_info'], media_sha256_fixture='a' * 64)
        source = '## post:tiktok_post\r\nMột\r\n👩\u200d💻\r\n'
        item = prepare_tiktok_fixture(ledger, **{**base(), **options, 'source': source})
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['suggested_caption'] == 'Một\n👩\u200d💻'
        assert payload['source_sha256'] == hashlib.sha256(source.encode('utf-8')).hexdigest()
    finally:
        con.close()


@pytest.mark.parametrize('change', ['title', 'media', 'target', 'remove_schedule', 'remove_schema'])
def test_revision_rejects_inconsistent_tiktok_snapshot(tmp_path, change):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_tiktok_fixture(ledger, **{**base(), **direct_options()})
        ledger.approve(item, expected_version=1)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        if change == 'title': payload['candidate']['request']['body']['post_info']['title'] = 'changed'
        elif change == 'media': payload['media_sha256_fixture'] = 'b' * 64
        elif change == 'target': payload['target']['creator_id'] = 'fixture-tiktok-creator-other'
        elif change == 'remove_schedule': del payload['scheduled_at']
        else: payload.pop('fixture_schema', None)
        with pytest.raises(ValueError):
            ledger.revise(item, payload)
        assert ledger.get(item)['version'] == 1
        assert ledger.get(item)['grant_version'] == 1
    finally:
        con.close()


def test_due_claim_rechecks_candidate_even_when_snapshot_hash_was_recomputed(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.fixture_ledger import _snapshot_digest
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_tiktok_fixture(ledger, **{**base(), **direct_options()})
        ledger.approve(item, expected_version=1)
        snapshot = json.loads(ledger.get(item)['snapshot_json'])
        snapshot['payload']['candidate']['request']['body']['post_info']['title'] = 'changed'
        con.execute('UPDATE destination_fixture_intents SET snapshot_json=?,snapshot_digest=? WHERE intent_id=?',
                    (json.dumps(snapshot), _snapshot_digest(snapshot), item))
        con.commit()
        assert item in ledger.scan_due(now='2026-11-20T03:00:00Z')['invalid']
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert ledger.get(item)['state'] == 'prepared'
    finally:
        con.close()


@pytest.mark.parametrize('caption', ['# internal heading', '<div>unsafe</div>', '> quoted'])
def test_inbox_revision_rejects_ambiguous_markdown_caption(tmp_path, caption):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_tiktok_fixture(ledger, **base())
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        payload['suggested_caption'] = caption
        with pytest.raises(ValueError):
            ledger.revise(item, payload)
    finally:
        con.close()


def test_direct_revision_rejects_heading_even_with_matching_candidate_and_digest(tmp_path):
    from scripts.social.channels.tiktok.direct import fixture_consent_digest, preview_direct_post
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_tiktok_fixture(ledger, **{**base(), **direct_options()})
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        inputs = payload['validation_inputs']
        inputs['post_info']['title'] = payload['suggested_caption'] = '# internal heading'
        inputs['consent_digest_fixture'] = fixture_consent_digest(video_size=inputs['video_size'],
            chunk_size=inputs['chunk_size'], duration_sec=inputs['duration_sec'], creator=inputs['creator'],
            post_info=inputs['post_info'], media_sha256_fixture=payload['media_sha256_fixture'])
        payload['candidate'] = preview_direct_post(video_size=inputs['video_size'], chunk_size=inputs['chunk_size'],
            duration_sec=inputs['duration_sec'], creator=inputs['creator'], expected_creator=target()['creator_id'],
            expected_revision=inputs['creator_revision'], consent_fixture=True, post_info=inputs['post_info'],
            media_sha256_fixture=payload['media_sha256_fixture'], consent_digest_fixture=inputs['consent_digest_fixture'])
        with pytest.raises(ValueError):
            ledger.revise(item, payload)
    finally:
        con.close()
