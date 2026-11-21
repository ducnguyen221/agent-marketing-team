"""Preview separately adapted LinkedIn text for a synthetic V1 Facebook post."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from scripts.lib.delivery_anchors import preview_facebook_post
from scripts.social.channels.linkedin.direct import preview_post
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.tiktok_fixture_flow import _validate_caption


def _build(*, key: dict[str, str], source: str, publication: dict[str, Any], author: str,
           api_version: str, scheduled_at: str, adapted_text: str) -> dict[str, Any]:
    if (not isinstance(source, str) or len(source) > 32000 or not isinstance(key, dict)
            or key.get('platform') != 'linkedin' or not isinstance(publication, dict)
            or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id')
            or key.get('content_id') != publication.get('post_id') or not isinstance(key.get('post_id'), str)
            or not isinstance(author, str)):
        raise ValueError('invalid LinkedIn V1 fixture')
    person = re.fullmatch(r'urn:li:person:fixture-([A-Za-z0-9][A-Za-z0-9_-]{0,63})', author)
    org = re.fullmatch(r'urn:li:organization:([1-9][0-9]{0,31})', author)
    if person:
        account, destination = 'fixture-linkedin-account-' + person.group(1), 'fixture-linkedin-person-' + person.group(1)
    elif org:
        account, destination = 'fixture-linkedin-org-account-' + org.group(1), 'fixture-linkedin-org-' + org.group(1)
    else:
        raise ValueError('invalid LinkedIn fixture author')
    if key.get('account_id') != account or key.get('destination_id') != destination:
        raise ValueError('LinkedIn fixture target mismatch')
    source_preview = preview_facebook_post(source, publication, post_id=key['post_id'])
    post = next(item for item in publication['posts'] if item.get('post_id') == key['post_id'])
    if post.get('asset_ref', '') != '':
        raise ValueError('explicit source media needs a separate mapping')
    _validate_caption(adapted_text)
    if adapted_text.replace('\r\n', '\n').strip() == source_preview['body_raw'].replace('\r\n', '\n').strip():
        raise ValueError('separately adapted LinkedIn text required')
    _fixture_time(scheduled_at)
    candidate = preview_post(author=author, text=adapted_text, api_version=api_version)
    selected = {field: post.get(field, '') for field in
                ('post_id', 'content_id', 'channel', 'post_format', 'post_content', 'asset_ref')}
    return {'fixture_schema': 'linkedin-v1-facebook-text/1', 'platform': 'linkedin', 'account_id': account,
            'destination_id': destination, 'content_id': key['content_id'], 'campaign_id': key['campaign_id'],
            'channel_id': key['channel_id'], 'post_id': key['post_id'], 'author': author, 'source': source,
            'publication': {'schema': 'publish/2', 'post_id': key['content_id'], 'campaign_id': key['campaign_id'],
                            'channel_id': key['channel_id'], 'posts': [selected]},
            'adapted_text': adapted_text, 'source_notes': {'first_comment_omitted': bool(source_preview['first_comment_raw']),
            'image_prompt_omitted': source_preview['image_prompt_present'], 'default_media_unchecked': True},
            'api_version': api_version, 'scheduled_at': scheduled_at, 'candidate': candidate}


def prepare_linkedin_v1_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], source: str,
                                publication: dict[str, Any], author: str, api_version: str, scheduled_at: str,
                                adapted_text: str) -> str:
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, publication = copy.deepcopy((key, publication))
    payload = _build(key=key, source=source, publication=publication, author=author, api_version=api_version,
                     scheduled_at=scheduled_at, adapted_text=adapted_text)
    return ledger.prepare(key, payload)


def validate_linkedin_v1_snapshot(payload: dict[str, Any], *, account: str, destination: str, content: str,
                                  campaign: str, channel: str, post: str) -> None:
    key = {'platform': 'linkedin', 'account_id': account, 'destination_id': destination, 'content_id': content,
           'campaign_id': campaign, 'channel_id': channel, 'post_id': post}
    rebuilt = _build(key=key, source=payload['source'], publication=payload['publication'], author=payload['author'],
                     api_version=payload['api_version'], scheduled_at=payload['scheduled_at'],
                     adapted_text=payload['adapted_text'])
    if json.dumps(rebuilt, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(
            payload, sort_keys=True, ensure_ascii=False, allow_nan=False):
        raise ValueError('LinkedIn V1 snapshot mismatch')
