"""Preview separately adapted Threads text for a synthetic V1 Facebook post."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from scripts.lib.delivery_anchors import preview_facebook_post
from scripts.social.channels.threads.direct import preview_container
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.tiktok_fixture_flow import _validate_caption


def _build(*, key: dict[str, str], target: dict[str, str], source: str, publication: dict[str, Any],
           api_version: str, scheduled_at: str, adapted_text: str) -> dict[str, Any]:
    if (not isinstance(source, str) or len(source) > 32000 or not isinstance(key, dict)
            or key.get('platform') != 'threads' or not isinstance(publication, dict)
            or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id')
            or key.get('content_id') != publication.get('post_id') or not isinstance(key.get('post_id'), str)
            or not isinstance(target, dict) or set(target) != {'platform', 'account_id', 'destination_id', 'threads_user_id'}
            or target['platform'] != 'threads' or not isinstance(target['threads_user_id'], str)
            or not re.fullmatch(r'[1-9][0-9]{0,31}', target['threads_user_id'])):
        raise ValueError('invalid Threads V1 fixture')
    user_id = target['threads_user_id']
    if (target['account_id'] != 'fixture-threads-account-' + user_id
            or target['destination_id'] != 'fixture-threads-' + user_id
            or key.get('account_id') != target['account_id'] or key.get('destination_id') != target['destination_id']):
        raise ValueError('invalid Threads fixture target')
    source_preview = preview_facebook_post(source, publication, post_id=key['post_id'])
    post = next(item for item in publication['posts'] if item.get('post_id') == key['post_id'])
    if post.get('asset_ref', '') != '':
        raise ValueError('explicit source media needs a separate mapping')
    if not isinstance(adapted_text, str):
        raise ValueError('invalid Threads fixture text')
    normalized_text = adapted_text.replace('\r\n', '\n')
    if len(normalized_text) > 500:
        raise ValueError('Threads text exceeds fixture limit')
    _validate_caption(normalized_text)
    if normalized_text.strip() == source_preview['body_raw'].replace('\r\n', '\n').strip():
        raise ValueError('separately adapted Threads text required')
    _fixture_time(scheduled_at)
    if not scheduled_at.endswith('Z'):
        raise ValueError('Threads fixture uses UTC')
    candidate = preview_container(user_id=user_id, api_version=api_version, media_type='TEXT', text=adapted_text)
    selected = {field: post.get(field, '') for field in
                ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    return {'fixture_schema': 'threads-v1-facebook-text/1', 'platform': 'threads',
            'account_id': target['account_id'], 'destination_id': target['destination_id'], 'target': target,
            'content_id': key['content_id'], 'campaign_id': key['campaign_id'], 'channel_id': key['channel_id'],
            'post_id': key['post_id'], 'source': source,
            'publication': {'schema': 'publish/2', 'post_id': key['content_id'], 'campaign_id': key['campaign_id'],
                            'channel_id': key['channel_id'], 'posts': [selected]}, 'adapted_text': adapted_text,
            'source_notes': {'first_comment_omitted': bool(source_preview['first_comment_raw']),
                             'image_prompt_omitted': source_preview['image_prompt_present'],
                             'default_media_unchecked': True},
            'api_version': api_version, 'scheduled_at': scheduled_at, 'candidate': candidate}


def prepare_threads_v1_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], target: dict[str, str],
                               source: str, publication: dict[str, Any], api_version: str, scheduled_at: str,
                               adapted_text: str) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, target, publication = copy.deepcopy((key, target, publication))
    payload = _build(key=key, target=target, source=source, publication=publication, api_version=api_version,
                     scheduled_at=scheduled_at, adapted_text=adapted_text)
    return ledger.prepare(key, payload)


def validate_threads_v1_snapshot(payload: dict[str, Any], *, account: str, destination: str, content: str,
                                 campaign: str, channel: str, post: str) -> None:
    key = {'platform': 'threads', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, target=payload['target'], source=payload['source'], publication=payload['publication'],
                     api_version=payload['api_version'], scheduled_at=payload['scheduled_at'],
                     adapted_text=payload['adapted_text'])
    if json.dumps(rebuilt, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(
            payload, sort_keys=True, ensure_ascii=False, allow_nan=False):
        raise ValueError('Threads V1 snapshot mismatch')
