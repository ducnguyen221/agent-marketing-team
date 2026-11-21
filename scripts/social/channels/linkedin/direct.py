"""LinkedIn native request previews and receipt parsing; no network or secrets.

Contract informed by LinkedIn Posts API; preview is not approval, upload or
proof of capability. A future transport must enforce gates and bind the owner.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

_AUTHOR = re.compile(r'urn:li:(?:organization:[0-9]{1,32}|person:[A-Za-z0-9_-]{1,128})\Z')
_MEDIA = {'image': re.compile(r'urn:li:image:[A-Za-z0-9_-]{1,128}\Z'),
          'video': re.compile(r'urn:li:video:[A-Za-z0-9_-]{1,128}\Z')}
_POST = re.compile(r'urn:li:(?:share|ugcPost):[0-9]{1,32}\Z')
_RESERVED = frozenset('\\|{}@[]()<>#*_~')


def interpret_userinfo(status: int, body: Any, *, expected_author: str) -> dict[str, Any]:
    """Compare a LinkedIn userinfo subject; never infer posting permission."""
    person = re.compile(r'urn:li:person:([A-Za-z0-9_-]{1,128})\Z')
    expected = person.fullmatch(expected_author) if isinstance(expected_author, str) else None
    if expected is None:
        raise ValueError('invalid person author')
    result = {'identity': 'unknown', 'app_binding_verified': False, 'publish_authorized': False}
    if type(status) is not int or status != 200 or not isinstance(body, dict):
        return result
    subject = body.get('sub')
    if not isinstance(subject, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', subject):
        return result
    result['identity'] = 'match' if subject == expected.group(1) else 'mismatch'
    return result


def preview_post(*, author: str, text: str, api_version: str,
                 media_kind: str | None = None, media_urn: str | None = None) -> dict[str, Any]:
    """Build one native LinkedIn candidate; never submit or load credentials."""
    if isinstance(text, str):
        text = text.replace('\r\n', '\n')
    if (not isinstance(author, str) or not _AUTHOR.fullmatch(author)
            or not isinstance(api_version, str) or not re.fullmatch(r'[0-9]{6}', api_version)
            or not 1 <= int(api_version[4:]) <= 12
            or not isinstance(text, str) or not text.strip() or len(text) > 20_000
            or not any(not char.isspace() and unicodedata.category(char)[0] not in 'CM' for char in text)
            or '{{' in text or '}}' in text
            or any(unicodedata.category(char).startswith('C') and char not in '\n\t\u200d' for char in text)):
        raise ValueError('invalid LinkedIn preview')
    try:
        text.encode('utf-8')
    except UnicodeError:
        raise ValueError('invalid LinkedIn preview') from None
    if media_kind is None:
        if media_urn is not None:
            raise ValueError('unexpected LinkedIn media')
    elif (not isinstance(media_kind, str) or media_kind not in _MEDIA
          or not isinstance(media_urn, str) or not _MEDIA[media_kind].fullmatch(media_urn)):
        raise ValueError('invalid LinkedIn media')
    commentary = ''.join('\\' + char if char in _RESERVED else char for char in text)
    body = {'author': author, 'commentary': commentary, 'visibility': 'PUBLIC',
            'distribution': {'feedDistribution': 'MAIN_FEED', 'targetEntities': [],
                             'thirdPartyDistributionChannels': []},
            'lifecycleState': 'PUBLISHED', 'isReshareDisabledByAuthor': False}
    if media_kind is not None:
        body['content'] = {'media': {'id': media_urn}}
    return {'preview_only': True,
            'request': {'method': 'POST', 'path': '/rest/posts',
                        'headers': {'Linkedin-Version': api_version, 'X-Restli-Protocol-Version': '2.0.0',
                                    'Content-Type': 'application/json'}, 'body': body},
            'warnings': ['not_authorized', 'would_publish_if_sent', 'api_version_unverified',
                         'media_ownership_and_readiness_unverified', 'length_unverified',
                         'mentions_and_hashtags_as_plaintext']}


def interpret_create(status: int | None, headers: list[tuple[str, str]]) -> dict[str, str]:
    """A valid 201 ID is an accepted create, not proof of visible publication."""
    unknown = {'state': 'unknown', 'post_urn': '', 'readback': 'unverified'}
    if type(status) is not int or status != 201 or not isinstance(headers, list) or len(headers) > 100:
        return unknown
    if any(not isinstance(pair, tuple) or len(pair) != 2
           or not isinstance(pair[0], str) or not isinstance(pair[1], str) for pair in headers):
        return unknown
    ids = [value for name, value in headers if name.lower() == 'x-restli-id']
    if len(ids) != 1 or not _POST.fullmatch(ids[0]):
        return unknown
    return {'state': 'accepted', 'post_urn': ids[0], 'readback': 'unverified'}


def observe_post(receipt: dict[str, str], status: int | None, body: Any, *,
                 expected_author: str) -> dict[str, str]:
    """Inspect an offline readback without losing a prior accepted receipt.

    Matching data only means the provider reports this state; the caller must
    separately authenticate the response, author binding and delivery attempt.
    """
    if (not isinstance(receipt, dict)
            or not {'state', 'post_urn', 'readback'} <= set(receipt)
            or set(receipt) - {'state', 'post_urn', 'readback', 'previously_reported_published'}
            or receipt['state'] != 'accepted' or receipt['readback'] not in ('unverified', 'provider_reports_published')
            or type(receipt.get('previously_reported_published', False)) is not bool
            or (receipt['readback'] == 'provider_reports_published'
                and receipt.get('previously_reported_published') is not True)
            or not isinstance(receipt['post_urn'], str) or not _POST.fullmatch(receipt['post_urn'])
            or not isinstance(expected_author, str) or not _AUTHOR.fullmatch(expected_author)):
        raise ValueError('invalid LinkedIn receipt')
    result = {**receipt, 'readback': 'unverified',
              'previously_reported_published': receipt.get('previously_reported_published', False)}
    if (type(status) is int and status == 200 and isinstance(body, dict)
            and body.get('id') == receipt['post_urn'] and body.get('author') == expected_author
            and body.get('lifecycleState') == 'PUBLISHED' and body.get('visibility') == 'PUBLIC'):
        result['readback'] = 'provider_reports_published'
        result['previously_reported_published'] = True
    return result


def preview_marketing_anchor(*, source: str, anchor: str, author: str, api_version: str,
                             media_kind: str | None = None, media_urn: str | None = None) -> dict[str, Any]:
    """Read a synthetic extension anchor; LinkedIn is not a V1 post-format enum."""
    from markdown_it import MarkdownIt
    from scripts.lib.delivery_anchors import extract_delivery_anchor
    if not isinstance(anchor, str) or not re.fullmatch(r'post:linkedin_post(?:#[1-9][0-9]*)?', anchor):
        raise ValueError('invalid LinkedIn anchor')
    text = extract_delivery_anchor(source, anchor)
    env: dict[str, Any] = {}
    tokens = MarkdownIt('commonmark', {'html': True}).parse(text, env)
    if env.get('references') or any(token.type in {'heading_open', 'html_block', 'blockquote_open', 'fence', 'code_block'}
           or any(child.type == 'html_inline' for child in (token.children or [])) for token in tokens):
        raise ValueError('ambiguous LinkedIn anchor')
    text = text.removesuffix('\n').removesuffix('\r')
    result = preview_post(author=author, text=text, api_version=api_version,
                          media_kind=media_kind, media_urn=media_urn)
    result['source_anchor'] = anchor
    result['warnings'].append('synthetic_anchor_not_v1_enum')
    return result
