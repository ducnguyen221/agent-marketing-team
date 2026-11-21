"""Adapt a synthetic V1 Facebook post to a Telegram publishing bot and channel."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from scripts.lib.delivery_anchors import preview_facebook_post
from scripts.social.channels.telegram.direct import preview_message, valid_fixture_chat_id
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time


def _build(*, key: dict[str, str], source: str, publication: dict[str, Any], target: dict[str, str],
           chat_id: str, scheduled_at: str, adapted_text: str) -> dict[str, Any]:
    if (not isinstance(source, str) or len(source) > 32000 or not isinstance(key, dict)
            or key.get('platform') != 'telegram' or not isinstance(publication, dict)
            or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id')
            or key.get('content_id') != publication.get('post_id') or not isinstance(key.get('post_id'), str)
            or not valid_fixture_chat_id(chat_id)
            or target != {'chat_id': chat_id, 'purpose': 'publish'}
            or not isinstance(key.get('account_id'), str)
            or not re.fullmatch(r'fixture-telegram-publish-bot-[A-Za-z0-9_-]{1,64}', key['account_id'])
            or key.get('destination_id') != 'fixture-telegram-channel-' + chat_id[4:]):
        raise ValueError('invalid Telegram fixture binding')
    source_preview = preview_facebook_post(source, publication, post_id=key['post_id'])
    post = next(item for item in publication['posts'] if item.get('post_id') == key['post_id'])
    if post.get('asset_ref', '') != '':
        raise ValueError('explicit source media needs separate mapping')
    if (not isinstance(adapted_text, str) or adapted_text.replace('\r\n', '\n').strip()
            == source_preview['body_raw'].replace('\r\n', '\n').strip()):
        raise ValueError('separately adapted Telegram text required')
    _fixture_time(scheduled_at)
    candidate = preview_message(chat_id=chat_id, text=adapted_text)
    selected = {field: post.get(field, '') for field in
                ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    return {'fixture_schema': 'telegram-v1-facebook-text/1', 'platform': 'telegram',
            'account_id': key['account_id'], 'destination_id': key['destination_id'], 'content_id': key['content_id'],
            'campaign_id': key['campaign_id'], 'channel_id': key['channel_id'], 'post_id': key['post_id'],
            'chat_id': chat_id, 'target': target, 'source': source,
            'publication': {'schema': 'publish/2', 'post_id': key['content_id'], 'campaign_id': key['campaign_id'],
                            'channel_id': key['channel_id'], 'posts': [selected]}, 'adapted_text': adapted_text,
            'source_notes': {'first_comment_omitted': bool(source_preview['first_comment_raw']),
                             'image_prompt_omitted': source_preview['image_prompt_present'], 'default_media_unchecked': True},
            'scheduled_at': scheduled_at, 'candidate': candidate}


def prepare_telegram_v1_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], source: str,
                                publication: dict[str, Any], target: dict[str, str], chat_id: str,
                                scheduled_at: str, adapted_text: str) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, publication, target = copy.deepcopy((key, publication, target))
    return ledger.prepare(key, _build(key=key, source=source, publication=publication, target=target,
                                    chat_id=chat_id, scheduled_at=scheduled_at, adapted_text=adapted_text))


def validate_telegram_snapshot(payload: dict[str, Any], *, account: str, destination: str, content: str,
                               campaign: str, channel: str, post: str) -> None:
    key = {'platform': 'telegram', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, source=payload['source'], publication=payload['publication'], target=payload['target'],
                     chat_id=payload['chat_id'], scheduled_at=payload['scheduled_at'], adapted_text=payload['adapted_text'])
    if json.dumps(rebuilt, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(
            payload, sort_keys=True, ensure_ascii=False, allow_nan=False):
        raise ValueError('Telegram fixture snapshot mismatch')
