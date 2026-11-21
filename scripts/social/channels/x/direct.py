"""Synthetic X text request preview; no transport or credentials."""
from __future__ import annotations

import unicodedata
from typing import Any


def preview_post(*, text: str) -> dict[str, Any]:
    """Prepare a single text candidate without asserting platform validity."""
    if not isinstance(text, str) or not 1 <= len(text) <= 32000:
        raise ValueError('invalid X fixture text')
    text = text.replace('\r\n', '\n')
    if ('{{' in text or '}}' in text
            or any(unicodedata.category(char) in ('Cc', 'Cs') and char not in '\n\t' for char in text)
            or any(char in '\u061c\u200e\u200f' for char in text)
            or any(unicodedata.bidirectional(char) in ('LRE', 'RLE', 'LRO', 'RLO', 'PDF', 'LRI', 'RLI', 'FSI', 'PDI') for char in text)
            or not any(not char.isspace() and unicodedata.category(char)[0] not in ('C', 'M') for char in text)):
        raise ValueError('invalid X fixture text')
    return {'preview_only': True, 'request': {'method': 'POST', 'path': '/2/tweets', 'body': {'text': text}},
            'warnings': ['not_authorized', 'would_publish_if_sent', 'x_weighted_length_unchecked',
                         'account_and_permissions_unverified']}
