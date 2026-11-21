"""Build a candidate Postiz create-post body without network or approval.

Based on public documentation consulted 2026-11-18; the installed version and
provider behaviour must be verified independently before dispatch is enabled.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
import copy
import re
import unicodedata

if __package__:
    from .delivery_contract import canonical_snapshot
else:
    from delivery_contract import canonical_snapshot


def _identifier(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and len(value) <= 512 and '*' not in value
            and not any(unicodedata.category(c).startswith('C') for c in value))


def match_create_receipt(response: Any, *, integration_id: str) -> dict[str, str] | None:
    """Match a documented create response; acceptance does not prove publication.

    Pure offline parsing only. Missing or ambiguous evidence returns None; the
    caller must reconcile without automatically sending again. This does not
    establish instance identity, source authority, approval, or API version.
    """
    if not _identifier(integration_id) or not isinstance(response, list):
        return None
    if len(response) > 1000:
        return None
    matches = []
    for item in response:
        if not isinstance(item, dict) or not _identifier(item.get('integration')) or not _identifier(item.get('postId')):
            return None
        if item['integration'] == integration_id:
            matches.append(item['postId'])
    if len(matches) != 1 or sum(item['postId'] == matches[0] for item in response) != 1:
        return None
    return {'state': 'accepted', 'remote_job_id': matches[0], 'integration_id': integration_id}


def interpret_tiktok_status(posting_method: Any, provider_status: Any) -> str:
    """Interpret the documented inbox-only success without claiming publication.

    Caller must independently bind the observation to the same integration,
    post, instance and approved snapshot. This helper performs no I/O.
    """
    if posting_method == 'UPLOAD' and provider_status in ('PUBLISHED', 'published'):
        return 'awaiting_creator'
    return 'unknown'


def inspect_postiz_list_response(response: Any, *, remote_job_id: Any, integration_id: Any,
                                 expected_posting_method: Any = None) -> str:
    """Inspect a list response without inferring success from missing evidence.

    The caller must bind the response to the intended Postiz instance and
    approved snapshot; this parser neither fetches nor authenticates it.
    PUBLISHED remains unknown unless it is a matched TikTok inbox handoff.
    """
    if (not _identifier(remote_job_id) or not _identifier(integration_id)
            or not isinstance(response, dict) or not isinstance(response.get('posts'), list)
            or len(response['posts']) > 10_000):
        return 'unknown'
    matches = []
    for item in response['posts']:
        if not isinstance(item, dict):
            return 'unknown'
        if item.get('id') == remote_job_id:
            matches.append(item)
    if len(matches) != 1:
        return 'unknown'
    item = matches[0]
    if item.get('error') not in (None, ''):
        return 'unknown'
    integration = item.get('integration')
    if not isinstance(integration, dict) or integration.get('id') != integration_id:
        return 'unknown'
    if expected_posting_method is not None:
        settings = item.get('settings')
        if (expected_posting_method not in ('DIRECT_POST', 'UPLOAD')
                or integration.get('providerIdentifier') != 'tiktok'
                or not isinstance(settings, dict)
                or ('__type' in settings and settings['__type'] != 'tiktok')
                or settings.get('content_posting_method') != expected_posting_method):
            return 'unknown'
    state = item.get('state')
    if state == 'QUEUE':
        return 'accepted'
    if state == 'PUBLISHED' and expected_posting_method == 'UPLOAD':
        return 'awaiting_creator'
    return 'unknown'


def build_postiz_create_candidate(*, integration_id: str, provider: str, content: str,
                                  uploaded_media: list[dict[str, str]], mode: str,
                                  date_utc: str, settings: dict[str, Any],
                                  first_comment: str | None = None) -> dict[str, Any]:
    """Build one target only; caller must establish gates, owner and provenance.

    Media entries are caller-supplied ``id``, ``path`` and ``kind`` (image/video)
    from a separately verified Postiz upload. This function does not upload,
    inspect bytes, verify the provider or perform any I/O. A candidate is not
    proof of platform capability or permission to send. Discord and Threads are
    restricted to text-only candidates pending account-specific verification.
    TikTok UPLOAD is an inbox handoff; its privacy and disclosure fields may be
    ignored by TikTok and it must not be interpreted as a published post.
    """
    try:
        uploaded_media = copy.deepcopy(uploaded_media)
        settings = copy.deepcopy(settings)
    except (TypeError, ValueError, RuntimeError, RecursionError):
        raise ValueError('invalid Postiz candidate') from None
    if (not _identifier(integration_id) or not isinstance(provider, str)
            or provider not in {'facebook', 'youtube', 'linkedin', 'linkedin-page', 'discord', 'threads',
                                'instagram', 'instagram-standalone', 'tiktok', 'x'}
            or not isinstance(content, str) or not content.strip() or len(content) > 1_000_000
            or '{{' in content or '}}' in content or not isinstance(mode, str)
            or mode not in {'now', 'schedule', 'draft'}
            or not isinstance(date_utc, str) or len(date_utc) > 40
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)', date_utc)
            or not isinstance(settings, dict) or not isinstance(uploaded_media, list)):
        raise ValueError('invalid Postiz candidate')
    if len(uploaded_media) > 100:
        raise ValueError('too many Postiz candidate media')
    try:
        settings_bytes, _ = canonical_snapshot({'settings': settings})
        if len(settings_bytes) > 65536:
            raise ValueError('oversized settings')
    except (TypeError, ValueError, RecursionError):
        raise ValueError('invalid Postiz candidate settings') from None
    try:
        dt = datetime.fromisoformat(date_utc.replace('Z', '+00:00'))
        if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(dt):
            raise ValueError('not UTC')
    except (ValueError, OverflowError):
        raise ValueError('invalid Postiz candidate date') from None
    if first_comment is not None and (not isinstance(first_comment, str) or not first_comment.strip()
                                      or len(first_comment) > 1_000_000
                                      or '{{' in first_comment or '}}' in first_comment):
        raise ValueError('invalid Postiz candidate comment')
    if provider == 'youtube' and first_comment is not None:
        raise ValueError('YouTube extra post parts are not supported')
    media = []
    for item in uploaded_media:
        if (not isinstance(item, dict) or set(item) != {'id', 'path', 'kind'}
                or not _identifier(item['id']) or not isinstance(item['path'], str)
                or not item['path'].strip() or item['path'] != item['path'].strip()
                or len(item['path']) > 4096 or any(c.isspace() or unicodedata.category(c).startswith('C')
                                                   for c in item['path'])
                or not isinstance(item['kind'], str) or item['kind'] not in {'image', 'video'}):
            raise ValueError('invalid Postiz candidate media')
        try:
            location = urlsplit(item['path'])
            if (location.query or location.fragment or location.username is not None or location.password is not None
                    or location.scheme not in {'', 'http', 'https'}
                    or (location.scheme and not location.hostname)
                    or (not location.scheme and location.netloc)):
                raise ValueError('invalid location')
            _ = location.port
        except ValueError:
            raise ValueError('invalid Postiz candidate media') from None
        media.append({'id': item['id'], 'path': item['path']})
    kinds = [item['kind'] for item in uploaded_media]
    if provider == 'youtube' and kinds != ['video']:
        raise ValueError('YouTube requires one video')
    if provider in {'facebook', 'linkedin', 'linkedin-page'} and 'video' in kinds and len(kinds) != 1:
        raise ValueError('video must be the only attachment')
    if settings.get('__type') != provider:
        raise ValueError('provider settings do not match target')
    if provider == 'discord':
        channel = settings.get('channel')
        if (not isinstance(channel, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', channel)
                or not 0 < int(channel) <= 18446744073709551615):
            raise ValueError('invalid Discord channel')
        if len(content) > 2000 or '@' in content or first_comment is not None or uploaded_media:
            raise ValueError('unsupported Discord candidate')
    if provider == 'threads' and (uploaded_media or first_comment is not None
                                  or len(content) > 500 or set(settings) != {'__type'}):
        raise ValueError('unsupported Threads candidate')
    if provider == 'x':
        allowed = {'__type', 'who_can_reply_post', 'post_type', 'made_with_ai', 'paid_partnership'}
        if (uploaded_media or first_comment is not None or settings.keys() - allowed
                or settings.get('post_type', 'post') != 'post'
                or settings.get('who_can_reply_post') not in ('everyone', 'following', 'mentionedUsers',
                                                               'subscribers', 'verified')
                or any(field in settings and type(settings[field]) is not bool
                       for field in ('made_with_ai', 'paid_partnership'))):
            raise ValueError('unsupported X candidate')
    if provider in {'instagram', 'instagram-standalone'}:
        if (kinds != ['image'] or first_comment is not None or len(content) > 2200
                or set(settings) != {'__type', 'post_type'} or settings.get('post_type') != 'post'):
            raise ValueError('unsupported Instagram candidate')
    if provider == 'tiktok':
        required = {'__type', 'title', 'privacy_level', 'duet', 'stitch', 'comment', 'autoAddMusic',
                    'brand_content_toggle', 'brand_organic_toggle', 'content_posting_method'}
        optional = {'video_made_with_ai'}
        boolean_fields = {'duet', 'stitch', 'comment', 'brand_content_toggle', 'brand_organic_toggle'}
        if (kinds != ['video'] or first_comment is not None or not required <= settings.keys()
                or settings.keys() - required - optional
                or not isinstance(settings.get('title'), str) or len(settings['title']) > 90
                or settings.get('privacy_level') not in ('PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS',
                                                         'FOLLOWER_OF_CREATOR', 'SELF_ONLY')
                or settings.get('content_posting_method') not in ('DIRECT_POST', 'UPLOAD')
                or settings.get('autoAddMusic') != 'no'
                or any(type(settings.get(field)) is not bool for field in boolean_fields)
                or (settings.get('content_posting_method') == 'DIRECT_POST'
                    and settings.get('brand_content_toggle') is True
                    and settings.get('privacy_level') not in ('PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS'))
                or ('video_made_with_ai' in settings and type(settings['video_made_with_ai']) is not bool)):
            raise ValueError('unsupported TikTok candidate')
    if provider == 'youtube':
        title = settings.get('title')
        visibility = settings.get('type')
        if (not isinstance(title, str) or title != title.strip() or not 2 <= len(title) <= 100
                or not isinstance(visibility, str) or visibility not in {'public', 'unlisted', 'private'}):
            raise ValueError('invalid YouTube settings')
    if provider in {'linkedin', 'linkedin-page'} and 'post_as_images_carousel' in settings:
        carousel = settings['post_as_images_carousel']
        if type(carousel) is not bool or (carousel and (len(kinds) < 2 or any(k != 'image' for k in kinds))):
            raise ValueError('invalid LinkedIn carousel')
    values = [{'content': content, 'image': media}]
    if first_comment is not None:
        values.append({'content': first_comment, 'image': []})
    candidate = {'type': mode, 'date': date_utc, 'shortLink': False, 'tags': [],
                 'posts': [{'integration': {'id': integration_id}, 'value': values,
                            'settings': settings}]}
    try:
        canonical_snapshot(candidate)
    except (TypeError, ValueError, RecursionError):
        raise ValueError('invalid Postiz candidate data') from None
    return candidate


def build_postiz_batch_preview(requests: Any) -> list[dict[str, Any]]:
    """Prepare a bounded collection of independent candidates entirely in memory.

    References are caller labels only, not durable delivery identities or
    approval evidence. The caller must bind each target and schedule to the
    existing authorization and delivery ledger before any external action.
    """
    if not isinstance(requests, list) or not 1 <= len(requests) <= 100:
        raise ValueError('invalid batch preview')
    # Walk before deepcopy or JSON serialization, bounding nested input too.
    remaining = 2_000_000
    pending = [requests]
    visited_nodes = 0
    while pending:
        value = pending.pop()
        visited_nodes += 1
        if visited_nodes > 20_000:
            raise ValueError('batch preview too large')
        if isinstance(value, str):
            if len(value) > remaining:
                raise ValueError('batch preview too large')
            try:
                remaining -= len(value.encode('utf-8'))
            except UnicodeError:
                raise ValueError('invalid batch preview') from None
            if remaining < 0:
                raise ValueError('batch preview too large')
        elif isinstance(value, dict):
            if (visited_nodes + len(pending) + 2 * len(value) > 20_000
                    or any(not isinstance(key, str) for key in value)):
                raise ValueError('invalid batch preview')
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            if visited_nodes + len(pending) + len(value) > 20_000:
                raise ValueError('batch preview too large')
            pending.extend(value)
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise ValueError('invalid batch preview')
    required = {'ref', 'integration_id', 'provider', 'content', 'uploaded_media',
                'mode', 'date_utc', 'settings'}
    allowed = required | {'first_comment'}
    seen = set()
    results = []
    for request in requests:
        if (not isinstance(request, dict) or not required <= request.keys()
                or request.keys() - allowed or not _identifier(request.get('ref'))
                or request['ref'] in seen):
            raise ValueError('invalid batch preview')
        seen.add(request['ref'])
        candidate = build_postiz_create_candidate(**{key: value for key, value in request.items() if key != 'ref'})
        warnings = ['preview_not_authorized_or_provider_verified']
        if request['provider'] == 'x':
            warnings.append('x_weighted_length_unchecked')
        if request['provider'] == 'tiktok' and request['settings']['content_posting_method'] == 'UPLOAD':
            warnings.append('tiktok_upload_awaits_creator_and_ignores_settings')
        results.append({'ref': request['ref'], 'candidate': candidate, 'warnings': warnings})
    return results
