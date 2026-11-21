"""Synthetic V1-shaped Facebook content to native destination fixture."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter, preview_facebook_post
from scripts.social.channels.facebook.direct import preview_marketing_anchor, preview_reel_anchor
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.fixture_assets import resolve_fixture_assets
from scripts.social.tiktok_fixture_flow import _UniqueLoader


def _build(*, key: dict[str, str], source: str, publication: dict[str, Any], manifest: list[dict[str, str]],
           scheduled_at: str, api_version: str, page_id: str, media_type: str) -> dict[str, Any]:
    if (not isinstance(key, dict) or key.get('platform') != 'facebook' or not isinstance(page_id, str)
            or not re.fullmatch(r'[1-9][0-9]{0,31}', page_id)
            or key.get('account_id') != 'fixture-facebook-account-' + page_id
            or key.get('destination_id') != 'fixture-facebook-page-' + page_id
            or not isinstance(publication, dict) or not isinstance(source, str) or len(source) > 32000
            or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id')
            or key.get('content_id') != publication.get('post_id') or not isinstance(key.get('post_id'), str)):
        raise ValueError('invalid Facebook fixture binding')
    _fixture_time(scheduled_at)
    if media_type == 'REEL':
        header, _ = _split_frontmatter(source)
        try:
            metadata = yaml.load(header, Loader=_UniqueLoader) if header is not None else None
        except (yaml.YAMLError, ValueError, TypeError, RecursionError):
            raise ValueError('invalid Reel source metadata') from None
        posts = publication.get('posts')
        if (publication.get('schema') != 'publish/2' or not isinstance(metadata, dict)
                or metadata.get('schema') != 'content/1' or metadata.get('content_id') != key['content_id']
                or metadata.get('campaign_id') != key['campaign_id'] or not isinstance(posts, list)
                or len(posts) > 100 or any(not isinstance(item, dict) for item in posts)):
            raise ValueError('invalid Reel fixture binding')
        matches = [item for item in posts if item.get('post_id') == key['post_id']]
        if len(matches) != 1:
            raise ValueError('Reel post missing or ambiguous')
        item = matches[0]
        anchor = item.get('post_content')
        if (item.get('channel') != 'facebook' or item.get('post_format') != 'reel'
                or item.get('content_id') != key['content_id'] or not isinstance(anchor, str)
                or not re.fullmatch(r'post:reel(?:#[1-9][0-9]*)?', anchor)
                or sum(other.get('post_content') == anchor for other in posts) != 1):
            raise ValueError('invalid Reel post')
        binding = {'anchor': anchor}
    else:
        binding = preview_facebook_post(source, publication, post_id=key['post_id'])
    if any(not isinstance(post.get('post_id'), str) or not post['post_id'] for post in publication['posts']):
        raise ValueError('invalid Facebook fixture publication')
    matches = [post for post in publication['posts'] if post['post_id'] == key['post_id']]
    post = matches[0]
    if media_type == 'REEL':
        assets = resolve_fixture_assets(content_id=key['content_id'], post_id=key['post_id'], platform='facebook',
                                        post_format='reel', asset_ref=post.get('asset_ref', ''), manifest=manifest)
        media_id = assets['media'][0]['id']
    elif media_type in ('IMAGE', 'VIDEO'):
        assets = resolve_fixture_assets(content_id=key['content_id'], post_id=key['post_id'], platform='facebook',
                                        post_format='facebook_post', asset_ref=post.get('asset_ref', ''), manifest=manifest,
                                        attachment_kind='video' if media_type == 'VIDEO' else 'image')
        asset = assets['media'][0]
        suffix = asset['path'].rsplit('.', 1)[-1].lower()
        if suffix not in (('mp4',) if media_type == 'VIDEO' else ('png', 'jpg', 'jpeg')) or not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,100}', asset['id']):
            raise ValueError('invalid Facebook fixture asset')
        media_url = f"https://fixture.example.test/assets/{asset['id']}.{suffix}"
    elif media_type == 'TEXT' and manifest == [] and post.get('asset_ref', '') == '':
        media_url = None
    else:
        raise ValueError('invalid Facebook fixture media')
    selected = {field: post.get(field, '') for field in ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    clean_publication = {'schema': 'publish/2', 'post_id': publication['post_id'], 'campaign_id': publication['campaign_id'],
                         'channel_id': publication['channel_id'], 'posts': [selected]}
    candidate = (preview_reel_anchor(source=source, anchor=binding['anchor'], page_id=page_id,
                                     api_version=api_version, media_id=media_id) if media_type == 'REEL'
                 else preview_marketing_anchor(source=source, anchor=binding['anchor'], page_id=page_id,
                                               api_version=api_version, media_type=media_type, media_url=media_url))
    return {'fixture_schema': 'facebook-native-intent/1', 'platform': 'facebook', 'account_id': key['account_id'],
            'destination_id': key['destination_id'], 'content_id': key['content_id'], 'campaign_id': key['campaign_id'],
            'channel_id': key['channel_id'], 'post_id': key['post_id'], 'source': source,
            'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(), 'publication': clean_publication,
            'manifest': manifest, 'page_id': page_id, 'api_version': api_version, 'media_type': media_type,
            'scheduled_at': scheduled_at, 'candidate': candidate}


def prepare_facebook_native_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], source: str,
                                    publication: dict[str, Any], manifest: list[dict[str, str]], scheduled_at: str,
                                    api_version: str, page_id: str, media_type: str) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, publication, manifest = copy.deepcopy((key, publication, manifest))
    snapshot = _build(key=key, source=source, publication=publication, manifest=manifest, scheduled_at=scheduled_at,
                      api_version=api_version, page_id=page_id, media_type=media_type)
    return ledger.prepare(key, snapshot)


def validate_facebook_snapshot(payload: dict[str, Any], *, account: str, destination: str, content: str,
                               campaign: str, channel: str, post: str) -> None:
    fields = {'fixture_schema', 'platform', 'account_id', 'destination_id', 'content_id', 'campaign_id', 'channel_id',
              'post_id', 'source', 'source_sha256', 'publication', 'manifest', 'page_id', 'api_version', 'media_type',
              'scheduled_at', 'candidate'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('invalid Facebook fixture snapshot')
    key = {'platform': 'facebook', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, source=payload['source'], publication=payload['publication'], manifest=payload['manifest'],
                     scheduled_at=payload['scheduled_at'], api_version=payload['api_version'],
                     page_id=payload['page_id'], media_type=payload['media_type'])
    def canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
    if canonical(rebuilt) != canonical(payload):
        raise ValueError('Facebook fixture snapshot mismatch')
