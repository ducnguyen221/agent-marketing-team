"""Connect synthetic Threads previews to a disposable destination ledger.

No files, provider, network, human approval, actual scheduling or dispatch.
Target mapping and numeric user ID are test data, not account verification.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any

from scripts.social.channels.threads.direct import preview_marketing_anchor
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.lib.delivery_anchors import _split_frontmatter

_TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z')
_MEDIA = re.compile(r'https://fixture\.example\.test/assets/fixture-[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')


def _build(*, key: dict[str, str], target: dict[str, str], source: str, anchor: str, api_version: str,
           media_type: str, scheduled_at: str, media_url: str | None) -> dict[str, Any]:
    if (not isinstance(key, dict) or not isinstance(target, dict) or not isinstance(source, str) or len(source) > 32000
            or any(not isinstance(key.get(field), str) or not key[field] for field in ('content_id', 'campaign_id'))
            or set(target) != {'platform', 'account_id', 'destination_id', 'threads_user_id'}
            or key.get('platform') != 'threads' or target['platform'] != 'threads'
            or target['account_id'] != key.get('account_id') or target['destination_id'] != key.get('destination_id')):
        raise ValueError('fixture Threads target mismatch')
    user_id = target['threads_user_id']
    if (not isinstance(user_id, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', user_id)
            or target['account_id'] != 'fixture-threads-account-' + user_id
            or target['destination_id'] != 'fixture-threads-' + user_id):
        raise ValueError('fixture Threads target mismatch')
    header, _ = _split_frontmatter(source)
    if header is not None:
        import yaml

        class UniqueLoader(yaml.SafeLoader):
            def construct_mapping(self, node: Any, deep: bool = False) -> dict[str, Any]:
                result = {}
                for key_node, value_node in node.value:
                    if key_node.tag == 'tag:yaml.org,2002:merge':
                        raise ValueError('invalid fixture metadata')
                    name = self.construct_object(key_node, deep=deep)
                    if not isinstance(name, str) or name in result:
                        raise ValueError('invalid fixture metadata')
                    result[name] = self.construct_object(value_node, deep=deep)
                return result

        try:
            metadata = yaml.load(header, Loader=UniqueLoader)
        except (yaml.YAMLError, ValueError, TypeError, RecursionError):
            raise ValueError('invalid fixture metadata') from None
        if (not isinstance(metadata, dict) or metadata.get('schema') != 'content/1'
                or metadata.get('content_id') != key.get('content_id')
                or metadata.get('campaign_id') != key.get('campaign_id')):
            raise ValueError('fixture source identity mismatch')
    if not isinstance(scheduled_at, str) or not _TIME.fullmatch(scheduled_at):
        raise ValueError('invalid fixture schedule')
    try:
        datetime.strptime(scheduled_at, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        raise ValueError('invalid fixture schedule') from None
    if media_url is not None and (not isinstance(media_url, str) or not _MEDIA.fullmatch(media_url)):
        raise ValueError('fixture media URL required')
    if media_type == 'IMAGE' and media_url is not None and media_url.rsplit('.', 1)[-1].lower() not in ('jpg', 'jpeg', 'png'):
        raise ValueError('fixture media label mismatch')
    if media_type == 'VIDEO' and media_url is not None and media_url.rsplit('.', 1)[-1].lower() not in ('mp4', 'mov'):
        raise ValueError('fixture media label mismatch')
    candidate = preview_marketing_anchor(source=source, anchor=anchor, user_id=target['threads_user_id'],
                                         api_version=api_version, media_type=media_type, media_url=media_url)
    snapshot: dict[str, Any] = {'fixture_schema': 'threads-intent/1', 'platform': 'threads', 'account_id': key['account_id'],
                                'destination_id': key['destination_id'], 'target': target,
                                'content_id': key['content_id'], 'campaign_id': key['campaign_id'],
                                'source': source, 'anchor': anchor, 'api_version': api_version,
                                'media_type': media_type, 'media_url': media_url, 'scheduled_at': scheduled_at, 'candidate': candidate,
                                'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
                                'source_identity': ('caller_metadata_matches_unverified'
                                                    if header is not None else 'caller_text_only')}
    return snapshot


def prepare_threads_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], target: dict[str, str],
                            source: str, anchor: str, api_version: str, media_type: str,
                            scheduled_at: str, media_url: str | None = None) -> str:
    """Create one unapproved synthetic occurrence with a native candidate."""
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture ledger required')
    key, target = copy.deepcopy((key, target))
    snapshot = _build(key=key, target=target, source=source, anchor=anchor, api_version=api_version,
                      media_type=media_type, scheduled_at=scheduled_at, media_url=media_url)
    return ledger.prepare(key, snapshot)


def validate_threads_snapshot(payload: dict[str, Any], *, account: str, destination: str,
                              content: str, campaign: str) -> None:
    fields = {'fixture_schema', 'platform', 'account_id', 'destination_id', 'target', 'content_id', 'campaign_id',
              'source', 'anchor', 'api_version', 'media_type', 'media_url', 'scheduled_at', 'candidate',
              'source_sha256', 'source_identity'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('invalid Threads fixture snapshot')
    key = {'platform': 'threads', 'account_id': account, 'destination_id': destination,
           'content_id': content, 'campaign_id': campaign}
    rebuilt = _build(key=key, target=payload['target'], source=payload['source'], anchor=payload['anchor'],
                     api_version=payload['api_version'], media_type=payload['media_type'],
                     scheduled_at=payload['scheduled_at'], media_url=payload['media_url'])
    def canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
    if canonical(payload) != canonical(rebuilt):
        raise ValueError('Threads fixture snapshot mismatch')
