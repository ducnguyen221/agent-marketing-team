"""Map one V1 Facebook attachment to a synthetic LinkedIn media candidate."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from scripts.social.channels.linkedin.direct import preview_post
from scripts.social.channels.linkedin.media import inspect_media
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.fixture_assets import resolve_fixture_assets
from scripts.social.linkedin_v1_fixture_flow import _build as build_text


def _build(*, key: dict[str, str], source: str, publication: dict[str, Any], author: str,
           api_version: str, scheduled_at: str, adapted_text: str, manifest: list[dict[str, str]],
           media_kind: str, media_urn: str, media_observation: dict[str, str]) -> dict[str, Any]:
    if not isinstance(publication, dict) or not isinstance(key, dict):
        raise ValueError('invalid LinkedIn media fixture')
    normalized = copy.deepcopy(publication)
    try:
        if not isinstance(normalized['posts'], list) or any(not isinstance(row, dict) for row in normalized['posts']):
            raise ValueError('invalid fixture posts')
        post = next(row for row in normalized['posts'] if row.get('post_id') == key['post_id'])
        asset_ref = post['asset_ref']
    except (KeyError, TypeError, StopIteration):
        raise ValueError('missing LinkedIn fixture asset') from None
    if (not isinstance(asset_ref, str) or not asset_ref or media_kind not in ('image', 'video')
            or not isinstance(media_urn, str)
            or not re.fullmatch(r'urn:li:' + media_kind + r':fixture-[A-Za-z0-9_-]{1,100}', media_urn)):
        raise ValueError('invalid LinkedIn fixture asset')
    asset = resolve_fixture_assets(content_id=key['content_id'], post_id=key['post_id'], platform='facebook',
                                   post_format='facebook_post', asset_ref=asset_ref, manifest=manifest,
                                   attachment_kind=media_kind)['media'][0]
    if (not isinstance(media_observation, dict)
            or set(media_observation) != {'id', 'owner', 'status', 'asset_id'}
            or media_observation['asset_id'] != asset['id']
            or inspect_media(status=200, body={field: media_observation[field] for field in ('id', 'owner', 'status')},
                             expected_urn=media_urn, expected_owner=author)['state'] != 'provider_reports_available'):
        raise ValueError('LinkedIn fixture media unavailable')
    post['asset_ref'] = ''
    payload = build_text(key=key, source=source, publication=normalized, author=author, api_version=api_version,
                         scheduled_at=scheduled_at, adapted_text=adapted_text)
    payload['fixture_schema'] = 'linkedin-v1-facebook-media/1'
    payload['publication']['posts'][0]['asset_ref'] = asset_ref
    payload.update(manifest=manifest, asset=asset, media_kind=media_kind, media_urn=media_urn,
                   media_observation=media_observation,
                   candidate=preview_post(author=author, text=adapted_text, api_version=api_version,
                                          media_kind=media_kind, media_urn=media_urn))
    payload['source_notes']['default_media_unchecked'] = False
    return payload


def prepare_linkedin_v1_media_fixture(ledger: DestinationFixtureLedger, **kwargs: Any) -> str:
    """Prepare one synthetic V1 media mapping; never access media bytes."""
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    args = copy.deepcopy(kwargs)
    return ledger.prepare(args['key'], _build(**args))


def validate_linkedin_v1_media_snapshot(payload: dict[str, Any], *, account: str, destination: str,
                                        content: str, campaign: str, channel: str, post: str) -> None:
    key = {'platform': 'linkedin', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    fields = ('source', 'publication', 'author', 'api_version', 'scheduled_at', 'adapted_text',
              'manifest', 'media_kind', 'media_urn', 'media_observation')
    rebuilt = _build(key=key, **{field: payload[field] for field in fields})
    if json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) != json.dumps(
            rebuilt, ensure_ascii=False, sort_keys=True, allow_nan=False):
        raise ValueError('LinkedIn media fixture snapshot mismatch')
