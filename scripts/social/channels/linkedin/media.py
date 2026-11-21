"""LinkedIn-native media planning only: no file, network, credentials or upload.

Signed upload URLs and real upload tokens are never accepted or returned by
these helpers. Provider observations are caller-supplied and unauthenticated.
"""
from __future__ import annotations

import re
import hashlib
import json
from typing import Any

from scripts.social.channels.linkedin.direct import _AUTHOR, _MEDIA


def _headers(api_version: str) -> dict[str, str]:
    if (not isinstance(api_version, str) or not re.fullmatch(r'[0-9]{6}', api_version)
            or not 1 <= int(api_version[4:]) <= 12):
        raise ValueError('invalid API version')
    return {'Linkedin-Version': api_version, 'X-Restli-Protocol-Version': '2.0.0',
            'Content-Type': 'application/json'}


def preview_initialize(*, kind: str, owner: str, api_version: str,
                       file_size: int | None = None) -> dict[str, Any]:
    """Create an upload-init candidate; this call does not contact LinkedIn."""
    if not isinstance(owner, str) or not _AUTHOR.fullmatch(owner) or kind not in ('image', 'video'):
        raise ValueError('invalid media initialization')
    data: dict[str, Any] = {'owner': owner}
    if kind == 'image':
        if file_size is not None:
            raise ValueError('unexpected image size')
    else:
        if type(file_size) is not int or not 1 <= file_size <= 5_000_000_000:
            raise ValueError('invalid video size')
        data.update(fileSizeBytes=file_size, uploadCaptions=False, uploadThumbnail=False)
    return {'preview_only': True,
            'request': {'method': 'POST', 'path': f'/rest/{kind}s?action=initializeUpload',
                        'headers': _headers(api_version), 'body': {'initializeUploadRequest': data}},
            'warnings': ['not_authorized', 'would_initialize_upload_if_sent', 'api_version_unverified',
                         'file_format_size_and_owner_unverified']}


def video_ranges(*, file_size: int, instructions: list[dict[str, int]]) -> list[dict[str, int]]:
    """Validate sanitized inclusive ranges and clamp the last part to EOF.

    Input contains byte offsets only, no upload URLs or tokens. This does not
    prove the response is authentic, unexpired or belongs to the expected file.
    """
    if (type(file_size) is not int or not 1 <= file_size <= 5_000_000_000
            or not isinstance(instructions, list) or not 1 <= len(instructions) <= 2000):
        raise ValueError('invalid video instructions')
    result = []
    expected = 0
    for index, instruction in enumerate(instructions):
        if (not isinstance(instruction, dict) or set(instruction) != {'firstByte', 'lastByte'}
                or type(instruction['firstByte']) is not int or type(instruction['lastByte']) is not int):
            raise ValueError('invalid video range')
        start, last = instruction['firstByte'], instruction['lastByte']
        if start != expected or start >= file_size or last < start or last > 2**63 - 1:
            raise ValueError('invalid video range')
        end = min(last, file_size - 1)
        result.append({'index': index, 'start': start, 'end': end, 'length': end - start + 1})
        expected = end + 1
    if expected != file_size:
        raise ValueError('incomplete video ranges')
    return result


def video_fixture_session(*, owner: str, video_urn: str, session_id: str, file_size: int,
                          instructions: list[dict[str, int]], expires_at_ms: int,
                          file_sha256: str, upload_token: str) -> dict[str, Any]:
    """Build an in-memory synthetic session; no provider data is authenticated."""
    if (not isinstance(owner, str) or not _AUTHOR.fullmatch(owner)
            or not isinstance(video_urn, str) or not video_urn.startswith('urn:li:video:fixture-')
            or not _MEDIA['video'].fullmatch(video_urn) or not isinstance(session_id, str)
            or not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,128}', session_id)
            or type(expires_at_ms) is not int or expires_at_ms <= 0
            or not isinstance(file_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', file_sha256)
            or not isinstance(upload_token, str)
            or (upload_token != '' and not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,128}', upload_token))):
        raise ValueError('invalid fixture session')
    result = {'owner': owner, 'video_urn': video_urn, 'session_id': session_id, 'file_size': file_size,
              'expires_at_ms': expires_at_ms, 'file_sha256': file_sha256,
              'ranges': video_ranges(file_size=file_size, instructions=instructions)}
    canonical = json.dumps({'session': result, 'upload_token': upload_token}, sort_keys=True,
                           separators=(',', ':')).encode('utf-8')
    result['session_digest'] = hashlib.sha256(canonical).hexdigest()
    return result


def preview_fixture_finalize(*, session: dict[str, Any], api_version: str,
                             completed: list[dict[str, Any]], upload_token: str,
                             now_ms: int) -> dict[str, Any]:
    """Order synthetic part receipts tied to one unexpired fixture session."""
    required = {'owner', 'video_urn', 'session_id', 'file_size', 'expires_at_ms', 'file_sha256', 'ranges',
                'session_digest'}
    if (not isinstance(session, dict) or set(session) != required or not isinstance(session['ranges'], list)
            or not 1 <= len(session['ranges']) <= 2000 or type(now_ms) is not int or now_ms < 0
            or type(session['expires_at_ms']) is not int or now_ms >= session['expires_at_ms']
            or not isinstance(completed, list) or len(completed) != len(session['ranges'])
            or not isinstance(upload_token, str)
            or (upload_token != '' and not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,128}', upload_token))):
        raise ValueError('invalid finalize fixture')
    ranges = session['ranges']
    try:
        instructions = [{'firstByte': part['start'], 'lastByte': part['end']} for part in ranges]
        checked = video_fixture_session(owner=session['owner'], video_urn=session['video_urn'],
                                        session_id=session['session_id'], file_size=session['file_size'],
                                        instructions=instructions, expires_at_ms=session['expires_at_ms'],
                                        file_sha256=session['file_sha256'], upload_token=upload_token)
    except (KeyError, TypeError, ValueError):
        raise ValueError('invalid fixture session') from None
    if checked != session:
        raise ValueError('invalid fixture ranges')
    indexed: dict[int, str] = {}
    fields = {'session_id', 'video_urn', 'owner', 'file_sha256', 'session_digest', 'index', 'start', 'end', 'etag'}
    for item in completed:
        if (not isinstance(item, dict) or set(item) != fields or type(item['index']) is not int
                or item['index'] < 0 or item['index'] >= len(ranges) or item['index'] in indexed
                or any(item[key] != session[key] for key in ('session_id', 'video_urn', 'owner', 'file_sha256',
                                                             'session_digest'))
                or type(item['start']) is not int or type(item['end']) is not int
                or item['start'] != ranges[item['index']]['start'] or item['end'] != ranges[item['index']]['end']
                or not isinstance(item['etag'], str)):
            raise ValueError('invalid fixture part')
        etag = item['etag']
        if len(etag) >= 2 and etag[0] == etag[-1] == '"':
            etag = etag[1:-1]
        if not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,128}', etag):
            raise ValueError('invalid fixture part')
        indexed[item['index']] = etag
    return {'preview_only': True,
            'request': {'method': 'POST', 'path': '/rest/videos?action=finalizeUpload',
                        'headers': _headers(api_version),
                        'body': {'finalizeUploadRequest': {'video': session['video_urn'], 'uploadToken': upload_token,
                                  'uploadedPartIds': [indexed[index] for index in range(len(ranges))]}}},
            'warnings': ['synthetic_only', 'not_authorized', 'not_uploaded', 'finalize_does_not_mean_available']}


def inspect_media(*, status: int | None, body: Any, expected_urn: str, expected_owner: str) -> dict[str, Any]:
    """Interpret one unauthenticated observation without asserting readiness."""
    if (not isinstance(expected_urn, str) or not any(pattern.fullmatch(expected_urn) for pattern in _MEDIA.values())
            or not isinstance(expected_owner, str) or not _AUTHOR.fullmatch(expected_owner)):
        raise ValueError('invalid expected media identity')
    state = 'unverified'
    if (type(status) is int and status == 200 and isinstance(body, dict)
            and body.get('id') == expected_urn and body.get('owner') == expected_owner
            and isinstance(body.get('status'), str)
            and (body['status'] == 'PROCESSING_FAILED' or body.get('processingFailureReason') in (None, ''))):
        state = {'AVAILABLE': 'provider_reports_available', 'WAITING_UPLOAD': 'provider_reports_waiting_upload',
                 'PROCESSING': 'provider_reports_processing',
                 'PROCESSING_FAILED': 'provider_reports_processing_failed'}.get(body.get('status'), 'unverified')
    return {'state': state, 'authenticated': False}


def preview_fixture_media_post(*, owner: str, text: str, api_version: str, media_kind: str,
                               media_urn: str, status: int | None, observation: dict[str, Any]) -> dict[str, Any]:
    """Build a native post after matching an unauthenticated fixture observation."""
    from scripts.social.channels.linkedin.direct import preview_post
    if (not isinstance(media_kind, str) or media_kind not in _MEDIA or not isinstance(media_urn, str)
            or not media_urn.startswith(f'urn:li:{media_kind}:fixture-')):
        raise ValueError('fixture media required')
    state = inspect_media(status=status, body=observation, expected_urn=media_urn, expected_owner=owner)
    if state['state'] != 'provider_reports_available':
        raise ValueError('fixture media is not available')
    result = preview_post(author=owner, text=text, api_version=api_version,
                          media_kind=media_kind, media_urn=media_urn)
    result['warnings'].append('fixture_observation_not_authenticated')
    return result
