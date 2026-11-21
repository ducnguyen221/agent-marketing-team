"""Canonical delivery snapshots with limited sensitive-data checks."""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_RUNTIME_FIELDS = frozenset({'prepared_at', 'attempt_id', 'state', 'payload_digest'})
MAX_SOURCE_SNAPSHOT_BYTES = 32 * 1024 * 1024
_SECRET_FIELDS = frozenset({'authorization', 'token', 'accesstoken', 'refreshtoken',
                            'apikey', 'password', 'cookie', 'secret', 'clientsecret',
                            'privatekey', 'credential', 'credentials', 'signedurl', 'jwt'})
_SENSITIVE_QUERY_KEYS = _SECRET_FIELDS | frozenset({
    'sig', 'signature', 'xamzsignature', 'xamzcredential',
    'xgoogsignature', 'xgoogcredential', 'awsaccesskeyid',
})
_URL = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
_EXEMPTION_FIELDS = frozenset({'schema', 'decision', 'status', 'event_id', 'binding_event_id',
                               'key', 'payload_digest', 'declaration_ref', 'declaration_digest',
                               'decision_ref', 'by', 'quote', 'approved_at'})


def _field_name(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', value.lower())


def _check_urls(value: str) -> None:
    """Reject common signed/credential URL patterns without logging values.

    This is not a general detector for secrets or PII and cannot identify all
    signed URL schemes. Source payloads still need an explicit data policy.
    """
    for match in _URL.finditer(html.unescape(value)):
        try:
            url = urlsplit(match.group())
            if url.username is not None or url.password is not None:
                raise ValueError('credential URL forbidden in snapshot')
            for part in (url.query, url.fragment, url.fragment.partition('?')[2]):
                for key, _ in parse_qsl(part, keep_blank_values=True, max_num_fields=512):
                    if _field_name(key) in _SENSITIVE_QUERY_KEYS:
                        raise ValueError('sensitive URL component forbidden in snapshot')
        except ValueError:
            raise ValueError('sensitive or malformed URL forbidden in snapshot') from None


def _check(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError('snapshot keys must be strings')
            _check_urls(key)
            if _field_name(key) in _SECRET_FIELDS:
                raise ValueError('secret field forbidden in snapshot')
            _check(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _check(child)
    elif isinstance(value, str):
        _check_urls(value)


def canonical_snapshot(payload: dict[str, Any]) -> tuple[bytes, str]:
    """Return stable UTF-8 JSON and SHA-256, without runtime metadata."""
    if not isinstance(payload, dict):
        raise ValueError('snapshot must be an object')
    try:
        _check(payload)
    except RecursionError:
        raise ValueError('snapshot nesting is invalid') from None
    snapshot = {key: val for key, val in payload.items() if key not in _RUNTIME_FIELDS}
    try:
        data = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('invalid snapshot') from exc
    return data, hashlib.sha256(data).hexdigest()


def validate_source_envelope_basics(payload: dict[str, Any]) -> None:
    """Check common envelope shape, without approving or authorizing delivery.

    This does not verify source authority, QA, policy, platform capabilities,
    artifact bytes, PII absence, or the contents of approval_refs/depends_on.
    Platform-specific and nested schemas must be validated independently.
    """
    if __package__:
        from .delivery_ledger import KEY_FIELDS, _evidence_locator
    else:
        from delivery_ledger import KEY_FIELDS, _evidence_locator

    def invalid() -> None:
        raise ValueError('invalid source envelope')

    def utc_timestamp(value: Any) -> bool:
        if (not isinstance(value, str) or len(value) > 40
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)', value)):
            return False
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return False
        return True

    if not isinstance(payload, dict) or payload.get('schema') != 'marketing-publish/1':
        invalid()
    for field in KEY_FIELDS:
        value = payload.get(field)
        if (not isinstance(value, str) or not value or value != value.strip() or '*' in value
                or len(value) > 512 or any(unicodedata.category(c).startswith('C') for c in value)):
            invalid()
    if payload.get('provider') not in ('legacy', 'postiz'):
        invalid()
    try:
        _evidence_locator(payload.get('source_locator'))
        anchor = payload.get('content_anchor')
        digest = payload.get('source_digest')
        if (not isinstance(anchor, str) or len(anchor) > 256
                or not re.fullmatch(r'post:[a-z0-9_]+(?:#[0-9]+)?', anchor)
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or not utc_timestamp(payload.get('prepared_at'))):
            invalid()
        if (not isinstance(payload.get('text'), str)
                or not isinstance(payload.get('post_format'), str) or not payload['post_format'].strip()
                or not isinstance(payload.get('links'), dict)
                or not isinstance(payload.get('artifacts'), list)
                or not isinstance(payload.get('approval_refs'), list) or not payload['approval_refs']
                or not isinstance(payload.get('depends_on'), list)):
            invalid()
        if not isinstance(payload.get('privacy'), str) or not payload['privacy'].strip():
            invalid()
        if payload.get('mode') == 'scheduled':
            if not utc_timestamp(payload.get('scheduled_at')):
                invalid()
        elif payload.get('mode') != 'immediate' or payload.get('scheduled_at') is not None:
            invalid()
        zone = payload.get('timezone')
        if not isinstance(zone, str) or not zone or len(zone) > 128:
            invalid()
        ZoneInfo(zone)
        data, _ = canonical_snapshot(payload)
        if len(data) > MAX_SOURCE_SNAPSHOT_BYTES:
            invalid()
    except (ValueError, TypeError, ZoneInfoNotFoundError, RecursionError):
        raise ValueError('invalid source envelope') from None


def validate_facebook_web_dependency(payload: dict[str, Any], *, resolved_post_id: str | None,
                                     resolved_web_url: str | None) -> None:
    """Check a declared Facebook-to-web dependency against caller-supplied evidence.

    Independent Facebook posts need no web dependency. This checks consistency,
    not whether the caller's evidence is authentic, current, approved or published.
    Other dependency kinds, links, and media require their own validators.
    """
    def invalid() -> None:
        raise ValueError('invalid Facebook web dependency')

    if (not isinstance(payload, dict) or payload.get('platform') != 'facebook'
            or payload.get('post_format') != 'facebook_post'
            or not isinstance(payload.get('text'), str)
            or not isinstance(payload.get('links'), dict)
            or not isinstance(payload.get('depends_on'), list)):
        invalid()
    comment = payload.get('first_comment')
    if comment is not None and not isinstance(comment, str):
        invalid()
    if any('{{' in text or '}}' in text for text in (payload['text'], comment or '')):
        invalid()
    dependencies = payload['depends_on']
    if any(not isinstance(item, dict) or not isinstance(item.get('kind'), str) for item in dependencies):
        invalid()
    web = [item for item in dependencies if item['kind'] == 'web_url']
    link = payload['links'].get('web')
    if 'web' in payload['links'] and link is None:
        invalid()
    if not web and link is None:
        if resolved_post_id is not None or resolved_web_url is not None:
            invalid()
        return
    if (len(web) != 1 or set(web[0]) != {'kind', 'post_id', 'url'}
            or not isinstance(resolved_post_id, str) or not resolved_post_id.strip()
            or resolved_post_id != resolved_post_id.strip() or len(resolved_post_id) > 512 or '*' in resolved_post_id
            or any(unicodedata.category(char).startswith('C') for char in resolved_post_id)
            or not isinstance(resolved_web_url, str) or not resolved_web_url
            or resolved_web_url != resolved_web_url.strip() or len(resolved_web_url) > 4096
            or web[0].get('post_id') != resolved_post_id or web[0].get('url') != resolved_web_url
            or link != resolved_web_url or not comment):
        invalid()
    try:
        parsed = urlsplit(resolved_web_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or any(c.isspace() for c in resolved_web_url)
                or any(unicodedata.category(c).startswith('C') for c in resolved_web_url)):
            invalid()
        _ = parsed.port  # Forces validation of a present port.
        _check_urls(resolved_web_url)
    except ValueError:
        invalid()
    urls = [match.group() for match in _URL.finditer(comment)
            if match.start() == 0 or comment[match.start() - 1].isspace()
            or comment[match.start() - 1] in '([<"\'']
    if resolved_web_url not in urls:
        invalid()


def validate_g3_exemption_record(record: dict[str, Any], *, expected_key: dict[str, str],
                                 expected_payload_digest: str, expected_binding_event_id: str,
                                 expected_exemption_event_id: str,
                                 expected_declaration_ref: str, expected_declaration_digest: str,
                                 expected_decision_ref: str, expected_by: str,
                                 expected_quote: str, expected_approved_at: str) -> None:
    """Check record shape and consistency, never authenticate or grant approval.

    Expected values must be obtained independently from the current source and
    frozen preview, not from the record itself. The caller must separately
    establish source authority, the user's decision, QA, revocation and G1/G2.
    """
    if __package__:
        from .delivery_ledger import KEY_FIELDS, _evidence_locator
    else:
        from delivery_ledger import KEY_FIELDS, _evidence_locator

    def invalid() -> None:
        raise ValueError('invalid G3 exemption record')

    def valid_key(value: Any) -> bool:
        return (isinstance(value, dict) and set(value) == set(KEY_FIELDS)
                and all(isinstance(v, str) and v and v == v.strip() and '*' not in v
                        and len(v) <= 512 and not any(unicodedata.category(c).startswith('C') for c in v)
                        for v in value.values())
                and value['platform'] in ('facebook', 'youtube'))

    def valid_uuid(value: Any) -> bool:
        if not isinstance(value, str) or len(value) != 36:
            return False
        try:
            parsed = uuid.UUID(value)
        except ValueError:
            return False
        return parsed.version == 4 and str(parsed) == value

    def valid_digest(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None

    if not isinstance(record, dict) or set(record) != _EXEMPTION_FIELDS:
        invalid()
    if (record['schema'] != 'g3-exemption/1' or record['decision'] != 'waive_g3'
            or record['status'] != 'active' or not valid_key(expected_key)
            or not valid_key(record['key']) or record['key'] != expected_key):
        invalid()
    if (not valid_uuid(record['event_id']) or not valid_uuid(record['binding_event_id'])
            or record['event_id'] == record['binding_event_id']
            or record['event_id'] != expected_exemption_event_id
            or record['binding_event_id'] != expected_binding_event_id):
        invalid()
    if (not valid_digest(expected_payload_digest) or not valid_digest(expected_declaration_digest)
            or record['payload_digest'] != expected_payload_digest
            or record['declaration_digest'] != expected_declaration_digest):
        invalid()
    try:
        if (_evidence_locator(record['declaration_ref']) != expected_declaration_ref
                or _evidence_locator(record['decision_ref']) != expected_decision_ref):
            invalid()
        approved_at = record['approved_at']
        if (not isinstance(approved_at, str)
                or len(approved_at) > 40
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)', approved_at)):
            invalid()
        datetime.fromisoformat(approved_at.replace('Z', '+00:00'))
        if (not isinstance(record['by'], str) or not record['by'].strip() or len(record['by']) > 256
                or not isinstance(record['quote'], str) or not record['quote'].strip()
                or len(record['quote']) > 10000 or record['by'] != expected_by
                or record['quote'] != expected_quote or approved_at != expected_approved_at):
            invalid()
        canonical_snapshot(record)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('invalid G3 exemption record') from None
