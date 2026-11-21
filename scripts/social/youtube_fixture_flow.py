"""Synthetic V1-shaped video into native YouTube destination fixture."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter
from scripts.social.channels.youtube.direct import preview_marketing_anchor
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.fixture_assets import resolve_fixture_assets
from scripts.social.tiktok_fixture_flow import _UniqueLoader


def _build(*, key: dict[str, str], source: str, publication: dict[str, Any], manifest: list[dict[str, str]],
           scheduled_at: str, title: str, category_id: str, privacy: str, made_for_kids: bool) -> dict[str, Any]:
    if (not isinstance(key, dict) or key.get('platform') != 'youtube'
            or not isinstance(key.get('account_id'), str) or not isinstance(key.get('destination_id'), str)
            or any(not isinstance(key.get(field), str) or not key[field]
                   for field in ('channel_id', 'campaign_id', 'content_id', 'post_id'))
            or not isinstance(source, str) or len(source) > 32000 or not isinstance(publication, dict)
            or publication.get('schema') != 'publish/2' or publication.get('channel_id') != key['channel_id']
            or publication.get('campaign_id') != key['campaign_id'] or publication.get('post_id') != key['content_id']):
        raise ValueError('invalid YouTube fixture binding')
    match = re.fullmatch(r'fixture-youtube-account-([A-Za-z0-9][A-Za-z0-9_-]{0,63})', key['account_id'])
    if match is None or key['destination_id'] != 'fixture-youtube-channel-' + match.group(1):
        raise ValueError('invalid YouTube fixture target')
    _fixture_time(scheduled_at)
    header, _ = _split_frontmatter(source)
    if header is None:
        raise ValueError('fixture source identity missing')
    try:
        metadata = yaml.load(header, Loader=_UniqueLoader)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        raise ValueError('invalid fixture metadata') from None
    if (not isinstance(metadata, dict) or metadata.get('schema') != 'content/1'
            or metadata.get('content_id') != key['content_id'] or metadata.get('campaign_id') != key['campaign_id']):
        raise ValueError('fixture source identity mismatch')
    posts = publication.get('posts')
    if (not isinstance(posts, list) or len(posts) > 100 or any(not isinstance(row, dict)
            or not isinstance(row.get('post_id'), str) or not row['post_id'] for row in posts)):
        raise ValueError('invalid fixture publication')
    matches = [row for row in posts if row['post_id'] == key['post_id']]
    if len(matches) != 1:
        raise ValueError('fixture post missing or ambiguous')
    row = matches[0]
    anchor = row.get('post_content')
    post_format = row.get('post_format')
    anchor_prefix = {'youtube_video': 'post:youtube_desc', 'youtube_short': 'post:youtube_short'}.get(post_format)
    if (row.get('content_id') != key['content_id'] or row.get('channel') != 'youtube'
            or anchor_prefix is None or not isinstance(anchor, str)
            or not re.fullmatch(re.escape(anchor_prefix) + r'(?:#[1-9][0-9]*)?', anchor)
            or sum(post.get('post_content') == anchor for post in posts) != 1):
        raise ValueError('fixture post contract mismatch')
    assets = resolve_fixture_assets(content_id=key['content_id'], post_id=key['post_id'], platform='youtube',
                                    post_format=post_format, asset_ref=row.get('asset_ref', ''), manifest=manifest)
    video_id = assets['media'][0]['id']
    thumbnail = next((entry for entry in manifest if entry['relative_path'] == 'thumbnail.png'), None)
    if thumbnail is not None and thumbnail['id'] == video_id:
        raise ValueError('fixture video and thumbnail IDs must differ')
    candidate = preview_marketing_anchor(source=source, anchor=anchor, title=title, category_id=category_id,
                                         privacy=privacy, made_for_kids=made_for_kids, media_id=video_id)
    selected = {field: row.get(field, '') for field in ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    clean_publication = {'schema': 'publish/2', 'post_id': key['content_id'], 'campaign_id': key['campaign_id'],
                         'channel_id': key['channel_id'], 'posts': [selected]}
    return {'fixture_schema': 'youtube-native-intent/1', 'platform': 'youtube', 'account_id': key['account_id'],
            'destination_id': key['destination_id'], 'channel_id': key['channel_id'], 'campaign_id': key['campaign_id'],
            'content_id': key['content_id'], 'post_id': key['post_id'], 'source': source,
            'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(), 'publication': clean_publication,
            'manifest': manifest, 'thumbnail': thumbnail, 'scheduled_at': scheduled_at, 'title': title,
            'category_id': category_id, 'privacy': privacy, 'made_for_kids': made_for_kids, 'candidate': candidate}


def prepare_youtube_native_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], source: str,
                                   publication: dict[str, Any], manifest: list[dict[str, str]], scheduled_at: str,
                                   title: str, category_id: str, privacy: str, made_for_kids: bool) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, publication, manifest = copy.deepcopy((key, publication, manifest))
    snapshot = _build(key=key, source=source, publication=publication, manifest=manifest, scheduled_at=scheduled_at,
                      title=title, category_id=category_id, privacy=privacy, made_for_kids=made_for_kids)
    return ledger.prepare(key, snapshot)


def validate_youtube_snapshot(payload: dict[str, Any], *, account: str, destination: str, content: str,
                              campaign: str, channel: str, post: str) -> None:
    fields = {'fixture_schema', 'platform', 'account_id', 'destination_id', 'channel_id', 'campaign_id', 'content_id',
              'post_id', 'source', 'source_sha256', 'publication', 'manifest', 'thumbnail', 'scheduled_at', 'title',
              'category_id', 'privacy', 'made_for_kids', 'candidate'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('invalid YouTube fixture snapshot')
    key = {'platform': 'youtube', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, source=payload['source'], publication=payload['publication'], manifest=payload['manifest'],
                     scheduled_at=payload['scheduled_at'], title=payload['title'], category_id=payload['category_id'],
                     privacy=payload['privacy'], made_for_kids=payload['made_for_kids'])
    def canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
    if canonical(payload) != canonical(rebuilt):
        raise ValueError('YouTube fixture snapshot mismatch')
