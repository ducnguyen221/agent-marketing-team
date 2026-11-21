"""Synthetic Telegram media intents mapped from V1 infographic or Short."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter
from scripts.social.channels.instagram.direct import preview_marketing_anchor as preview_instagram
from scripts.social.channels.telegram.direct import preview_media, valid_fixture_chat_id
from scripts.social.channels.youtube.direct import preview_marketing_anchor as preview_youtube
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.fixture_assets import resolve_fixture_assets
from scripts.social.tiktok_fixture_flow import _UniqueLoader


def _build(*, key: dict[str, str], source: str, publication: dict[str, Any], target: dict[str, str],
           chat_id: str, scheduled_at: str, adapted_caption: str, manifest: list[dict[str, str]]) -> dict[str, Any]:
    if (not isinstance(source, str) or len(source) > 32000 or not isinstance(key, dict)
            or key.get('platform') != 'telegram' or not isinstance(publication, dict)
            or publication.get('schema') != 'publish/2' or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id') or key.get('content_id') != publication.get('post_id')
            or not isinstance(key.get('post_id'), str) or not isinstance(publication.get('posts'), list)
            or len(publication['posts']) > 100 or any(not isinstance(item, dict) for item in publication['posts'])
            or not valid_fixture_chat_id(chat_id) or target != {'chat_id': chat_id, 'purpose': 'publish'}
            or not isinstance(key.get('account_id'), str)
            or not re.fullmatch(r'fixture-telegram-publish-bot-[A-Za-z0-9_-]{1,64}', key['account_id'])
            or key.get('destination_id') != 'fixture-telegram-channel-' + chat_id[4:]):
        raise ValueError('invalid Telegram V1 media binding')
    _fixture_time(scheduled_at)
    header, _ = _split_frontmatter(source)
    try:
        metadata = yaml.load(header, Loader=_UniqueLoader) if header is not None else None
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        raise ValueError('invalid Telegram V1 source') from None
    if (not isinstance(metadata, dict) or metadata.get('schema') != 'content/1'
            or metadata.get('content_id') != key['content_id'] or metadata.get('campaign_id') != key['campaign_id']):
        raise ValueError('invalid Telegram V1 source identity')
    posts = publication['posts']
    matches = [item for item in posts if item.get('post_id') == key['post_id']]
    if len(matches) != 1:
        raise ValueError('invalid Telegram V1 post')
    post = matches[0]
    mapping = {('facebook', 'infographic'): ('image', 'post:infographic'),
               ('youtube', 'youtube_short'): ('video', 'post:youtube_short')}
    choice = mapping.get((post.get('channel'), post.get('post_format')))
    anchor = post.get('post_content')
    if (choice is None or post.get('content_id') != key['content_id'] or not isinstance(anchor, str)
            or not re.fullmatch(re.escape(choice[1]) + r'(?:#[1-9][0-9]*)?', anchor)
            or sum(item.get('post_content') == anchor for item in posts) != 1):
        raise ValueError('invalid Telegram V1 media source')
    kind = choice[0]
    asset = resolve_fixture_assets(content_id=key['content_id'], post_id=key['post_id'], platform=post['channel'],
        post_format=post['post_format'], asset_ref=post.get('asset_ref', ''), manifest=manifest)['media'][0]
    if kind == 'image':
        source_preview = preview_instagram(source=source, anchor=anchor, user_id='1', api_version='v1.0',
            media_type='IMAGE', media_url='https://fixture.example.test/asset.jpg')
        source_caption = source_preview['request']['params'].get('caption', '')
    else:
        source_preview = preview_youtube(source=source, anchor=anchor, title='Fixture', category_id='22',
            privacy='private', made_for_kids=False, media_id='fixture-video')
        source_caption = source_preview['request']['body']['snippet']['description']
    candidate = preview_media(chat_id=chat_id, media_kind=kind, media_id=asset['id'], caption=adapted_caption)
    selected = {field: post.get(field, '') for field in
                ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    return {'fixture_schema': f'telegram-v1-{kind}/1', 'platform': 'telegram', 'account_id': key['account_id'],
            'destination_id': key['destination_id'], 'content_id': key['content_id'], 'campaign_id': key['campaign_id'],
            'channel_id': key['channel_id'], 'post_id': key['post_id'], 'chat_id': chat_id, 'target': target,
            'source': source, 'publication': {'schema': 'publish/2', 'post_id': key['content_id'],
                'campaign_id': key['campaign_id'], 'channel_id': key['channel_id'], 'posts': [selected]},
            'manifest': manifest, 'media_kind': kind, 'source_caption': source_caption, 'adapted_caption': adapted_caption,
            'scheduled_at': scheduled_at, 'candidate': candidate}


def prepare_telegram_media_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], source: str,
        publication: dict[str, Any], target: dict[str, str], chat_id: str, scheduled_at: str,
        adapted_caption: str, manifest: list[dict[str, str]]) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, publication, target, manifest = copy.deepcopy((key, publication, target, manifest))
    return ledger.prepare(key, _build(key=key, source=source, publication=publication, target=target, chat_id=chat_id,
        scheduled_at=scheduled_at, adapted_caption=adapted_caption, manifest=manifest))


def validate_telegram_media_snapshot(payload: dict[str, Any], *, account: str, destination: str, content: str,
                                     campaign: str, channel: str, post: str) -> None:
    key = {'platform': 'telegram', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, **{field: payload[field] for field in ('source', 'publication', 'target', 'chat_id',
        'scheduled_at', 'adapted_caption', 'manifest')})
    if json.dumps(rebuilt, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(
            payload, sort_keys=True, ensure_ascii=False, allow_nan=False):
        raise ValueError('Telegram media fixture snapshot mismatch')
