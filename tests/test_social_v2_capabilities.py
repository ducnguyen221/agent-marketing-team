"""Capabilities distinguish exercised synthetic paths from planned actions."""
import importlib

import pytest


def module():
    mod = importlib.import_module('scripts.social.capabilities')
    assert hasattr(mod, 'capabilities')
    return mod


def test_facebook_page_image_has_fixture_preview_but_no_live_enablement():
    result = module().capabilities(platform='facebook', destination='page', action='post_image')
    assert result['fixture_preview'] is True
    assert result['live_enabled'] is False
    assert result['planned_methods'] == ['api']


def test_group_and_native_duet_are_planned_ui_actions_not_api_claims():
    group = module().capabilities(platform='facebook', destination='group', action='post_image')
    duet = module().capabilities(platform='tiktok', destination='profile', action='create_duet')
    assert group['planned_methods'] == ['ui', 'manual'] and not group['fixture_preview']
    assert duet['planned_methods'] == ['ui', 'manual'] and not duet['fixture_preview']
    assert group['live_enabled'] is False and duet['live_enabled'] is False


def test_unknown_capability_is_not_inferred():
    with pytest.raises(ValueError):
        module().capabilities(platform='facebook', destination='group', action='create_duet')


def test_caller_cannot_modify_subsequent_result():
    first = module().capabilities(platform='facebook', destination='page', action='post_image')
    first['planned_methods'].append('ui')
    assert module().capabilities(platform='facebook', destination='page', action='post_image')['planned_methods'] == ['api']


def test_facebook_text_candidate_is_discoverable():
    result = module().capabilities(platform='facebook', destination='page', action='post_text')
    assert result['fixture_preview'] is True


def test_facebook_page_video_is_native_preview_only():
    result = module().capabilities(platform='facebook', destination='page', action='post_video')
    assert result['preview_schema'] == 'facebook_native'
    assert result['fixture_preview'] is True
    assert result['live_enabled'] is False


def test_facebook_reel_identifies_start_only_fixture():
    result = module().capabilities(platform='facebook', destination='page', action='post_reel')
    assert result['preview_schema'] == 'facebook_reel_start'
    assert result['fixture_preview'] is True
    assert result['live_enabled'] is False


def test_catalog_lists_planned_and_exercised_entries_without_live_routes():
    records = module().list_capabilities()
    assert any(item['scope'] == 'planned' for item in records)
    assert any(item['scope'] == 'offline_candidate_only' for item in records)
    assert all(item['live_enabled'] is False for item in records)


def test_catalog_distinguishes_native_linkedin_from_postiz_reference():
    linkedin = module().capabilities(platform='linkedin', destination='account', action='post_text')
    facebook = module().capabilities(platform='facebook', destination='page', action='post_image')
    group = module().capabilities(platform='facebook', destination='group', action='post_image')
    assert linkedin['preview_schema'] == 'linkedin_native'
    assert facebook['preview_schema'] == 'facebook_native'
    assert group['preview_schema'] is None


@pytest.mark.parametrize('action', ['post_image', 'post_video'])
def test_linkedin_media_candidates_are_native_but_not_live(action):
    result = module().capabilities(platform='linkedin', destination='account', action=action)
    assert result['preview_schema'] == 'linkedin_native'
    assert result['fixture_preview'] is True
    assert result['live_enabled'] is False


@pytest.mark.parametrize('action', ['upload_video', 'post_video'])
def test_tiktok_video_modes_are_native_previews_only(action):
    result = module().capabilities(platform='tiktok', destination='profile', action=action)
    assert result['preview_schema'] == 'tiktok_native'
    assert result['live_enabled'] is False
