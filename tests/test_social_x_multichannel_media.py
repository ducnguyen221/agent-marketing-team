"""A V1 Facebook asset shared across synthetic Facebook and X destinations."""
import copy
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch, simulate_v1_fixture_batch


def sample(kind):
    data = json.loads((Path(__file__).resolve().parents[1] /
        f'fixtures/social_v2/v1_facebook_to_x_{kind}_simulation.json').read_text(encoding='utf-8'))
    x = data['entries'][0]['args']
    fbkey = dict(x['key'], platform='facebook', account_id='fixture-facebook-account-321',
                 destination_id='fixture-facebook-page-321')
    fb = {'platform': 'facebook', 'args': {'key': fbkey, 'scheduled_at': x['scheduled_at'],
        'manifest': copy.deepcopy(x['manifest']), 'media_type': kind.upper(), 'page_id': '321', 'api_version': 'v27.0'}}
    data['entries'].insert(0, fb)
    data['events'] = [{'action': 'grant', 'entries': [{'index': 0, 'version': 1}, {'index': 1, 'version': 1}]},
        {'action': 'scan', 'now': '2026-11-20T03:00:00Z'},
        {'action': 'claim', 'index': 0, 'version': 1, 'now': '2026-11-20T03:00:00Z'},
        {'action': 'claim', 'index': 1, 'version': 1, 'now': '2026-11-20T03:00:00Z'}]
    return data


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_one_v1_asset_prepares_facebook_and_x_independently(kind):
    data = sample(kind)
    result = simulate_v1_fixture_batch(**data)
    assert [item['platform'] for item in result['items']] == ['facebook', 'x']
    assert [item['state'] for item in result['items']] == ['submitting', 'submitting']
    assert result['items'][1]['source_binding']['post_id'] == 'fixture-fb-post'
    assert result['items'][1]['fixture_media']['media_kind'] == kind


def test_x_asset_error_leaves_both_destinations_unprepared():
    data = sample('image')
    data['entries'][1]['args']['manifest'][0]['post_id'] = 'fixture-wrong-post'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_expired_x_does_not_stop_other_destination():
    data = sample('video')
    data['entries'][1]['args']['observation']['expires_at'] = '2026-11-20T03:00:00Z'
    data['events'].pop()
    result = simulate_v1_fixture_batch(**data)
    assert result['events'][1]['due'] == [0]
    assert result['events'][1]['invalid'] == [1]
    assert [item['state'] for item in result['items']] == ['submitting', 'prepared']


@pytest.mark.parametrize('reverse', [False, True])
def test_same_v1_asset_cannot_have_conflicting_source_ids_across_facebook_and_x(reverse):
    data = sample('video')
    data['entries'][0]['args']['manifest'][0]['id'] = 'fixture-other-source-asset'
    if reverse:
        data['entries'].reverse()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_grant_x_only_does_not_grant_facebook():
    data = sample('image')
    data['events'] = [{'action': 'grant', 'entries': [{'index': 1, 'version': 1}]},
        {'action': 'scan', 'now': '2026-11-20T03:00:00Z'},
        {'action': 'claim', 'index': 1, 'version': 1, 'now': '2026-11-20T03:00:00Z'}]
    result = simulate_v1_fixture_batch(**data)
    assert result['events'][1]['due'] == [1]
    assert [item['state'] for item in result['items']] == ['prepared', 'submitting']
    assert result['items'][0]['grant_version'] is None


def test_same_filename_in_different_posts_keeps_distinct_asset_ids():
    data = sample('video')
    data['source'] += '\n## post:facebook_post#2\nBài thứ hai giả\n'
    new_post = copy.deepcopy(data['publication']['posts'][-1])
    new_post.update(post_id='fixture-other-post', post_content='post:facebook_post#2')
    data['publication']['posts'].append(new_post)
    args = data['entries'][1]['args']
    args['key']['post_id'] = 'fixture-other-post'
    args['manifest'][0].update(post_id='fixture-other-post', id='fixture-other-asset')
    args['observation']['asset_id'] = 'fixture-other-asset'
    result = simulate_v1_fixture_batch(**data)
    assert [item['state'] for item in result['items']] == ['submitting', 'submitting']
    assert result['items'][1]['source_binding']['post_id'] == 'fixture-other-post'
