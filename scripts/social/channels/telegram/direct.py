"""Synthetic Telegram channel message preview; no token, network or dispatch."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def valid_fixture_chat_id(chat_id: Any) -> bool:
    return (isinstance(chat_id, str) and bool(re.fullmatch(r'-100[1-9][0-9]{0,19}', chat_id))
            and abs(int(chat_id)).bit_length() <= 52)


def preview_message(*, chat_id: str, text: str) -> dict[str, Any]:
    if isinstance(text, str):
        text = text.replace('\r\n', '\n')
    if (not valid_fixture_chat_id(chat_id)
            or not isinstance(text, str) or not 1 <= len(text) <= 4096 or '{{' in text or '}}' in text
            or any(unicodedata.category(char) in ('Cc', 'Cs') and char not in '\n\t' for char in text)
            or any(char in '\u061c\u200e\u200f' or unicodedata.bidirectional(char) in
                   ('LRE', 'RLE', 'LRO', 'RLO', 'PDF', 'LRI', 'RLI', 'FSI', 'PDI') for char in text)
            or not any(not char.isspace() and unicodedata.category(char)[0] not in 'CM' for char in text)):
        raise ValueError('invalid Telegram fixture message')
    return {'preview_only': True, 'request': {'method': 'sendMessage',
            'body': {'chat_id': chat_id, 'text': text}},
            'warnings': ['synthetic_only', 'not_authorized', 'would_send_if_submitted',
                         'bot_and_channel_unverified', 'content_limits_unverified']}


def preview_media(*, chat_id: str, media_kind: str, media_id: str, caption: str) -> dict[str, Any]:
    """Describe one synthetic attachment without resolving a file or token."""
    if (media_kind not in ('image', 'video') or not isinstance(media_id, str)
            or not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,100}', media_id) or not isinstance(caption, str)):
        raise ValueError('invalid Telegram fixture media')
    normalized = caption.replace('\r\n', '\n')
    if len(normalized) > 1024:
        raise ValueError('invalid Telegram fixture caption')
    if normalized:
        preview_message(chat_id=chat_id, text=normalized)
    elif not valid_fixture_chat_id(chat_id):
        raise ValueError('invalid Telegram fixture channel')
    field = 'photo' if media_kind == 'image' else 'video'
    body = {'chat_id': chat_id, field: media_id}
    if normalized:
        body['caption'] = normalized
    return {'preview_only': True, 'request': {'method': 'sendPhoto' if field == 'photo' else 'sendVideo', 'body': body},
            'warnings': ['synthetic_only', 'not_authorized', 'would_send_if_submitted', 'media_not_uploaded',
                         'bot_channel_and_media_unverified', 'content_limits_unverified']}
