"""Map V1 default asset roles to synthetic media, without touching the filesystem."""
import importlib

import pytest


def resolve(*, platform='youtube', post_id='fixture-yt', manifest=None, asset_ref=''):
    mod = importlib.import_module('scripts.social.fixture_assets')
    return mod.resolve_fixture_assets(
        content_id='fixture-content', post_id=post_id, platform=platform,
        post_format='youtube_video' if platform == 'youtube' else 'facebook_post',
        asset_ref=asset_ref, manifest=manifest)


def item(path, kind, post_id='fixture-yt'):
    return {'content_id': 'fixture-content', 'post_id': post_id, 'relative_path': path,
            'kind': kind, 'id': 'fixture-' + kind, 'path': '/fixture/' + path}


def test_youtube_default_video_and_thumbnail_keep_separate_roles():
    result = resolve(manifest=[item('video.mp4', 'video'), item('thumbnail.png', 'image')])
    assert result['media'] == [{'id': 'fixture-video', 'path': '/fixture/video.mp4', 'kind': 'video'}]
    assert result['unmapped'] == [{'relative_path': 'thumbnail.png', 'role': 'thumbnail'}]
    assert result['fixture_only'] is True


def test_facebook_default_thumbnail_becomes_fake_image():
    result = resolve(platform='facebook', post_id='fixture-fb',
                     manifest=[item('thumbnail.png', 'image', post_id='fixture-fb')])
    assert result['media'][0]['kind'] == 'image'
    assert result['unmapped'] == []


@pytest.mark.parametrize('manifest', [[], [item('video.mp4', 'video')],
    [item('video.mp4', 'video', post_id='fixture-other'), item('thumbnail.png', 'image')],
    [item('video.mp4', 'video'), item('thumbnail.png', 'image'), item('video.mp4', 'video')]])
def test_missing_wrong_owner_or_duplicate_asset_is_refused(manifest):
    with pytest.raises(ValueError):
        resolve(manifest=manifest)


@pytest.mark.parametrize('asset_ref', ['../outside.png', '/outside.png', 'C:\\outside.png', 'one.png,two.png', '.', 'video.mp4'])
def test_ambiguous_or_unsafe_override_is_refused(asset_ref):
    with pytest.raises(ValueError):
        resolve(platform='facebook', post_id='fixture-fb', asset_ref=asset_ref, manifest=[])


@pytest.mark.parametrize('asset_ref', ['.', 'video.mp4'])
def test_facebook_override_must_name_supported_image_even_with_matching_manifest(asset_ref):
    with pytest.raises(ValueError):
        resolve(platform='facebook', post_id='fixture-fb', asset_ref=asset_ref,
                manifest=[item(asset_ref, 'image', post_id='fixture-fb')])
