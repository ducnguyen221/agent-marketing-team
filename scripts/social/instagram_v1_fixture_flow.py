"""Adapt synthetic V1 Facebook content to Instagram fixtures."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter
from scripts.social.channels.facebook.direct import preview_reel_anchor
from scripts.social.channels.instagram.direct import preview_container
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.fixture_assets import resolve_fixture_assets
from scripts.social.instagram_fixture_flow import _build as instagram_build
from scripts.social.tiktok_fixture_flow import _UniqueLoader


def _build(*, key: dict[str, str], source: str, publication: dict[str, Any],
           manifest: list[dict[str, str]], user_id: str, api_version: str, scheduled_at: str) -> dict[str, Any]:
    if (not isinstance(source, str) or len(source) > 32000
            or not isinstance(key, dict) or key.get('platform') != 'instagram' or not isinstance(publication, dict)
            or publication.get('schema') != 'publish/2' or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id')
            or key.get('content_id') != publication.get('post_id') or not isinstance(key.get('post_id'), str)
            or not isinstance(publication.get('posts'), list) or len(publication['posts']) > 100
            or any(not isinstance(post, dict) for post in publication['posts'])):
        raise ValueError('invalid Instagram V1 binding')
    posts = publication['posts']
    matches = [post for post in posts if post.get('post_id') == key['post_id']]
    if len(matches) != 1:
        raise ValueError('invalid Instagram V1 post')
    post = matches[0]
    anchor = post.get('post_content')
    post_format = post.get('post_format')
    if (post.get('channel') != 'facebook' or post_format not in ('infographic', 'reel')
            or post.get('content_id') != key['content_id'] or not isinstance(anchor, str)
            or not re.fullmatch(r'post:' + post_format + r'(?:#[1-9][0-9]*)?', anchor)
            or sum(item.get('post_content') == anchor for item in posts) != 1
            or not isinstance(source, str) or _split_frontmatter(source)[0] is None):
        raise ValueError('invalid Instagram infographic source')
    assets = resolve_fixture_assets(content_id=key['content_id'], post_id=key['post_id'], platform='facebook',
                                    post_format=post_format, asset_ref=post.get('asset_ref'), manifest=manifest)
    asset = assets['media'][0]
    suffix = asset['path'].rsplit('.', 1)[-1].lower()
    if not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,100}', asset['id']):
        raise ValueError('invalid Instagram fixture asset')
    url = f"https://fixture.example.test/assets/{asset['id']}.{suffix}"
    if post_format == 'infographic':
        candidate = instagram_build(key=key, source=source, user_id=user_id, anchor=anchor, api_version=api_version,
                                    media_type='IMAGE', scheduled_at=scheduled_at, media_url=url)['candidate']
    else:
        if (not isinstance(user_id, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', user_id)
                or key.get('account_id') != 'fixture-instagram-account-' + user_id
                or key.get('destination_id') != 'fixture-instagram-' + user_id):
            raise ValueError('invalid Instagram fixture target')
        _fixture_time(scheduled_at)
        header, _ = _split_frontmatter(source)
        try:
            metadata = yaml.load(header, Loader=_UniqueLoader)
        except (yaml.YAMLError, ValueError, TypeError, RecursionError):
            raise ValueError('invalid Instagram fixture metadata') from None
        if (not isinstance(metadata, dict) or metadata.get('schema') != 'content/1'
                or metadata.get('content_id') != key['content_id']
                or metadata.get('campaign_id') != key['campaign_id']):
            raise ValueError('invalid Instagram fixture identity')
        reel = preview_reel_anchor(source=source, anchor=anchor, page_id='1', api_version=api_version,
                                   media_id=asset['id'])
        candidate = preview_container(user_id=user_id, api_version=api_version, media_type='REELS',
                                      media_url=url, caption=reel['caption'])
        candidate['source_anchor'] = anchor
    selected = {field: post.get(field, '') for field in
                ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    return {'fixture_schema': f'instagram-v1-{post_format}/1', 'platform': 'instagram',
            'account_id': key['account_id'], 'destination_id': key['destination_id'],
            'content_id': key['content_id'], 'campaign_id': key['campaign_id'], 'channel_id': key['channel_id'],
            'post_id': key['post_id'], 'source': source,
            'publication': {'schema': 'publish/2', 'post_id': key['content_id'], 'campaign_id': key['campaign_id'],
                            'channel_id': key['channel_id'], 'posts': [selected]},
            'manifest': manifest, 'user_id': user_id, 'api_version': api_version, 'scheduled_at': scheduled_at,
            'candidate': candidate}


def prepare_instagram_v1_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], source: str,
                                 publication: dict[str, Any], manifest: list[dict[str, str]], user_id: str,
                                 api_version: str, scheduled_at: str) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, publication, manifest = copy.deepcopy((key, publication, manifest))
    snapshot = _build(key=key, source=source, publication=publication, manifest=manifest, user_id=user_id,
                      api_version=api_version, scheduled_at=scheduled_at)
    return ledger.prepare(key, snapshot)


def validate_instagram_v1_snapshot(payload: dict[str, Any], *, account: str, destination: str,
                                   content: str, campaign: str, channel: str, post: str) -> None:
    key = {'platform': 'instagram', 'account_id': account, 'destination_id': destination,
           'content_id': content, 'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, source=payload['source'], publication=payload['publication'],
                     manifest=payload['manifest'], user_id=payload['user_id'], api_version=payload['api_version'],
                     scheduled_at=payload['scheduled_at'])
    if json.dumps(rebuilt, ensure_ascii=False, sort_keys=True, allow_nan=False) != json.dumps(
            payload, ensure_ascii=False, sort_keys=True, allow_nan=False):
        raise ValueError('Instagram V1 snapshot mismatch')
