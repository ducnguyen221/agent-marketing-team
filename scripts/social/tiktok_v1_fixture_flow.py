"""Adapt a synthetic V1 YouTube Short to a TikTok fixture."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter
from scripts.social.channels.tiktok.direct import preview_direct_post, preview_inbox_upload
from scripts.social.channels.youtube.direct import preview_marketing_anchor
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.fixture_assets import resolve_fixture_assets
from scripts.social.tiktok_fixture_flow import _UniqueLoader, _validate_caption


def _build(*, key: dict[str, str], target: dict[str, str], source: str, publication: dict[str, Any],
           manifest: list[dict[str, str]], scheduled_at: str, video_size: int, chunk_size: int,
           media_sha256_fixture: str, direct: dict[str, Any] | None = None) -> dict[str, Any]:
    if (not isinstance(source, str) or len(source) > 32000 or not isinstance(key, dict)
            or key.get('platform') != 'tiktok' or not isinstance(target, dict)
            or set(target) != {'account_id', 'destination_id', 'creator_id'}
            or not isinstance(target['creator_id'], str) or not isinstance(publication, dict)
            or publication.get('schema') != 'publish/2' or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id') or key.get('content_id') != publication.get('post_id')
            or not isinstance(key.get('post_id'), str) or not isinstance(publication.get('posts'), list)
            or len(publication['posts']) > 100 or any(not isinstance(item, dict) for item in publication['posts'])
            or not isinstance(media_sha256_fixture, str) or not re.fullmatch(r'[0-9a-f]{64}', media_sha256_fixture)):
        raise ValueError('invalid TikTok V1 fixture')
    creator = re.fullmatch(r'fixture-tiktok-creator-([A-Za-z0-9][A-Za-z0-9_-]{0,63})', target['creator_id'])
    if (creator is None or target['account_id'] != 'fixture-tiktok-account-' + creator.group(1)
            or target['destination_id'] != 'fixture-tiktok-profile-' + creator.group(1)
            or key.get('account_id') != target['account_id'] or key.get('destination_id') != target['destination_id']):
        raise ValueError('invalid TikTok fixture target')
    header, _ = _split_frontmatter(source)
    try:
        metadata = yaml.load(header, Loader=_UniqueLoader) if header is not None else None
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        raise ValueError('invalid TikTok fixture metadata') from None
    if (not isinstance(metadata, dict) or metadata.get('schema') != 'content/1'
            or metadata.get('content_id') != key['content_id'] or metadata.get('campaign_id') != key['campaign_id']):
        raise ValueError('invalid TikTok source identity')
    posts = publication['posts']
    matches = [item for item in posts if item.get('post_id') == key['post_id']]
    if len(matches) != 1:
        raise ValueError('invalid TikTok source post')
    item = matches[0]
    anchor = item.get('post_content')
    if (item.get('channel') != 'youtube' or item.get('post_format') != 'youtube_short'
            or item.get('content_id') != key['content_id'] or not isinstance(anchor, str)
            or not re.fullmatch(r'post:youtube_short(?:#[1-9][0-9]*)?', anchor)
            or sum(post.get('post_content') == anchor for post in posts) != 1):
        raise ValueError('invalid TikTok Short source')
    assets = resolve_fixture_assets(content_id=key['content_id'], post_id=key['post_id'], platform='youtube',
                                    post_format='youtube_short', asset_ref=item.get('asset_ref', ''), manifest=manifest)
    media_id = assets['media'][0]['id']
    preview = preview_marketing_anchor(source=source, anchor=anchor, title='Fixture', category_id='22',
                                      privacy='private', made_for_kids=False, media_id=media_id)
    caption = preview['request']['body']['snippet']['description']
    _validate_caption(caption)
    _fixture_time(scheduled_at)
    if direct is None:
        candidate = preview_inbox_upload(video_size=video_size, chunk_size=chunk_size)
    else:
        if (not isinstance(direct, dict) or set(direct) != {'creator', 'creator_revision', 'duration_sec',
                'post_info', 'consent_fixture', 'consent_digest_fixture'}
                or not isinstance(direct['post_info'], dict) or direct['post_info'].get('title') != caption):
            raise ValueError('invalid TikTok Direct fixture options')
        candidate = preview_direct_post(video_size=video_size, chunk_size=chunk_size,
            duration_sec=direct['duration_sec'], creator=direct['creator'], expected_creator=target['creator_id'],
            expected_revision=direct['creator_revision'], consent_fixture=direct['consent_fixture'],
            post_info=direct['post_info'], media_sha256_fixture=media_sha256_fixture,
            consent_digest_fixture=direct['consent_digest_fixture'])
    selected = {field: item.get(field, '') for field in
                ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    result = {'fixture_schema': 'tiktok-v1-short-inbox/1' if direct is None else 'tiktok-v1-short-direct/1',
            'platform': 'tiktok', 'account_id': key['account_id'],
            'destination_id': key['destination_id'], 'content_id': key['content_id'], 'campaign_id': key['campaign_id'],
            'channel_id': key['channel_id'], 'post_id': key['post_id'], 'target': target, 'source': source,
            'publication': {'schema': 'publish/2', 'post_id': key['content_id'], 'campaign_id': key['campaign_id'],
                            'channel_id': key['channel_id'], 'posts': [selected]}, 'manifest': manifest,
            'source_anchor': anchor, 'suggested_caption': caption, 'media_id': media_id,
            'media_sha256_fixture': media_sha256_fixture, 'video_size': video_size, 'chunk_size': chunk_size,
            'scheduled_at': scheduled_at, 'candidate': candidate}
    if direct is not None:
        result['direct'] = direct
    return result


def prepare_tiktok_v1_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], target: dict[str, str],
                              source: str, publication: dict[str, Any], manifest: list[dict[str, str]],
                              scheduled_at: str, video_size: int, chunk_size: int, media_sha256_fixture: str,
                              direct: dict[str, Any] | None = None) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, target, publication, manifest, direct = copy.deepcopy((key, target, publication, manifest, direct))
    payload = _build(key=key, target=target, source=source, publication=publication, manifest=manifest,
                     scheduled_at=scheduled_at, video_size=video_size, chunk_size=chunk_size,
                     media_sha256_fixture=media_sha256_fixture, direct=direct)
    return ledger.prepare(key, payload)


def validate_tiktok_v1_snapshot(payload: dict[str, Any], *, account: str, destination: str, content: str,
                                campaign: str, channel: str, post: str) -> None:
    key = {'platform': 'tiktok', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, target=payload['target'], source=payload['source'], publication=payload['publication'],
                     manifest=payload['manifest'], scheduled_at=payload['scheduled_at'], video_size=payload['video_size'],
                     chunk_size=payload['chunk_size'], media_sha256_fixture=payload['media_sha256_fixture'],
                     direct=payload.get('direct'))
    if json.dumps(rebuilt, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(
            payload, sort_keys=True, ensure_ascii=False, allow_nan=False):
        raise ValueError('TikTok V1 snapshot mismatch')
