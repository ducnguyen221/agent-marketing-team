"""Instagram Facebook Login request previews; never fetch media or call Meta."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from markdown_it import MarkdownIt

from scripts.lib.delivery_anchors import extract_delivery_anchor
from scripts.social.channels.threads.direct import _media_url

_ID = re.compile(r'[0-9]{1,32}\Z')
_VERSION = re.compile(r'v[0-9]{1,3}\.[0-9]{1,3}\Z')


def _path(user_id: str, api_version: str, operation: str) -> str:
    if (not isinstance(user_id, str) or not _ID.fullmatch(user_id)
            or not isinstance(api_version, str) or not _VERSION.fullmatch(api_version)):
        raise ValueError('invalid Instagram destination')
    return f'/{api_version}/{user_id}/{operation}'


def preview_container(*, user_id: str, api_version: str, media_type: str,
                      media_url: str, caption: str) -> dict[str, Any]:
    """Describe one image or Reel container for Facebook Login; no send."""
    path = _path(user_id, api_version, 'media')
    if isinstance(caption, str):
        caption = caption.replace('\r\n', '\n')
    if (media_type not in ('IMAGE', 'REELS') or not isinstance(caption, str) or len(caption) > 20000
            or '{{' in caption or '}}' in caption
            or (caption and not any(not c.isspace() and unicodedata.category(c)[0] not in 'CM' for c in caption))
            or any(unicodedata.category(c).startswith('C') and c not in '\n\t\u200d' for c in caption)):
        raise ValueError('invalid Instagram content')
    try:
        caption.encode('utf-8')
    except UnicodeError:
        raise ValueError('invalid Instagram content') from None
    try:
        url = _media_url(media_url)
    except ValueError:
        raise ValueError('invalid Instagram media URL') from None
    params = {'image_url' if media_type == 'IMAGE' else 'video_url': url}
    if media_type == 'REELS':
        params['media_type'] = 'REELS'
    if caption:
        params['caption'] = caption
    return {'preview_only': True, 'login_product': 'facebook_login', 'host': 'graph.facebook.com',
            'request': {'method': 'POST', 'path': path, 'params': params},
            'warnings': ['not_authorized', 'api_version_unverified', 'media_not_fetched_or_validated',
                         'url_host_and_access_unverified', 'content_limits_unverified', 'container_not_post',
                         'provider_may_fetch_media_if_sent']}


def preview_publish(*, user_id: str, api_version: str, creation_id: str) -> dict[str, Any]:
    path = _path(user_id, api_version, 'media_publish')
    if not isinstance(creation_id, str) or not _ID.fullmatch(creation_id):
        raise ValueError('invalid Instagram container')
    return {'preview_only': True, 'login_product': 'facebook_login', 'host': 'graph.facebook.com',
            'request': {'method': 'POST', 'path': path, 'params': {'creation_id': creation_id}},
            'warnings': ['not_authorized', 'would_publish_if_sent', 'container_readiness_unverified',
                         'container_ownership_unverified', 'api_version_unverified']}


def preview_marketing_anchor(*, source: str, anchor: str, user_id: str, api_version: str,
                             media_type: str, media_url: str) -> dict[str, Any]:
    expected = 'infographic' if media_type == 'IMAGE' else 'instagram_reel' if media_type == 'REELS' else None
    if (expected is None or not isinstance(anchor, str)
            or not re.fullmatch(r'post:' + expected + r'(?:#[1-9][0-9]*)?', anchor)):
        raise ValueError('invalid Instagram anchor')
    content = extract_delivery_anchor(source, anchor)
    env: dict[str, Any] = {}
    tokens = MarkdownIt('commonmark', {'html': True}).parse(content, env)
    if media_type == 'IMAGE':
        lines = content.splitlines()
        matches = []
        caption_end = None
        for token in tokens:
            if token.type != 'paragraph_open' or token.level != 0 or token.map is None:
                continue
            start, end = token.map
            if lines[start].startswith('**Caption:**'):
                if end != start + 1:
                    raise ValueError('fixture caption is multiline')
                match = re.fullmatch(r'\*\*Caption:\*\*[ \t]*(\S.*?)[ \t]*', lines[start])
                if match is None or '<' in match.group(1) or '>' in match.group(1):
                    raise ValueError('invalid fixture caption')
                matches.append(match.group(1))
                caption_end = end
        if len(matches) != 1 or any(line.strip() not in ('', '---') for line in lines[caption_end:]):
            raise ValueError('fixture caption missing or ambiguous')
        caption = matches[0].strip()
    else:
        if env.get('references') or any(token.type in {'heading_open', 'html_block', 'blockquote_open', 'fence', 'code_block'}
                or any(child.type == 'html_inline' for child in (token.children or [])) for token in tokens):
            raise ValueError('ambiguous Instagram anchor')
        caption = content.replace('\r\n', '\n').removesuffix('\n')
        if not any(not c.isspace() and unicodedata.category(c)[0] not in 'CM' for c in caption):
            raise ValueError('invalid Instagram caption')
    result = preview_container(user_id=user_id, api_version=api_version, media_type=media_type,
                               media_url=media_url, caption=caption)
    result['source_anchor'] = anchor
    if media_type == 'REELS':
        result['warnings'].append('synthetic_anchor_not_v1_enum')
    return result
