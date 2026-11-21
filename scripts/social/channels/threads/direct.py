"""Threads native request previews: no network, credentials or publication."""
from __future__ import annotations

import ipaddress
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit

_ID = re.compile(r'[0-9]{1,32}\Z')
_VERSION = re.compile(r'v[0-9]{1,3}\.[0-9]{1,3}\Z')


def _endpoint(user_id: str, api_version: str, operation: str) -> str:
    if (not isinstance(user_id, str) or not _ID.fullmatch(user_id)
            or not isinstance(api_version, str) or not _VERSION.fullmatch(api_version)):
        raise ValueError('invalid Threads destination')
    return f'/{api_version}/{user_id}/{operation}'


def _media_url(value: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or any(ord(ch) <= 32 or ord(ch) == 127 for ch in value) or '\\' in value):
        raise ValueError('invalid Threads media URL')
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None
                or url.port not in (None, 443) or url.query or url.fragment
                or url.hostname.lower() in ('localhost', 'localhost.localdomain')
                or url.hostname.lower().endswith('.localhost')):
            raise ValueError('invalid Threads media URL')
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError('invalid Threads media URL')
    except ValueError:
        raise ValueError('invalid Threads media URL') from None
    return value


def preview_container(*, user_id: str, api_version: str, media_type: str,
                      text: str = '', media_url: str | None = None) -> dict[str, Any]:
    """Construct a single native container candidate, without sending it."""
    path = _endpoint(user_id, api_version, 'threads')
    if isinstance(text, str):
        text = text.replace('\r\n', '\n')
    if (media_type not in ('TEXT', 'IMAGE', 'VIDEO') or not isinstance(text, str) or len(text) > 20000
            or '{{' in text or '}}' in text
            or any(unicodedata.category(c).startswith('C') and c not in '\n\t\u200d' for c in text)):
        raise ValueError('invalid Threads content')
    try:
        text.encode('utf-8')
    except UnicodeError:
        raise ValueError('invalid Threads content') from None
    params = {'media_type': media_type}
    if media_type == 'TEXT':
        if not any(not c.isspace() and unicodedata.category(c)[0] not in 'CM' for c in text) or media_url is not None:
            raise ValueError('invalid Threads content')
    else:
        params['image_url' if media_type == 'IMAGE' else 'video_url'] = _media_url(media_url)
    if text:
        params['text'] = text
    return {'preview_only': True, 'request': {'method': 'POST', 'path': path, 'params': params},
            'warnings': ['not_authorized', 'api_version_unverified', 'content_limits_unverified',
                         'media_not_fetched_or_validated', 'url_host_and_access_unverified',
                         'container_not_post', 'provider_may_fetch_media_if_sent']}


def preview_publish(*, user_id: str, api_version: str, creation_id: str) -> dict[str, Any]:
    """Describe a publish request; the result would publish if sent."""
    path = _endpoint(user_id, api_version, 'threads_publish')
    if not isinstance(creation_id, str) or not _ID.fullmatch(creation_id):
        raise ValueError('invalid Threads container')
    return {'preview_only': True, 'request': {'method': 'POST', 'path': path,
                                              'params': {'creation_id': creation_id}},
            'warnings': ['not_authorized', 'would_publish_if_sent', 'container_readiness_unverified',
                         'container_ownership_unverified', 'api_version_unverified']}


def preview_marketing_anchor(*, source: str, anchor: str, user_id: str, api_version: str,
                             media_type: str, media_url: str | None = None) -> dict[str, Any]:
    """Build from a synthetic extension anchor; it is not a V1 format enum."""
    from markdown_it import MarkdownIt
    from scripts.lib.delivery_anchors import extract_delivery_anchor

    if not isinstance(anchor, str) or not re.fullmatch(r'post:threads_post(?:#[1-9][0-9]*)?', anchor):
        raise ValueError('invalid Threads anchor')
    text = extract_delivery_anchor(source, anchor)
    env: dict[str, Any] = {}
    tokens = MarkdownIt('commonmark', {'html': True}).parse(text, env)
    if env.get('references') or any(token.type in {'heading_open', 'html_block', 'blockquote_open', 'fence', 'code_block'}
           or any(child.type == 'html_inline' for child in (token.children or [])) for token in tokens):
        raise ValueError('ambiguous Threads anchor')
    text = text.removesuffix('\n').removesuffix('\r')
    result = preview_container(user_id=user_id, api_version=api_version, media_type=media_type,
                               text=text, media_url=media_url)
    result['source_anchor'] = anchor
    result['warnings'].append('synthetic_anchor_not_v1_enum')
    return result
