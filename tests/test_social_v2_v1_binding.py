"""V1 metadata-to-preview binding with synthetic strings only."""
import importlib

import pytest


def fixture_source():
    return ('---\nschema: content/1\ncontent_id: fixture-content\n'
            'campaign_id: fixture-campaign\n---\n'
            '## post:facebook_post\nBai gia\n### comment_1\nComment gia\n'
            '### image_prompt\nPrompt noi bo\n'
            '## post:youtube_desc\nMo ta video gia\n')


def fixture_publication():
    return {'schema': 'publish/2', 'post_id': 'fixture-content', 'campaign_id': 'fixture-campaign',
            'channel_id': 'fixture-brand', 'posts': [
                {'post_id': 'fixture-fb', 'content_id': 'fixture-content', 'channel': 'facebook',
                 'post_format': 'facebook_post', 'post_content': 'post:facebook_post', 'asset_ref': ''},
                {'post_id': 'fixture-yt', 'content_id': 'fixture-content', 'channel': 'youtube',
                 'post_format': 'youtube_video', 'post_content': 'post:youtube_desc', 'asset_ref': ''},
            ]}


def invoke(source=None, publication=None, post_id='fixture-fb', provider='facebook', media=None):
    module = importlib.import_module('scripts.social.fixture_preview')
    assert hasattr(module, 'preview_v1_fixture'), 'V1 metadata binding is not implemented'
    settings = {'__type': provider}
    if provider == 'youtube':
        settings.update(title='Video gia', type='private')
    return module.preview_v1_fixture(
        source=fixture_source() if source is None else source,
        publication=fixture_publication() if publication is None else publication,
        post_id=post_id, integration_id='fixture-integration', provider=provider,
        media=[] if media is None else media, settings=settings, date_utc='2026-11-20T03:00:00Z')


def test_facebook_selects_post_and_excludes_image_prompt():
    result = invoke()
    assert result['source_post_id'] == 'fixture-fb'
    values = result['candidate']['posts'][0]['value']
    assert values[0]['content'].strip() == 'Bai gia'
    assert values[1]['content'].strip() == 'Comment gia'
    assert 'Prompt noi bo' not in str(values)
    assert 'v1_approval_not_inherited' in result['warnings']


def test_youtube_format_maps_to_v1_description_anchor():
    media = [{'id': 'fixture-video', 'path': '/fixture/video.mp4', 'kind': 'video'}]
    result = invoke(post_id='fixture-yt', provider='youtube', media=media)
    assert result['candidate']['posts'][0]['value'][0]['content'].strip() == 'Mo ta video gia'
    assert 'media_not_bound_to_v1_asset' in result['warnings']


def test_identity_mismatch_is_refused():
    with pytest.raises(ValueError):
        invoke(source=fixture_source().replace('campaign_id: fixture-campaign', 'campaign_id: fixture-other'))


def test_post_ids_and_anchors_must_be_unique():
    publication = fixture_publication()
    publication['posts'].append({**publication['posts'][0], 'post_id': 'fixture-another'})
    with pytest.raises(ValueError):
        invoke(publication=publication)


def test_wrong_platform_or_format_is_refused():
    publication = fixture_publication()
    publication['posts'][0]['post_format'] = 'youtube_video'
    with pytest.raises(ValueError):
        invoke(publication=publication)


def test_nonfixture_identity_is_refused():
    publication = fixture_publication()
    publication['campaign_id'] = 'actual-campaign'
    with pytest.raises(ValueError):
        invoke(publication=publication)


def test_duplicated_post_id_is_refused():
    publication = fixture_publication()
    publication['posts'].append(dict(publication['posts'][0]))
    with pytest.raises(ValueError):
        invoke(publication=publication)


def test_approved_v1_review_does_not_authorize_v2():
    publication = fixture_publication()
    publication['posts'][0]['review'] = {'status': 'approved', 'approved_by': 'fixture-human'}
    result = invoke(publication=publication)
    assert result['preview_only'] is True
    assert 'v1_approval_not_inherited' in result['warnings']


def test_duplicate_yaml_identity_is_refused():
    source = fixture_source().replace('content_id: fixture-content\n',
                                      'content_id: fixture-content\ncontent_id: fixture-content\n')
    with pytest.raises(ValueError):
        invoke(source=source)


def test_numbered_anchor_selects_exact_source_block():
    publication = fixture_publication()
    publication['posts'][0]['post_content'] = 'post:facebook_post#2'
    source = fixture_source() + '\n## post:facebook_post#2\nBai thu hai\n'
    assert invoke(source=source, publication=publication)['candidate']['posts'][0]['value'][0]['content'].strip() == 'Bai thu hai'


def test_missing_anchor_does_not_match_fenced_heading():
    source = fixture_source().replace('## post:youtube_desc\nMo ta video gia\n',
                                      '```\n## post:youtube_desc\nMo ta video gia\n```\n')
    with pytest.raises(ValueError):
        invoke(source=source, post_id='fixture-yt', provider='youtube',
               media=[{'id': 'fixture-video', 'path': '/fixture/video.mp4', 'kind': 'video'}])


@pytest.mark.parametrize('bad_id', ['fixture-one\nfixture-two', 'fixture-*', 'fixture-\u0000'])
def test_fixture_identity_rejects_controls_and_wildcards(bad_id):
    publication = fixture_publication()
    publication['posts'][0]['post_id'] = bad_id
    with pytest.raises(ValueError):
        invoke(publication=publication, post_id=bad_id)


def test_fixture_v1_youtube_asset_manifest_to_postiz_video_preview():
    module = importlib.import_module('scripts.social.fixture_preview')
    assert hasattr(module, 'preview_v1_with_assets_fixture')
    manifest = [
        {'content_id': 'fixture-content', 'post_id': 'fixture-yt', 'relative_path': 'video.mp4',
         'kind': 'video', 'id': 'fixture-video', 'path': '/fixture/video.mp4'},
        {'content_id': 'fixture-content', 'post_id': 'fixture-yt', 'relative_path': 'thumbnail.png',
         'kind': 'image', 'id': 'fixture-image', 'path': '/fixture/thumbnail.png'},
    ]
    result = module.preview_v1_with_assets_fixture(
        source=fixture_source(), publication=fixture_publication(), post_id='fixture-yt',
        integration_id='fixture-integration', provider='youtube', manifest=manifest,
        settings={'__type': 'youtube', 'title': 'Video gia', 'type': 'private'},
        date_utc='2026-11-20T03:00:00Z')
    assert result['candidate']['posts'][0]['value'][0]['image'] == [
        {'id': 'fixture-video', 'path': '/fixture/video.mp4'}]
    assert result['unmapped_assets'] == [{'relative_path': 'thumbnail.png', 'role': 'thumbnail'}]
    assert 'media_not_uploaded' in result['warnings']
    assert 'fixture_manifest_labels_matched_files_unverified' in result['warnings']
    assert 'media_not_bound_to_v1_asset' not in result['warnings']


def test_fixture_v1_facebook_thumbnail_to_postiz_image_preview():
    module = importlib.import_module('scripts.social.fixture_preview')
    manifest = [{'content_id': 'fixture-content', 'post_id': 'fixture-fb',
                 'relative_path': 'thumbnail.png', 'kind': 'image', 'id': 'fixture-image',
                 'path': '/fixture/thumbnail.png'}]
    result = module.preview_v1_with_assets_fixture(
        source=fixture_source(), publication=fixture_publication(), post_id='fixture-fb',
        integration_id='fixture-integration', provider='facebook', manifest=manifest,
        settings={'__type': 'facebook'}, date_utc='2026-11-20T03:00:00Z')
    assert result['candidate']['posts'][0]['value'][0]['image'] == [
        {'id': 'fixture-image', 'path': '/fixture/thumbnail.png'}]
    assert result['unmapped_assets'] == []


def test_v1_fixture_to_two_destination_ledger_without_network(monkeypatch):
    import socket
    from scripts.social.fixture_ledger import FixtureLedger

    def no_network(*args, **kwargs):
        raise AssertionError('network access is forbidden')

    monkeypatch.setattr(socket, 'socket', no_network)
    module = importlib.import_module('scripts.social.fixture_preview')
    ledger = FixtureLedger()
    manifest = [{'content_id': 'fixture-content', 'post_id': 'fixture-fb',
                 'relative_path': 'thumbnail.png', 'kind': 'image', 'id': 'fixture-image',
                 'path': '/fixture/thumbnail.png'}]
    items = []
    for destination in ('fixture-page-a', 'fixture-page-b'):
        result = module.preview_v1_with_assets_fixture(
            source=fixture_source(), publication=fixture_publication(), post_id='fixture-fb',
            integration_id=destination, provider='facebook', manifest=manifest,
            settings={'__type': 'facebook'}, date_utc='2026-11-20T03:00:00Z')
        identity = {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
                    'content': 'fixture-content', 'post': 'fixture-fb', 'platform': 'facebook',
                    'account': 'fixture-account', 'destination': destination, 'occurrence': 'fixture-slot'}
        items.append(ledger.prepare(identity, {'candidate': result['candidate']}))
    event = ledger.approve_batch([(item, ledger.get(item)['version']) for item in items])
    ledger.revoke(items[1])
    attempt = ledger.claim(items[0])
    ledger.finish(items[0], 'scheduled', receipt={'attempt': attempt, 'destination': 'fixture-page-a',
                                                'remote_id': 'fixture-job-a'})
    assert ledger.batch_status(event) == {'complete': False, 'states': {'scheduled': 1, 'revoked': 1}}
    assert ledger.get(items[1])['state'] == 'revoked'
