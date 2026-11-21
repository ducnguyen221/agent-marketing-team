"""Facebook Page request previews; no credentials, transport or publication."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from markdown_it import MarkdownIt

from scripts.lib.delivery_anchors import extract_delivery_anchor, split_facebook_source
from scripts.social.channels.threads.direct import _media_url

_ID = re.compile(r'[1-9][0-9]{0,31}\Z')
_VERSION = re.compile(r'v[0-9]{1,3}\.[0-9]{1,3}\Z')


def _check_page(page_id: str, api_version: str) -> None:
    if (not isinstance(page_id, str) or not _ID.fullmatch(page_id)
            or not isinstance(api_version, str) or not _VERSION.fullmatch(api_version)):
        raise ValueError('invalid Facebook Page fixture')


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError('invalid Facebook content')
    value = value.replace('\r\n', '\n').strip('\n')
    if (len(value) > 20000 or '{{' in value or '}}' in value
            or not any(not c.isspace() and unicodedata.category(c)[0] not in 'CM' for c in value)
            or any(unicodedata.category(c).startswith('C') and c not in '\n\t\u200d' for c in value)):
        raise ValueError('invalid Facebook content')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ValueError('invalid Facebook content') from None
    return value


def preview_post(*, page_id: str, api_version: str, media_type: str, message: str,
                 media_url: str | None = None) -> dict[str, Any]:
    _check_page(page_id, api_version)
    message = _text(message)
    if media_type == 'TEXT' and media_url is None:
        operation, params = 'feed', {'message': message}
    elif media_type == 'IMAGE':
        try:
            url = _media_url(media_url)
        except ValueError:
            raise ValueError('invalid Facebook media URL') from None
        operation, params = 'photos', {'caption': message, 'url': url}
    elif media_type == 'VIDEO':
        try:
            url = _media_url(media_url)
        except ValueError:
            raise ValueError('invalid Facebook media URL') from None
        operation, params = 'videos', {'description': message, 'file_url': url}
    else:
        raise ValueError('invalid Facebook media type')
    return {'preview_only': True, 'host': 'graph.facebook.com',
            'request': {'method': 'POST', 'path': f'/{api_version}/{page_id}/{operation}', 'params': params},
            'warnings': ['not_authorized', 'would_publish_if_sent', 'account_and_permissions_unverified',
                         'api_version_unverified', 'raw_markdown_unvalidated', 'media_not_fetched_or_validated']}


def preview_comment(*, page_id: str, post_id: str, api_version: str, message: str) -> dict[str, Any]:
    _check_page(page_id, api_version)
    if not isinstance(post_id, str) or not re.fullmatch(re.escape(page_id) + r'_[1-9][0-9]{0,31}', post_id):
        raise ValueError('invalid Facebook post fixture')
    return {'preview_only': True, 'host': 'graph.facebook.com',
            'request': {'method': 'POST', 'path': f'/{api_version}/{post_id}/comments', 'params': {'message': _text(message)}},
            'warnings': ['not_authorized', 'would_comment_if_sent', 'post_identity_and_permissions_unverified',
                         'raw_markdown_unvalidated']}


def preview_marketing_anchor(*, source: str, anchor: str, page_id: str, api_version: str,
                             media_type: str, media_url: str | None = None) -> dict[str, Any]:
    parts = split_facebook_source(source, anchor)
    for value in (parts['body'], parts['first_comment']):
        if value is None:
            continue
        env: dict[str, Any] = {}
        tokens = MarkdownIt('commonmark', {'html': True}).parse(value, env)
        if env.get('references') or any(token.type == 'html_block'
                or any(child.type == 'html_inline' for child in (token.children or [])) for token in tokens):
            raise ValueError('hidden Facebook source content')
    result = preview_post(page_id=page_id, api_version=api_version, media_type=media_type,
                          message=parts['body'], media_url=media_url)
    result['first_comment'] = _text(parts['first_comment']) if parts['first_comment'] is not None else None
    result['image_prompt_present'] = parts['image_prompt_present']
    result['source_anchor'] = anchor
    result['warnings'].append('first_comment_not_submitted')
    return result


def preview_reel_anchor(*, source: str, anchor: str, page_id: str, api_version: str,
                        media_id: str) -> dict[str, Any]:
    """Describe only a synthetic Reel start; caller must not send this preview."""
    _check_page(page_id, api_version)
    if (not isinstance(anchor, str) or not re.fullmatch(r'post:reel(?:#[1-9][0-9]*)?', anchor)
            or not isinstance(media_id, str) or not re.fullmatch(r'fixture-video(?:-[A-Za-z0-9_-]{1,100})?', media_id)):
        raise ValueError('invalid Facebook Reel fixture')
    content = extract_delivery_anchor(source, anchor).replace('\r\n', '\n')
    env: dict[str, Any] = {}
    tokens = MarkdownIt('commonmark', {'html': True}).parse(content, env)
    if env.get('references') or any(token.type == 'html_block'
            or any(child.type == 'html_inline' for child in (token.children or [])) for token in tokens):
        raise ValueError('hidden Reel content')
    lines = content.splitlines()
    paragraphs = []
    seen_quote = False
    for token in tokens:
        if token.level != 0:
            continue
        if token.type == 'blockquote_open':
            template_note = '> Caption NGẮN đi kèm video/Reel — khác hẳn bài dài ở trên. 1–3 câu + link + ≤6 hashtag.'
            if (seen_quote or paragraphs or token.map is None
                    or lines[token.map[0]:token.map[1]] != [template_note]):
                raise ValueError('ambiguous Reel caption')
            seen_quote = True
        elif token.type == 'paragraph_open' and token.map is not None:
            paragraphs.append(token.map)
        elif token.type not in ('blockquote_close', 'paragraph_close', 'inline', 'hr'):
            raise ValueError('ambiguous Reel caption')
    if not paragraphs:
        raise ValueError('invalid Reel caption')
    first, last = paragraphs[0][0], paragraphs[-1][1]
    caption = _text('\n'.join(lines[first:last]))
    return {'preview_only': True, 'media_id': media_id, 'caption': caption, 'source_anchor': anchor,
            'request': {'method': 'POST', 'host': 'graph.facebook.com',
                        'path': f'/{api_version}/{page_id}/video_reels', 'params': {'upload_phase': 'start'}},
            'warnings': ['not_authorized', 'not_uploaded', 'upload_and_finish_not_prepared',
                         'page_and_media_unverified', 'api_version_unverified']}
