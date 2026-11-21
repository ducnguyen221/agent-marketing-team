"""Instagram preview and scheduling fixture; no real account or network."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter
from scripts.social.channels.instagram.direct import preview_marketing_anchor
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.tiktok_fixture_flow import _UniqueLoader

_MEDIA = re.compile(r'https://fixture\.example\.test/assets/fixture-[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')


def _build(*, key: dict[str, str], user_id: str, source: str, anchor: str, api_version: str,
           media_type: str, scheduled_at: str, media_url: str) -> dict[str, Any]:
    if (not isinstance(key, dict) or key.get('platform') != 'instagram' or not isinstance(user_id, str)
            or any(not isinstance(key.get(field), str) or not key[field] for field in ('content_id', 'campaign_id'))
            or not re.fullmatch(r'[1-9][0-9]{0,31}', user_id)
            or key.get('account_id') != 'fixture-instagram-account-' + user_id
            or key.get('destination_id') != 'fixture-instagram-' + user_id
            or not isinstance(source, str) or len(source) > 32000
            or not isinstance(media_url, str) or not _MEDIA.fullmatch(media_url)):
        raise ValueError('invalid Instagram fixture input')
    suffix = media_url.rsplit('.', 1)[-1].lower()
    if (media_type == 'IMAGE' and suffix not in ('jpg', 'jpeg', 'png')) or (
            media_type == 'REELS' and suffix not in ('mp4', 'mov')):
        raise ValueError('fixture media label mismatch')
    _fixture_time(scheduled_at)
    header, _ = _split_frontmatter(source)
    if header is not None:
        try:
            metadata = yaml.load(header, Loader=_UniqueLoader)
        except (yaml.YAMLError, ValueError, TypeError, RecursionError):
            raise ValueError('invalid fixture metadata') from None
        if (not isinstance(metadata, dict) or metadata.get('schema') != 'content/1'
                or metadata.get('content_id') != key.get('content_id')
                or metadata.get('campaign_id') != key.get('campaign_id')):
            raise ValueError('fixture source identity mismatch')
    candidate = preview_marketing_anchor(source=source, anchor=anchor, user_id=user_id, api_version=api_version,
                                         media_type=media_type, media_url=media_url)
    return {'fixture_schema': 'instagram-intent/1', 'platform': 'instagram', 'account_id': key['account_id'],
            'destination_id': key['destination_id'], 'content_id': key['content_id'],
            'campaign_id': key['campaign_id'], 'user_id': user_id, 'source': source, 'anchor': anchor,
            'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(), 'api_version': api_version,
            'media_type': media_type, 'scheduled_at': scheduled_at, 'media_url': media_url, 'candidate': candidate}


def prepare_instagram_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], user_id: str,
                              source: str, anchor: str, api_version: str, media_type: str,
                              scheduled_at: str, media_url: str) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key = copy.deepcopy(key)
    snapshot = _build(key=key, user_id=user_id, source=source, anchor=anchor, api_version=api_version,
                      media_type=media_type, scheduled_at=scheduled_at, media_url=media_url)
    return ledger.prepare(key, snapshot)


def validate_instagram_snapshot(payload: dict[str, Any], *, account: str, destination: str,
                                content: str, campaign: str) -> None:
    fields = {'fixture_schema', 'platform', 'account_id', 'destination_id', 'content_id', 'campaign_id',
              'user_id', 'source', 'anchor', 'source_sha256', 'api_version', 'media_type', 'scheduled_at',
              'media_url', 'candidate'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('invalid Instagram fixture snapshot')
    key = {'platform': 'instagram', 'account_id': account, 'destination_id': destination,
           'content_id': content, 'campaign_id': campaign}
    rebuilt = _build(key=key, user_id=payload['user_id'], source=payload['source'], anchor=payload['anchor'],
                     api_version=payload['api_version'], media_type=payload['media_type'],
                     scheduled_at=payload['scheduled_at'], media_url=payload['media_url'])
    def canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
    if canonical(rebuilt) != canonical(payload):
        raise ValueError('Instagram fixture snapshot mismatch')
