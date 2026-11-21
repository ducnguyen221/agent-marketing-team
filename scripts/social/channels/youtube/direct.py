"""YouTube videos.insert metadata previews only; no files, network or tokens."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from markdown_it import MarkdownIt

from scripts.lib.delivery_anchors import extract_delivery_anchor


def _text(value: Any, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValueError('invalid YouTube text')
    value = value.replace('\r\n', '\n')
    if ('<' in value or '>' in value or '{{' in value or '}}' in value
            or any(unicodedata.category(c).startswith('C') and c not in '\n\t\u200d' for c in value)
            or ((value or not allow_empty)
                and not any(not c.isspace() and unicodedata.category(c)[0] not in 'CM' for c in value))):
        raise ValueError('invalid YouTube text')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ValueError('invalid YouTube text') from None
    return value


def preview_video(*, title: str, description: str, category_id: str, privacy: str,
                  made_for_kids: bool, media_id: str) -> dict[str, Any]:
    title, description = _text(title, allow_empty=False), _text(description, allow_empty=True)
    if (len(title) > 100 or len(description.encode('utf-8')) > 5000
            or not isinstance(category_id, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', category_id)
            or privacy not in ('private', 'unlisted', 'public') or type(made_for_kids) is not bool
            or not isinstance(media_id, str) or not re.fullmatch(r'fixture-video(?:-[A-Za-z0-9_-]{1,100})?', media_id)):
        raise ValueError('invalid YouTube fixture video')
    return {'preview_only': True, 'media_id': media_id,
            'request': {'method': 'POST', 'host': 'www.googleapis.com', 'path': '/upload/youtube/v3/videos',
                        'params': {'part': 'snippet,status', 'uploadType': 'resumable'},
                        'body': {'snippet': {'title': title, 'description': description, 'categoryId': category_id},
                                 'status': {'privacyStatus': privacy, 'selfDeclaredMadeForKids': made_for_kids}}},
            'warnings': ['not_authorized', 'would_upload_if_sent', 'media_not_read_or_uploaded',
                         'account_and_channel_unverified', 'category_and_api_behavior_unverified',
                         'resumable_session_and_thumbnail_not_created', 'no_provider_schedule_prepared',
                         'notify_subscribers_defaults_true_delivery_unverified']}


def preview_marketing_anchor(*, source: str, anchor: str, title: str, category_id: str, privacy: str,
                             made_for_kids: bool, media_id: str) -> dict[str, Any]:
    if not isinstance(anchor, str) or not re.fullmatch(r'post:youtube_(?:desc|short)(?:#[1-9][0-9]*)?', anchor):
        raise ValueError('invalid YouTube anchor')
    description = extract_delivery_anchor(source, anchor).replace('\r\n', '\n').removesuffix('\n')
    env: dict[str, Any] = {}
    tokens = MarkdownIt('commonmark', {'html': True}).parse(description, env)
    if env.get('references') or any(token.type == 'html_block'
            or any(child.type == 'html_inline' for child in (token.children or [])) for token in tokens):
        raise ValueError('hidden YouTube source content')
    if re.fullmatch(r'post:youtube_short(?:#[1-9][0-9]*)?', anchor):
        lines = description.splitlines()
        captions = []
        caption_end = None
        for token in tokens:
            if token.type != 'paragraph_open' or token.level != 0 or token.map is None:
                continue
            start, end = token.map
            line = lines[start].lstrip(' \t')
            if line.startswith('**Caption:**'):
                match = re.fullmatch(r'\*\*Caption:\*\*[ \t]*(\S.*?)[ \t]*', line)
                if end != start + 1 or match is None:
                    raise ValueError('invalid YouTube Short caption')
                captions.append(match.group(1))
                caption_end = end
        if len(captions) != 1 or any(line.strip() not in ('', '---') for line in lines[caption_end:]):
            raise ValueError('YouTube Short caption missing or ambiguous')
        description = captions[0]
    result = preview_video(title=title, description=description, category_id=category_id, privacy=privacy,
                           made_for_kids=made_for_kids, media_id=media_id)
    result['source_anchor'] = anchor
    if re.fullmatch(r'post:youtube_short(?:#[1-9][0-9]*)?', anchor):
        result['warnings'].append('shorts_classification_unverified')
    return result
