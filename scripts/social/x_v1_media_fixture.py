"""Scheduled X V1 media fixtures; observations are unauthenticated caller data."""
from __future__ import annotations

import copy
import json
from typing import Any

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.x_v1_media_preview import preview_v1_media


def _build(*, key: dict[str, str], source: str, publication: dict[str, Any], target: dict[str, str],
           user_id: str, scheduled_at: str, adapted_text: str, manifest: list[dict[str, str]],
           media_kind: str, media_id: str, observation: dict[str, str]) -> dict[str, Any]:
    if (not isinstance(key, dict) or key.get('platform') != 'x' or not isinstance(publication, dict)
            or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id')
            or key.get('content_id') != publication.get('post_id')
            or key.get('account_id') != f'fixture-x-account-{user_id}'
            or key.get('destination_id') != f'fixture-x-profile-{user_id}' or target != {'user_id': user_id}):
        raise ValueError('invalid X media fixture binding')
    _fixture_time(scheduled_at)
    preview = preview_v1_media(source=source, publication=publication, post_id=key.get('post_id'),
                               manifest=manifest, media_kind=media_kind, user_id=user_id, media_id=media_id,
                               adapted_text=adapted_text)
    fields = {'user_id', 'media_id', 'asset_id', 'media_kind', 'state', 'observed_at', 'expires_at'}
    if (not isinstance(observation, dict) or set(observation) != fields
            or observation['user_id'] != user_id or observation['media_id'] != media_id
            or observation['asset_id'] != preview['asset']['id'] or observation['media_kind'] != media_kind
            or observation['state'] not in ('pending', 'failed', 'succeeded')
            or _fixture_time(observation['observed_at']) >= _fixture_time(observation['expires_at'])):
        raise ValueError('invalid X media fixture observation')
    post = next(item for item in publication['posts'] if item.get('post_id') == key['post_id'])
    selected = {field: post.get(field, '') for field in
                ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    return {'fixture_schema': 'x-v1-facebook-media/1', 'platform': 'x', 'account_id': key['account_id'],
            'destination_id': key['destination_id'], 'channel_id': key['channel_id'], 'campaign_id': key['campaign_id'],
            'content_id': key['content_id'], 'post_id': key['post_id'], 'source': source,
            'publication': {'schema': 'publish/2', 'post_id': key['content_id'], 'campaign_id': key['campaign_id'],
                            'channel_id': key['channel_id'], 'posts': [selected]},
            'target': target, 'user_id': user_id, 'scheduled_at': scheduled_at, 'adapted_text': adapted_text,
            'manifest': manifest, 'media_kind': media_kind, 'media_id': media_id, 'observation': observation,
            'candidate': preview['candidate'], 'source_notes': preview['source_notes']}


def prepare_x_media_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], source: str,
                            publication: dict[str, Any], target: dict[str, str], user_id: str, scheduled_at: str,
                            adapted_text: str, manifest: list[dict[str, str]], media_kind: str, media_id: str,
                            observation: dict[str, str]) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, publication, target, manifest, observation = copy.deepcopy((key, publication, target, manifest, observation))
    return ledger.prepare(key, _build(key=key, source=source, publication=publication, target=target, user_id=user_id,
        scheduled_at=scheduled_at, adapted_text=adapted_text, manifest=manifest, media_kind=media_kind,
        media_id=media_id, observation=observation))


def validate_x_media_snapshot(payload: dict[str, Any], *, account: str, destination: str, content: str,
                              campaign: str, channel: str, post: str) -> None:
    key = {'platform': 'x', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, **{field: payload[field] for field in ('source', 'publication', 'target', 'user_id',
        'scheduled_at', 'adapted_text', 'manifest', 'media_kind', 'media_id', 'observation')})
    if json.dumps(rebuilt, ensure_ascii=False, sort_keys=True, allow_nan=False) != json.dumps(
            payload, ensure_ascii=False, sort_keys=True, allow_nan=False):
        raise ValueError('X media fixture snapshot mismatch')


def require_ready_at(payload: dict[str, Any], now: str) -> None:
    """Check only a caller-supplied fixture observation against fixture time."""
    obs = payload['observation']
    if (obs['state'] != 'succeeded' or not _fixture_time(obs['observed_at']) <= _fixture_time(now)
            < _fixture_time(obs['expires_at'])):
        raise ValueError('X fixture media unavailable at claim time')
