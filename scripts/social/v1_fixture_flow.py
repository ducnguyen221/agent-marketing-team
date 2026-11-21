"""Bind V1-shaped Facebook fixture outputs to a disposable V2 SQLite intent.

Uses the existing Postiz-shaped offline research candidate; no runtime vendor,
provider, credentials, real station access, approval transfer or actual send.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.fixture_preview import preview_v1_with_assets_fixture


def prepare_facebook_v1_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], source: str,
                                publication: dict[str, Any], manifest: list[dict[str, str]],
                                scheduled_at: str) -> str:
    """Persist a source-bound preview without inheriting V1's approvals."""
    key = copy.deepcopy(key)
    publication = copy.deepcopy(publication)
    manifest = copy.deepcopy(manifest)
    if (type(ledger) is not DestinationFixtureLedger or not isinstance(key, dict) or not isinstance(publication, dict)
            or key.get('platform') != 'facebook' or key.get('channel_id') != publication.get('channel_id')
            or key.get('campaign_id') != publication.get('campaign_id')
            or key.get('content_id') != publication.get('post_id') or not isinstance(key.get('post_id'), str)
            or not isinstance(key.get('destination_id'), str)):
        raise ValueError('fixture V1 binding mismatch')
    _fixture_time(scheduled_at)
    candidate = preview_v1_with_assets_fixture(source=source, publication=publication, post_id=key['post_id'],
                                               integration_id=key['destination_id'], provider='facebook',
                                               manifest=manifest, settings={'__type': 'facebook'}, date_utc=scheduled_at)
    snapshot = {'platform': 'facebook', 'account_id': key.get('account_id'), 'destination_id': key['destination_id'],
                'scheduled_at': scheduled_at, 'candidate_schema': 'postiz_reference', 'candidate': candidate,
                'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest()}
    return ledger.prepare(key, snapshot)
