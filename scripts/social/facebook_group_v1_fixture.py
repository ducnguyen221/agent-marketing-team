"""Bind one synthetic V1 Reel to a synthetic Group UI occurrence."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from scripts.social.facebook_fixture_flow import _build as build_facebook_reel
from scripts.social.tiktok_fixture_flow import _validate_caption


def build_group_reel_snapshot(*, identity: dict[str, str], source: str, publication: dict[str, Any],
                              manifest: list[dict[str, str]], adapted_text: str) -> dict[str, Any]:
    identity, publication, manifest = copy.deepcopy((identity, publication, manifest))
    if (not isinstance(identity, dict) or identity.get('platform') != 'facebook'
            or not isinstance(identity.get('account'), str)
            or not re.fullmatch(r'fixture-facebook-account-[A-Za-z0-9_-]{1,64}', identity['account'])
            or not isinstance(identity.get('destination'), str)
            or not re.fullmatch(r'fixture-group-[A-Za-z0-9_-]{1,64}', identity['destination'])
            or any(not isinstance(identity.get(field), str) or not identity[field].startswith('fixture-')
                   for field in ('station', 'brand', 'campaign', 'content', 'post', 'occurrence'))):
        raise ValueError('invalid Group fixture identity')
    key = {'platform': 'facebook', 'account_id': 'fixture-facebook-account-1',
           'destination_id': 'fixture-facebook-page-1', 'channel_id': identity['brand'],
           'campaign_id': identity['campaign'], 'content_id': identity['content'], 'post_id': identity['post']}
    # The Page builder is reused only to validate the synthetic source and manifest.
    # Its candidate is discarded; the resulting Group action never calls a Page API.
    validated = build_facebook_reel(key=key, source=source, publication=publication, manifest=manifest,
                                    scheduled_at='2026-11-20T03:00:00Z', api_version='v1.0', page_id='1', media_type='REEL')
    if not isinstance(adapted_text, str):
        raise ValueError('invalid Group fixture caption')
    adapted_text = adapted_text.replace('\r\n', '\n')
    _validate_caption(adapted_text)
    if adapted_text.strip() == validated['candidate']['caption'].replace('\r\n', '\n').strip():
        raise ValueError('separately adapted Group caption required')
    return {'action': 'group_video', 'text': adapted_text, 'media_kind': 'video',
            'media_id': validated['candidate']['media_id'], 'destination_type': 'group', 'source': None,
            'reuse_permission': False, 'v1_binding': {'identity': identity, 'source': source,
                'publication': validated['publication'], 'manifest': manifest}}


def validate_group_reel_snapshot(identity: dict[str, str], snapshot: dict[str, Any]) -> None:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('v1_binding'), dict):
        raise ValueError('invalid Group V1 binding')
    binding = snapshot['v1_binding']
    if (set(binding) != {'identity', 'source', 'publication', 'manifest'} or binding['identity'] != identity):
        raise ValueError('Group V1 identity mismatch')
    rebuilt = build_group_reel_snapshot(identity=identity, source=binding['source'], publication=binding['publication'],
                                        manifest=binding['manifest'], adapted_text=snapshot.get('text'))
    if json.dumps(rebuilt, ensure_ascii=False, sort_keys=True, allow_nan=False) != json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False):
        raise ValueError('Group V1 snapshot mismatch')
