"""Synthetic Discord text request previews; no network or credentials."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def preview_message(*, channel_id: str, text: str) -> dict[str, Any]:
    """Build an offline message candidate with mention parsing disabled."""
    if (not isinstance(channel_id, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', channel_id)
            or not isinstance(text, str) or not text.strip() or len(text) > 2000
            or not any(not char.isspace() and unicodedata.category(char)[0] not in 'CM' for char in text)
            or '{{' in text or '}}' in text
            or any(unicodedata.category(char).startswith('C') and char not in '\n\t\u200d' for char in text)):
        raise ValueError('invalid Discord fixture message')
    try:
        text.encode('utf-8')
    except UnicodeError:
        raise ValueError('invalid Discord fixture message') from None
    return {'preview_only': True, 'request': {'method': 'POST', 'host': 'discord.com',
        'path': f'/api/v10/channels/{channel_id}/messages',
        'body': {'content': text, 'allowed_mentions': {'parse': []}}},
        'warnings': ['not_authorized', 'would_send_if_submitted', 'bot_and_channel_unverified',
                     'limits_and_mention_behavior_unverified']}
