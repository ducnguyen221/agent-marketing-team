"""Synthetic LinkedIn native candidates in a disposable scheduling ledger."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter
from scripts.social.channels.linkedin.direct import preview_marketing_anchor
from scripts.social.channels.linkedin.media import inspect_media
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.tiktok_fixture_flow import _UniqueLoader


def _build(*, key: dict[str, str], author: str, source: str, anchor: str, api_version: str,
           scheduled_at: str, media_kind: str | None, media_urn: str | None,
           media_observation: dict[str, Any] | None) -> dict[str, Any]:
    if (not isinstance(key, dict) or key.get('platform') != 'linkedin' or not isinstance(author, str)
            or not isinstance(source, str) or len(source) > 32000
            or any(not isinstance(key.get(field), str) or not key[field] for field in ('content_id', 'campaign_id'))):
        raise ValueError('invalid LinkedIn fixture')
    person = re.fullmatch(r'urn:li:person:fixture-([A-Za-z0-9][A-Za-z0-9_-]{0,63})', author)
    organization = re.fullmatch(r'urn:li:organization:([1-9][0-9]{0,31})', author)
    if person:
        account, destination = 'fixture-linkedin-account-' + person.group(1), 'fixture-linkedin-person-' + person.group(1)
    elif organization:
        account, destination = ('fixture-linkedin-org-account-' + organization.group(1),
                                'fixture-linkedin-org-' + organization.group(1))
    else:
        raise ValueError('invalid LinkedIn fixture author')
    if key.get('account_id') != account or key.get('destination_id') != destination:
        raise ValueError('LinkedIn fixture target mismatch')
    if media_kind is None:
        if media_urn is not None or media_observation is not None:
            raise ValueError('invalid LinkedIn fixture media')
    elif (media_kind not in ('image', 'video') or not isinstance(media_urn, str)
          or not re.fullmatch(r'urn:li:' + media_kind + r':fixture-[A-Za-z0-9_-]{1,100}', media_urn)):
        raise ValueError('invalid LinkedIn fixture media')
    if media_kind is not None:
        if (not isinstance(media_observation, dict) or set(media_observation) != {'id', 'owner', 'status'}
                or inspect_media(status=200, body=media_observation, expected_urn=media_urn,
                                 expected_owner=author)['state'] != 'provider_reports_available'):
            raise ValueError('LinkedIn fixture media not available')
    _fixture_time(scheduled_at)
    header, _ = _split_frontmatter(source)
    if header is not None:
        try:
            metadata = yaml.load(header, Loader=_UniqueLoader)
        except (yaml.YAMLError, ValueError, TypeError, RecursionError):
            raise ValueError('invalid fixture metadata') from None
        if (not isinstance(metadata, dict) or metadata.get('schema') != 'content/1'
                or metadata.get('content_id') != key['content_id'] or metadata.get('campaign_id') != key['campaign_id']):
            raise ValueError('fixture source identity mismatch')
    candidate = preview_marketing_anchor(source=source, anchor=anchor, author=author, api_version=api_version,
                                         media_kind=media_kind, media_urn=media_urn)
    return {'fixture_schema': 'linkedin-intent/1', 'platform': 'linkedin', 'account_id': account,
            'destination_id': destination, 'content_id': key['content_id'], 'campaign_id': key['campaign_id'],
            'author': author, 'source': source, 'anchor': anchor, 'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'api_version': api_version, 'scheduled_at': scheduled_at, 'media_kind': media_kind,
            'media_urn': media_urn, 'media_observation': media_observation, 'candidate': candidate}


def prepare_linkedin_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], author: str,
                             source: str, anchor: str, api_version: str, scheduled_at: str,
                             media_kind: str | None = None, media_urn: str | None = None,
                             media_observation: dict[str, Any] | None = None) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, media_observation = copy.deepcopy((key, media_observation))
    snapshot = _build(key=key, author=author, source=source, anchor=anchor, api_version=api_version,
                      scheduled_at=scheduled_at, media_kind=media_kind, media_urn=media_urn,
                      media_observation=media_observation)
    return ledger.prepare(key, snapshot)


def validate_linkedin_snapshot(payload: dict[str, Any], *, account: str, destination: str,
                               content: str, campaign: str) -> None:
    fields = {'fixture_schema', 'platform', 'account_id', 'destination_id', 'content_id', 'campaign_id', 'author',
              'source', 'anchor', 'source_sha256', 'api_version', 'scheduled_at', 'media_kind', 'media_urn',
              'media_observation', 'candidate'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('invalid LinkedIn fixture snapshot')
    key = {'platform': 'linkedin', 'account_id': account, 'destination_id': destination,
           'content_id': content, 'campaign_id': campaign}
    rebuilt = _build(key=key, author=payload['author'], source=payload['source'], anchor=payload['anchor'],
                     api_version=payload['api_version'], scheduled_at=payload['scheduled_at'],
                     media_kind=payload['media_kind'], media_urn=payload['media_urn'],
                     media_observation=payload['media_observation'])
    def canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
    if canonical(payload) != canonical(rebuilt):
        raise ValueError('LinkedIn fixture snapshot mismatch')
