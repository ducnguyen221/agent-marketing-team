"""Native TikTok video request previews only: no secrets, media or network."""
from __future__ import annotations

from typing import Any
import copy
import hashlib
import json
import re
import unicodedata

# Conservative byte interpretation of documented MB boundaries; no upload is performed.
_MIN_CHUNK = 5 * 1024 * 1024
_MAX_CHUNK = 64 * 1000 * 1000
_MAX_FINAL = 128 * 1000 * 1000


def preview_file_chunks(*, video_size: int, chunk_size: int) -> dict[str, Any]:
    """Calculate inclusive sequential ranges; final part absorbs the remainder."""
    if (type(video_size) is not int or type(chunk_size) is not int or video_size < 1 or chunk_size < 1
            or chunk_size > video_size or chunk_size > _MAX_CHUNK):
        raise ValueError('invalid TikTok fixture sizes')
    if video_size < _MIN_CHUNK and chunk_size != video_size:
        raise ValueError('small video must use a single chunk')
    if video_size >= _MIN_CHUNK and chunk_size < _MIN_CHUNK:
        raise ValueError('chunk below conservative minimum')
    count = video_size // chunk_size
    if count < 1 or count > 1000 or (video_size > _MAX_CHUNK and count < 2):
        raise ValueError('invalid TikTok chunk count')
    ranges = []
    for index in range(count):
        start = index * chunk_size
        end = (video_size - 1) if index == count - 1 else (start + chunk_size - 1)
        if end - start + 1 > _MAX_FINAL:
            raise ValueError('final TikTok chunk too large')
        ranges.append({'start': start, 'end': end, 'length': end - start + 1})
    return {'source_info': {'source': 'FILE_UPLOAD', 'video_size': video_size,
                            'chunk_size': chunk_size, 'total_chunk_count': count},
            'chunks': ranges, 'fixture_only': True}


def preview_inbox_upload(*, video_size: int, chunk_size: int) -> dict[str, Any]:
    """Describe inbox initialization, never upload or publish."""
    transfer = preview_file_chunks(video_size=video_size, chunk_size=chunk_size)
    return {'preview_only': True, 'request': {'method': 'POST',
            'path': '/v2/post/publish/inbox/video/init/', 'body': {'source_info': transfer['source_info']}},
            'chunks': transfer['chunks'], 'warnings': ['not_authorized', 'creator_action_required_if_delivered',
                'media_not_read_or_uploaded', 'limits_and_account_unverified', 'total_size_platform_limit_unverified']}


def fixture_consent_digest(*, video_size: int, chunk_size: int, duration_sec: int,
                           creator: dict[str, Any], post_info: dict[str, Any],
                           media_sha256_fixture: str) -> str:
    """Hash caller-supplied fixture data, not proof of consent or media bytes."""
    if not isinstance(media_sha256_fixture, str) or not re.fullmatch(r'[0-9a-f]{64}', media_sha256_fixture):
        raise ValueError('invalid fixture media digest')
    try:
        raw = json.dumps({'video_size': video_size, 'chunk_size': chunk_size, 'duration_sec': duration_sec,
                          'creator': creator, 'post_info': post_info, 'media_sha256_fixture': media_sha256_fixture},
                         sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValueError('invalid consent fixture') from None
    if len(raw) > 32768:
        raise ValueError('invalid consent fixture')
    return hashlib.sha256(raw).hexdigest()


def preview_direct_post(*, video_size: int, chunk_size: int, duration_sec: int,
                        creator: dict[str, Any], expected_creator: str, expected_revision: str,
                        consent_fixture: bool, post_info: dict[str, Any], media_sha256_fixture: str,
                        consent_digest_fixture: str) -> dict[str, Any]:
    """Describe Direct Post with synthetic creator info, never grant authority."""
    creator = copy.deepcopy(creator)
    post_info = copy.deepcopy(post_info)
    creator_keys = {'fixture_only', 'fixture_creator_id', 'fixture_revision', 'privacy_level_options', 'comment_disabled', 'duet_disabled',
                    'stitch_disabled', 'max_video_post_duration_sec'}
    post_keys = {'title', 'privacy_level', 'disable_comment', 'disable_duet', 'disable_stitch',
                 'brand_content_toggle', 'brand_organic_toggle'}
    privacy = {'PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY'}
    if (consent_fixture is not True or not isinstance(creator, dict) or set(creator) != creator_keys
            or creator['fixture_only'] is not True or not isinstance(post_info, dict) or set(post_info) != post_keys
            or not isinstance(expected_creator, str) or not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,100}', expected_creator)
            or not isinstance(expected_revision, str) or not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,100}', expected_revision)
            or creator['fixture_creator_id'] != expected_creator or creator['fixture_revision'] != expected_revision
            or not isinstance(creator['privacy_level_options'], list) or not creator['privacy_level_options']
            or any(not isinstance(p, str) or p not in privacy for p in creator['privacy_level_options'])
            or len(set(creator['privacy_level_options'])) != len(creator['privacy_level_options'])
            or post_info['privacy_level'] not in creator['privacy_level_options']
            or type(duration_sec) is not int or type(creator['max_video_post_duration_sec']) is not int
            or duration_sec < 1 or duration_sec > creator['max_video_post_duration_sec']
            or any(type(creator[field]) is not bool for field in ('comment_disabled', 'duet_disabled', 'stitch_disabled'))
            or any(type(post_info[field]) is not bool for field in ('disable_comment', 'disable_duet', 'disable_stitch',
                                                                      'brand_content_toggle', 'brand_organic_toggle'))):
        raise ValueError('invalid TikTok creator fixture')
    if post_info['brand_content_toggle'] and post_info['privacy_level'] == 'SELF_ONLY':
        raise ValueError('invalid branded content privacy')
    for feature in ('comment', 'duet', 'stitch'):
        if creator[feature + '_disabled'] and not post_info['disable_' + feature]:
            raise ValueError('creator interaction disabled')
    title = post_info['title']
    if (not isinstance(title, str) or '{{' in title or '}}' in title
            or any(unicodedata.category(c).startswith('C') and c not in '\n\t\u200d' for c in title)):
        raise ValueError('invalid TikTok title')
    try:
        if len(title.encode('utf-16-le')) // 2 > 2200:
            raise ValueError('invalid TikTok title')
    except UnicodeError:
        raise ValueError('invalid TikTok title') from None
    transfer = preview_file_chunks(video_size=video_size, chunk_size=chunk_size)
    digest = fixture_consent_digest(video_size=video_size, chunk_size=chunk_size, duration_sec=duration_sec,
                                    creator=creator, post_info=post_info, media_sha256_fixture=media_sha256_fixture)
    if not isinstance(consent_digest_fixture, str) or consent_digest_fixture != digest:
        raise ValueError('fixture consent snapshot mismatch')
    return {'preview_only': True, 'request': {'method': 'POST', 'path': '/v2/post/publish/video/init/',
            'body': {'post_info': post_info, 'source_info': transfer['source_info']}}, 'chunks': transfer['chunks'],
            'warnings': ['not_authorized', 'would_post_if_sent', 'creator_and_consent_are_fixture_only',
                         'creator_and_revision_not_authenticated', 'media_not_read_or_uploaded',
                         'media_digest_caller_supplied', 'app_audit_and_policy_unverified', 'duration_unverified',
                         'total_size_platform_limit_unverified', 'ai_label_not_supported'], 'consent_digest_fixture': digest}


def observe_status(*, mode: str, expected_publish_id: str, observed_publish_id: str,
                   http_status: int, body: Any) -> dict[str, Any]:
    """Interpret a caller-supplied fixture; it is not authenticated evidence."""
    result = {'state': 'unknown', 'visibility': 'unverified', 'authenticated': False}
    if (type(http_status) is not int or http_status != 200 or mode not in ('DIRECT', 'INBOX') or not isinstance(expected_publish_id, str)
            or not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,100}', expected_publish_id)
            or observed_publish_id != expected_publish_id or not isinstance(body, dict)
            or not isinstance(body.get('error'), dict) or body['error'].get('code') != 'ok'
            or not isinstance(body.get('data'), dict)):
        return result
    status = body['data'].get('status')
    if status != 'FAILED' and body['data'].get('fail_reason') not in (None, ''):
        return result
    if status == 'PROCESSING_UPLOAD':
        result['state'] = 'processing'
    elif status == 'SEND_TO_USER_INBOX' and mode == 'INBOX':
        result['state'] = 'awaiting_creator'
    elif status == 'PUBLISH_COMPLETE':
        result['state'] = 'provider_reports_published'
    elif status == 'FAILED':
        result['state'] = 'provider_reports_failed'
    return result
