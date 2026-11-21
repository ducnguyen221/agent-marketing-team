"""In-memory Telegram publisher simulation; no network or credentials."""
from __future__ import annotations

import copy
from typing import Any

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


class FakeTelegramTransport:
    """Return a caller-supplied synthetic Message independently of the request."""

    def __init__(self, *, response: dict[str, Any] | None) -> None:
        if response is not None and not isinstance(response, dict):
            raise ValueError('invalid synthetic Telegram response')
        self._response = copy.deepcopy(response)
        self.calls = 0
        self.last_candidate: dict[str, Any] | None = None
        self.last_attempt: str | None = None
        self.last_account_id: str | None = None

    def _send(self, candidate: dict[str, Any], attempt: str, account_id: str) -> dict[str, Any] | None:
        self.calls += 1
        self.last_candidate = copy.deepcopy(candidate)
        self.last_attempt = attempt
        self.last_account_id = account_id
        return copy.deepcopy(self._response)


def _receipt(candidate: dict[str, Any], response: Any) -> tuple[str, str, str | None] | None:
    if not isinstance(response, dict) or not isinstance(response.get('chat'), dict):
        return None
    chat = response['chat']
    message_id = response.get('message_id')
    body = candidate['request']['body']
    method = candidate['request']['method']
    kinds = {'sendMessage': None, 'sendPhoto': 'image', 'sendVideo': 'video'}
    if (method not in kinds or type(message_id) is not int or not 1 <= message_id < 10**20
            or type(chat.get('id')) is not int or str(chat['id']) != body['chat_id']
            or chat.get('type') != 'channel'):
        return None
    kind = kinds[method]
    if kind is None:
        if response.get('text') != body['text'] or any(field in response for field in ('photo', 'video', 'caption')):
            return None
    else:
        media = response.get('photo' if kind == 'image' else 'video')
        if ('text' in response or response.get('caption', '') != body.get('caption', '')
                or (kind == 'image' and (not isinstance(media, list) or not media
                    or any(not isinstance(item, dict) or not isinstance(item.get('file_id'), str)
                           or not item['file_id'].startswith('fixture-') for item in media)))
                or (kind == 'video' and (not isinstance(media, dict) or not isinstance(media.get('file_id'), str)
                    or not media['file_id'].startswith('fixture-')))
                or ('video' in response if kind == 'image' else 'photo' in response)):
            return None
    return str(chat['id']), str(message_id), kind


def send_due_fixture(ledger: DestinationFixtureLedger, intent_id: str, *, expected_version: int,
                     now: str, transport: FakeTelegramTransport) -> None:
    """Claim a publisher fixture and interpret one independently configured response."""
    if type(ledger) is not DestinationFixtureLedger or type(transport) is not FakeTelegramTransport:
        raise ValueError('synthetic transport required')
    attempt, candidate, account_id = ledger.claim_due_telegram_fixture(intent_id, expected_version=expected_version, now=now)
    receipt = _receipt(candidate, transport._send(candidate, attempt, account_id))
    if receipt is None:
        ledger.mark_unknown(intent_id, attempt=attempt)
        return
    chat_id, message_id, media_kind = receipt
    ledger.finish_telegram_fixture(intent_id, attempt=attempt, chat_id=chat_id, chat_type='channel',
                                   message_id=message_id, media_kind=media_kind)
