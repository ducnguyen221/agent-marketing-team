"""Synthetic TikTok marketing/video intent, never a real upload or consent."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from typing import Any

from markdown_it import MarkdownIt
import yaml

from scripts.lib.delivery_anchors import _split_frontmatter, extract_delivery_anchor
from scripts.social.channels.tiktok.direct import preview_direct_post, preview_inbox_upload
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node: Any, deep: bool = False) -> dict[str, Any]:
        result = {}
        for key_node, value_node in node.value:
            if key_node.tag == 'tag:yaml.org,2002:merge':
                raise ValueError('invalid fixture metadata')
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError('invalid fixture metadata')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _validate_caption(caption: Any) -> None:
    if (not isinstance(caption, str) or not any(not c.isspace() and unicodedata.category(c)[0] not in 'CM' for c in caption)
            or any(unicodedata.category(c).startswith('C') and c not in '\n\t\u200d' for c in caption)
            or '{{' in caption or '}}' in caption):
        raise ValueError('invalid TikTok fixture caption')
    env: dict[str, Any] = {}
    tokens = MarkdownIt('commonmark', {'html': True}).parse(caption, env)
    if env.get('references') or any(token.type in {'heading_open', 'html_block', 'blockquote_open', 'fence', 'code_block'}
           or any(child.type == 'html_inline' for child in (token.children or [])) for token in tokens):
        raise ValueError('ambiguous TikTok fixture anchor')


def build_tiktok_fixture_snapshot(*, key: dict[str, str], target: dict[str, str],
                           source: str, anchor: str, mode: str, scheduled_at: str, video_size: int,
                           chunk_size: int, media_id: str, media_sha256_fixture: str,
                           duration_sec: int | None = None, creator: dict[str, Any] | None = None,
                           creator_revision: str | None = None, consent_fixture: bool | None = None,
                           consent_digest_fixture: str | None = None, post_info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an unapproved synthetic snapshot without a database or network."""
    key, target, creator, post_info = copy.deepcopy((key, target, creator, post_info))
    if (not isinstance(key, dict) or key.get('platform') != 'tiktok'
            or not isinstance(target, dict) or set(target) != {'account_id', 'destination_id', 'creator_id'}
            or target['account_id'] != key.get('account_id') or target['destination_id'] != key.get('destination_id')
            or not isinstance(target['creator_id'], str)):
        raise ValueError('fixture TikTok target mismatch')
    match = re.fullmatch(r'fixture-tiktok-creator-([A-Za-z0-9][A-Za-z0-9_-]{0,63})', target['creator_id'])
    if (match is None or target['account_id'] != 'fixture-tiktok-account-' + match.group(1)
            or target['destination_id'] != 'fixture-tiktok-profile-' + match.group(1)):
        raise ValueError('fixture TikTok target mismatch')
    if (not isinstance(source, str) or len(source) > 1_000_000 or not isinstance(anchor, str)
            or not re.fullmatch(r'post:tiktok_post(?:#[1-9][0-9]*)?', anchor)
            or not isinstance(media_id, str) or not re.fullmatch(r'fixture-video(?:-[A-Za-z0-9_-]{1,100})?', media_id)
            or not isinstance(media_sha256_fixture, str) or not re.fullmatch(r'[0-9a-f]{64}', media_sha256_fixture)):
        raise ValueError('invalid TikTok fixture input')
    _fixture_time(scheduled_at)
    header, _ = _split_frontmatter(source)
    if header is not None:
        try:
            metadata = yaml.load(header, Loader=_UniqueLoader)
        except (yaml.YAMLError, ValueError, TypeError, RecursionError):
            raise ValueError('invalid fixture metadata') from None
        if (not isinstance(metadata, dict) or metadata.get('schema') != 'content/1'
                or metadata.get('content_id') != key.get('content_id')
                or metadata.get('campaign_id') != key.get('campaign_id')):
            raise ValueError('fixture source identity mismatch')
    caption = extract_delivery_anchor(source, anchor)
    caption = caption.replace('\r\n', '\n').removesuffix('\n')
    _validate_caption(caption)
    if mode == 'INBOX':
        if any(value is not None for value in (duration_sec, creator, creator_revision, consent_fixture,
                                                consent_digest_fixture, post_info)):
            raise ValueError('direct options are not inbox options')
        candidate = preview_inbox_upload(video_size=video_size, chunk_size=chunk_size)
    elif mode == 'DIRECT':
        if not isinstance(post_info, dict) or post_info.get('title') != caption:
            raise ValueError('fixture caption mismatch')
        candidate = preview_direct_post(video_size=video_size, chunk_size=chunk_size, duration_sec=duration_sec,
            creator=creator, expected_creator=target['creator_id'], expected_revision=creator_revision,
            consent_fixture=consent_fixture, post_info=post_info, media_sha256_fixture=media_sha256_fixture,
            consent_digest_fixture=consent_digest_fixture)
    else:
        raise ValueError('invalid TikTok fixture mode')
    snapshot = {'fixture_schema': 'tiktok-intent/1', 'platform': 'tiktok', 'account_id': key['account_id'], 'destination_id': key['destination_id'],
                'target': target, 'mode': mode, 'scheduled_at': scheduled_at, 'candidate': candidate,
                'media_id': media_id, 'media_sha256_fixture': media_sha256_fixture, 'suggested_caption': caption,
                'source_anchor': anchor,
                'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
                'source_identity': 'caller_metadata_matches_unverified' if header is not None else 'caller_text_only',
                'validation_inputs': {'video_size': video_size, 'chunk_size': chunk_size, 'duration_sec': duration_sec,
                    'creator': creator, 'creator_revision': creator_revision, 'consent_fixture': consent_fixture,
                    'consent_digest_fixture': consent_digest_fixture, 'post_info': post_info}}
    return snapshot


def prepare_tiktok_fixture(ledger: DestinationFixtureLedger, *, key: dict[str, str], target: dict[str, str],
                           source: str, anchor: str, mode: str, scheduled_at: str, video_size: int,
                           chunk_size: int, media_id: str, media_sha256_fixture: str,
                           duration_sec: int | None = None, creator: dict[str, Any] | None = None,
                           creator_revision: str | None = None, consent_fixture: bool | None = None,
                           consent_digest_fixture: str | None = None, post_info: dict[str, Any] | None = None) -> str:
    """Persist one synthetic snapshot in the explicitly supplied fixture ledger."""
    if type(ledger) is not DestinationFixtureLedger:
        raise ValueError('fixture TikTok target mismatch')
    key = copy.deepcopy(key)
    payload = build_tiktok_fixture_snapshot(
        key=key, target=target, source=source, anchor=anchor, mode=mode, scheduled_at=scheduled_at,
        video_size=video_size, chunk_size=chunk_size, media_id=media_id, media_sha256_fixture=media_sha256_fixture,
        duration_sec=duration_sec, creator=creator, creator_revision=creator_revision,
        consent_fixture=consent_fixture, consent_digest_fixture=consent_digest_fixture, post_info=post_info)
    return ledger.prepare(key, payload)


def validate_tiktok_snapshot(payload: dict[str, Any], *, account: str, destination: str) -> None:
    """Rebuild an entirely synthetic candidate; this does not prove consent or source."""
    fields = {'fixture_schema', 'platform', 'account_id', 'destination_id', 'target', 'mode', 'scheduled_at',
              'candidate', 'media_id', 'media_sha256_fixture', 'suggested_caption', 'source_anchor',
              'source_sha256', 'source_identity', 'validation_inputs'}
    input_fields = {'video_size', 'chunk_size', 'duration_sec', 'creator', 'creator_revision',
                    'consent_fixture', 'consent_digest_fixture', 'post_info'}
    if not isinstance(payload, dict) or set(payload) != fields or payload['fixture_schema'] != 'tiktok-intent/1':
        raise ValueError('invalid TikTok fixture snapshot')
    target, inputs = payload['target'], payload['validation_inputs']
    if (payload['platform'] != 'tiktok' or payload['account_id'] != account or payload['destination_id'] != destination
            or not isinstance(target, dict) or set(target) != {'account_id', 'destination_id', 'creator_id'}
            or target['account_id'] != account or target['destination_id'] != destination
            or not isinstance(target['creator_id'], str) or not isinstance(inputs, dict) or set(inputs) != input_fields):
        raise ValueError('invalid TikTok fixture target')
    match = re.fullmatch(r'fixture-tiktok-creator-([A-Za-z0-9][A-Za-z0-9_-]{0,63})', target['creator_id'])
    if (match is None or account != 'fixture-tiktok-account-' + match.group(1)
            or destination != 'fixture-tiktok-profile-' + match.group(1)):
        raise ValueError('invalid TikTok fixture target')
    if (not isinstance(payload['media_id'], str) or not re.fullmatch(r'fixture-video(?:-[A-Za-z0-9_-]{1,100})?', payload['media_id'])
            or not isinstance(payload['media_sha256_fixture'], str) or not re.fullmatch(r'[0-9a-f]{64}', payload['media_sha256_fixture'])
            or not isinstance(payload['source_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', payload['source_sha256'])
            or not isinstance(payload['source_anchor'], str) or not re.fullmatch(r'post:tiktok_post(?:#[1-9][0-9]*)?', payload['source_anchor'])
            or payload['source_identity'] not in ('caller_metadata_matches_unverified', 'caller_text_only')):
        raise ValueError('invalid TikTok fixture source')
    caption = payload['suggested_caption']
    _validate_caption(caption)
    _fixture_time(payload['scheduled_at'])
    if payload['mode'] == 'INBOX':
        if any(inputs[field] is not None for field in input_fields - {'video_size', 'chunk_size'}):
            raise ValueError('invalid TikTok inbox options')
        candidate = preview_inbox_upload(video_size=inputs['video_size'], chunk_size=inputs['chunk_size'])
    elif payload['mode'] == 'DIRECT':
        if not isinstance(inputs['post_info'], dict) or inputs['post_info'].get('title') != caption:
            raise ValueError('fixture caption mismatch')
        candidate = preview_direct_post(video_size=inputs['video_size'], chunk_size=inputs['chunk_size'],
            duration_sec=inputs['duration_sec'], creator=inputs['creator'], expected_creator=target['creator_id'],
            expected_revision=inputs['creator_revision'], consent_fixture=inputs['consent_fixture'],
            post_info=inputs['post_info'], media_sha256_fixture=payload['media_sha256_fixture'],
            consent_digest_fixture=inputs['consent_digest_fixture'])
    else:
        raise ValueError('invalid TikTok fixture mode')
    try:
        canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        if canonical(payload['candidate']) != canonical(candidate):
            raise ValueError('TikTok candidate mismatch')
    except (TypeError, RecursionError):
        raise ValueError('invalid TikTok fixture candidate') from None
