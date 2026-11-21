"""V1 Facebook attachments mapped to a synthetic LinkedIn candidate."""
import copy
import importlib
import json
import socket
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport, send_due_fixture
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch, simulate_v1_fixture_batch


def sample(kind):
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    args = copy.deepcopy(source['entries'][4]['args'])
    post = next(row for row in source['publication']['posts'] if row['post_id'] == args['key']['post_id'])
    filename = 'image.png' if kind == 'image' else 'video.mp4'
    post['asset_ref'] = filename
    args.update(source=source['source'], publication=source['publication'], media_kind=kind,
                media_urn=f'urn:li:{kind}:fixture-media',
                manifest=[{'content_id': args['key']['content_id'], 'post_id': args['key']['post_id'],
                           'relative_path': filename, 'kind': kind, 'id': 'fixture-source-asset',
                           'path': '/fixture/' + filename}],
                media_observation={'id': f'urn:li:{kind}:fixture-media', 'owner': args['author'],
                                   'status': 'AVAILABLE', 'asset_id': 'fixture-source-asset'})
    return args


@pytest.mark.parametrize('reverse', [False, True])
def test_file_preview_rejects_media_urn_bound_to_two_assets(reverse):
    from scripts.social.multichannel_fixture import preview_v1_file_batch

    args = sample('image')
    source, publication = args.pop('source'), args.pop('publication')
    other = copy.deepcopy(args)
    other['key']['occurrence_key'] = 'fixture-another-occurrence'
    other['manifest'][0]['id'] = 'fixture-other-asset'
    other['media_observation']['asset_id'] = 'fixture-other-asset'
    entries = [{'platform': 'linkedin', 'args': value} for value in (args, other)]
    if reverse:
        entries.reverse()
    with pytest.raises(ValueError):
        preview_v1_file_batch(source=source, publication=publication, entries=entries)


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_v1_attachment_to_linkedin_fake_transport_preserves_asset(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network forbidden'))
    try:
        module = importlib.import_module('scripts.social.linkedin_v1_media_fixture')
    except ModuleNotFoundError as exc:
        if exc.name == 'scripts.social.linkedin_v1_media_fixture':
            pytest.fail('V1 LinkedIn media mapping is missing')
        raise
    args = sample(kind)
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = module.prepare_linkedin_v1_media_fixture(ledger, **args)
        ledger.approve(item, expected_version=1)
        transport = FakeLinkedInTransport(post_urn='urn:li:share:123')
        send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['asset']['id'] == 'fixture-source-asset'
        assert transport.last_candidate['request']['body']['content']['media']['id'] == args['media_urn']
        assert transport.last_candidate == payload['candidate']
        assert ledger.get(item)['state'] == 'accepted'
    finally:
        con.close()


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_v1_media_enters_multichannel_batch(tmp_path, kind):
    args = sample(kind)
    source = args.pop('source')
    publication = args.pop('publication')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source, publication=publication,
                                          entries=[{'platform': 'linkedin', 'args': args}])
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['asset']['id'] == 'fixture-source-asset'
    finally:
        con.close()


@pytest.mark.parametrize('mutation', ['null_post', 'wrong_post', 'wrong_asset', 'wrong_owner',
                                       'processing', 'real_urn', 'wrong_kind', 'missing_ref'])
def test_invalid_media_mapping_does_not_create_intent(tmp_path, mutation):
    from scripts.social.linkedin_v1_media_fixture import prepare_linkedin_v1_media_fixture
    args = sample('image')
    post = next(row for row in args['publication']['posts'] if row['post_id'] == args['key']['post_id'])
    if mutation == 'null_post': args['publication']['posts'].insert(0, None)
    elif mutation == 'wrong_post': args['manifest'][0]['post_id'] = 'fixture-other'
    elif mutation == 'wrong_asset': args['media_observation']['asset_id'] = 'fixture-other'
    elif mutation == 'wrong_owner': args['media_observation']['owner'] = 'urn:li:person:fixture-other'
    elif mutation == 'processing': args['media_observation']['status'] = 'PROCESSING'
    elif mutation == 'real_urn': args['media_urn'] = 'urn:li:image:actual'
    elif mutation == 'wrong_kind': args['manifest'][0]['kind'] = 'video'
    else: post['asset_ref'] = ''
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_linkedin_v1_media_fixture(ledger, **args)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_simulation_reports_v1_source_and_fixture_media():
    args = sample('image')
    source = args.pop('source')
    publication = args.pop('publication')
    result = simulate_v1_fixture_batch(source=source, publication=publication,
                                       entries=[{'platform': 'linkedin', 'args': args}], events=[])
    item = result['items'][0]
    assert item.get('source_binding', {}).get('anchor') == 'post:facebook_post'
    assert item.get('fixture_media', {}).get('asset_id') == 'fixture-source-asset'


@pytest.mark.parametrize('reverse', [False, True])
def test_batch_refuses_same_media_urn_for_different_source_assets(tmp_path, reverse):
    args = sample('image')
    source = args.pop('source')
    publication = args.pop('publication')
    other = copy.deepcopy(args)
    other['key']['occurrence_key'] = 'fixture-second'
    other['manifest'][0]['id'] = 'fixture-other-asset'
    other['media_observation']['asset_id'] = 'fixture-other-asset'
    entries = [{'platform': 'linkedin', 'args': value} for value in (args, other)]
    if reverse:
        entries.reverse()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_media_revision_invalidates_previous_synthetic_grant(tmp_path):
    from scripts.social.linkedin_v1_media_fixture import _build, prepare_linkedin_v1_media_fixture
    args = sample('image')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_v1_media_fixture(ledger, **args)
        ledger.approve(item, expected_version=1)
        args['media_urn'] = 'urn:li:image:fixture-new'
        args['media_observation']['id'] = args['media_urn']
        ledger.revise(item, _build(**args))
        transport = FakeLinkedInTransport(post_urn='urn:li:share:123')
        with pytest.raises(ValueError):
            send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 0
        assert ledger.get(item)['grant_version'] is None
    finally:
        con.close()


@pytest.mark.parametrize('reverse', [False, True])
def test_batch_refuses_same_media_urn_for_different_owners(tmp_path, reverse):
    args = sample('image')
    source = args.pop('source')
    publication = args.pop('publication')
    other = copy.deepcopy(args)
    other['author'] = 'urn:li:person:fixture-other'
    other['key']['account_id'] = 'fixture-linkedin-account-other'
    other['key']['destination_id'] = 'fixture-linkedin-person-other'
    other['media_observation']['owner'] = other['author']
    entries = [{'platform': 'linkedin', 'args': value} for value in (args, other)]
    if reverse:
        entries.reverse()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_two_owners_can_use_distinct_media_for_same_source(tmp_path):
    args = sample('image')
    source = args.pop('source')
    publication = args.pop('publication')
    other = copy.deepcopy(args)
    other['author'] = 'urn:li:person:fixture-other'
    other['key']['account_id'] = 'fixture-linkedin-account-other'
    other['key']['destination_id'] = 'fixture-linkedin-person-other'
    other['media_urn'] = 'urn:li:image:fixture-other'
    other['media_observation'].update(id=other['media_urn'], owner=other['author'])
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        items = prepare_v1_fixture_batch(ledger, source=source, publication=publication,
            entries=[{'platform': 'linkedin', 'args': value} for value in (args, other)])
        assert len(items) == 2
    finally:
        con.close()


def test_media_urn_cannot_be_reassigned_after_reopening_fixture(tmp_path):
    from scripts.social.linkedin_v1_media_fixture import prepare_linkedin_v1_media_fixture
    args = sample('image')
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        prepare_linkedin_v1_media_fixture(ledger, **args)
    finally:
        con.close()
    args['key']['occurrence_key'] = 'fixture-second'
    args['manifest'][0]['id'] = 'fixture-other-asset'
    args['media_observation']['asset_id'] = 'fixture-other-asset'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        with pytest.raises(ValueError):
            prepare_linkedin_v1_media_fixture(ledger, **args)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 1
    finally:
        con.close()


def test_old_media_binding_survives_revision(tmp_path):
    from scripts.social.linkedin_v1_media_fixture import _build, prepare_linkedin_v1_media_fixture
    args = sample('image')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_v1_media_fixture(ledger, **args)
        original = copy.deepcopy(args)
        args['media_urn'] = 'urn:li:image:fixture-new'
        args['media_observation']['id'] = args['media_urn']
        ledger.revise(item, _build(**args))
        original['key']['occurrence_key'] = 'fixture-second'
        original['manifest'][0]['id'] = 'fixture-other'
        original['media_observation']['asset_id'] = 'fixture-other'
        with pytest.raises(ValueError):
            prepare_linkedin_v1_media_fixture(ledger, **original)
        assert con.execute('SELECT count(*) FROM linkedin_fixture_media_bindings').fetchone()[0] == 2
    finally:
        con.close()


@pytest.mark.parametrize('native_first', [False, True])
def test_native_and_v1_cannot_assign_same_media_to_different_owners(tmp_path, native_first):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    from scripts.social.linkedin_v1_media_fixture import prepare_linkedin_v1_media_fixture
    v1 = sample('image')
    native_key = copy.deepcopy(v1['key'])
    native_key.update(account_id='fixture-linkedin-account-other', destination_id='fixture-linkedin-person-other')
    native = {'key': native_key, 'author': 'urn:li:person:fixture-other',
              'source': '## post:linkedin_post\nNoi dung gia\n', 'anchor': 'post:linkedin_post',
              'api_version': v1['api_version'], 'scheduled_at': v1['scheduled_at'],
              'media_kind': 'image', 'media_urn': v1['media_urn'],
              'media_observation': {'id': v1['media_urn'], 'owner': 'urn:li:person:fixture-other', 'status': 'AVAILABLE'}}
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        first, first_args = (prepare_linkedin_fixture, native) if native_first else (prepare_linkedin_v1_media_fixture, v1)
        second, second_args = (prepare_linkedin_v1_media_fixture, v1) if native_first else (prepare_linkedin_fixture, native)
        first(ledger, **first_args)
        with pytest.raises(ValueError):
            second(ledger, **second_args)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 1
    finally:
        con.close()


@pytest.mark.parametrize('native_first', [False, True])
def test_native_and_v1_share_media_with_matching_owner(tmp_path, native_first):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    from scripts.social.linkedin_v1_media_fixture import prepare_linkedin_v1_media_fixture
    v1 = sample('image')
    key = copy.deepcopy(v1['key'])
    key['post_id'] = 'fixture-native-post'
    native = {'key': key, 'author': v1['author'], 'source': '## post:linkedin_post\nNoi dung gia\n',
              'anchor': 'post:linkedin_post', 'api_version': v1['api_version'], 'scheduled_at': v1['scheduled_at'],
              'media_kind': 'image', 'media_urn': v1['media_urn'],
              'media_observation': {'id': v1['media_urn'], 'owner': v1['author'], 'status': 'AVAILABLE'}}
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        builders = ((prepare_linkedin_fixture, native), (prepare_linkedin_v1_media_fixture, v1))
        if not native_first:
            builders = builders[::-1]
        ids = [builder(ledger, **args) for builder, args in builders]
        binding = con.execute('SELECT author,post_id,asset_id FROM linkedin_fixture_media_bindings').fetchone()
        assert binding == (v1['author'], v1['key']['post_id'], 'fixture-source-asset')
        assert len(ids) == 2
    finally:
        con.close()


def test_two_sources_compete_for_native_media_binding(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    from scripts.social.linkedin_v1_media_fixture import prepare_linkedin_v1_media_fixture
    v1 = sample('image')
    key = copy.deepcopy(v1['key'])
    key['post_id'] = 'fixture-native-post'
    native = {'key': key, 'author': v1['author'], 'source': '## post:linkedin_post\nNoi dung gia\n',
              'anchor': 'post:linkedin_post', 'api_version': v1['api_version'], 'scheduled_at': v1['scheduled_at'],
              'media_kind': 'image', 'media_urn': v1['media_urn'],
              'media_observation': {'id': v1['media_urn'], 'owner': v1['author'], 'status': 'AVAILABLE'}}
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        prepare_linkedin_fixture(DestinationFixtureLedger.initialize(con), **native)
    finally:
        con.close()
    other = copy.deepcopy(v1)
    other['key']['station_id'] = 'fixture-other-station'
    barrier = threading.Barrier(2)
    def worker(args):
        connection = sqlite3.connect(database, timeout=10)
        try:
            ledger = DestinationFixtureLedger.open(connection)
            barrier.wait(timeout=10)
            try:
                prepare_linkedin_v1_media_fixture(ledger, **args)
                return 'accepted'
            except ValueError:
                return 'refused'
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (v1, other)))
    assert sorted(results) == ['accepted', 'refused']
    con = sqlite3.connect(database)
    try:
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 2
        station = con.execute('SELECT station_id FROM linkedin_fixture_media_bindings').fetchone()[0]
        winner = con.execute('SELECT station_id FROM destination_fixture_intents WHERE post_id=?',
                             (v1['key']['post_id'],)).fetchone()[0]
        assert station == winner
    finally:
        con.close()


def test_v4_fixture_keeps_text_receipt_but_refuses_v1_media(tmp_path):
    from scripts.social.destination_ledger_fixture import _DDL, _REEL_DDL, _LINKEDIN_DDL
    from scripts.social.linkedin_v1_fixture_flow import prepare_linkedin_v1_fixture
    from scripts.social.linkedin_v1_media_fixture import prepare_linkedin_v1_media_fixture
    v1 = sample('image')
    text = {field: copy.deepcopy(v1[field]) for field in
            ('key', 'source', 'publication', 'author', 'api_version', 'scheduled_at', 'adapted_text')}
    text['publication']['posts'] = [row for row in text['publication']['posts']
                                   if row['post_id'] == text['key']['post_id']]
    text['publication']['posts'][0]['asset_ref'] = ''
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        con.execute(_DDL)
        con.execute(_REEL_DDL)
        con.execute(_LINKEDIN_DDL)
        con.execute('PRAGMA user_version=4')
        con.commit()
        ledger = DestinationFixtureLedger.open(con)
        with pytest.raises(ValueError):
            prepare_linkedin_v1_media_fixture(ledger, **v1)
        item = prepare_linkedin_v1_fixture(ledger, **text)
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T04:00:00Z')
        ledger.finish_linkedin_fixture(item, attempt=attempt, status=201,
                                       headers=[('x-restli-id', 'urn:li:share:123')])
        assert ledger.get_linkedin_fixture_receipt(item)['post_urn'] == 'urn:li:share:123'
    finally:
        con.close()
