"""Prepare one offline batch from a synthetic marketing source; never submit."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from typing import Any

from scripts.social.destination_ledger_fixture import _fixture_time

_LABEL = re.compile(r'fixture-[A-Za-z0-9][A-Za-z0-9_-]{0,100}\Z')
_LEDGER_LABEL = re.compile(r'fixture-[A-Za-z0-9][A-Za-z0-9_.-]{0,247}\Z')
_URL = re.compile(r'https://fixture\.example\.test/assets/fixture-[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')


def _preview(platform: str, destination: str, source: str, options: dict[str, Any], scheduled_at: str) -> dict[str, Any]:
    if 'source' in options:
        raise ValueError('source must be shared')
    if platform == 'tiktok':
        from scripts.social.tiktok_fixture_flow import build_tiktok_fixture_snapshot
        match = re.fullmatch(r'fixture-tiktok-profile-([A-Za-z0-9][A-Za-z0-9_-]{0,63})', destination)
        content, campaign = options.get('content_id'), options.get('campaign_id')
        if (match is None or not isinstance(content, str) or not _LABEL.fullmatch(content)
                or not isinstance(campaign, str) or not _LABEL.fullmatch(campaign)):
            raise ValueError('invalid TikTok fixture identity')
        suffix = match.group(1)
        account = 'fixture-tiktok-account-' + suffix
        target = {'account_id': account, 'destination_id': destination, 'creator_id': 'fixture-tiktok-creator-' + suffix}
        key = {'station_id': 'fixture-station', 'channel_id': 'fixture-channel', 'campaign_id': campaign,
               'content_id': content, 'post_id': 'fixture-post', 'platform': 'tiktok', 'account_id': account,
               'destination_id': destination, 'occurrence_key': 'fixture-slot'}
        args = {name: value for name, value in options.items() if name not in ('content_id', 'campaign_id')}
        try:
            payload = build_tiktok_fixture_snapshot(key=key, target=target, source=source,
                                                    scheduled_at=scheduled_at, **args)
            return {'preview_only': True, 'mode': payload['mode'], 'suggested_caption': payload['suggested_caption'],
                        'source_anchor': payload['source_anchor'], 'media_id': payload['media_id'],
                        'media_sha256_fixture': payload['media_sha256_fixture'],
                        'candidate': payload['candidate'], 'warnings': ['synthetic_only', 'source_and_media_unverified',
                            'consent_is_fixture_only', 'no_provider_request_sent']}
        except TypeError:
            raise ValueError('invalid TikTok fixture options') from None
    if platform == 'facebook':
        from scripts.social.channels.facebook.direct import preview_marketing_anchor
        page = options.get('page_id')
        if not isinstance(page, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', page) or destination != 'fixture-facebook-page-' + page:
            raise ValueError('fixture destination mismatch')
    elif platform == 'instagram':
        from scripts.social.channels.instagram.direct import preview_marketing_anchor
        user = options.get('user_id')
        if not isinstance(user, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', user) or destination != 'fixture-instagram-' + user:
            raise ValueError('fixture destination mismatch')
    elif platform == 'threads':
        from scripts.social.channels.threads.direct import preview_marketing_anchor
        user = options.get('user_id')
        if not isinstance(user, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', user) or destination != 'fixture-threads-' + user:
            raise ValueError('fixture destination mismatch')
    elif platform == 'linkedin':
        from scripts.social.channels.linkedin.direct import preview_marketing_anchor
        author = options.get('author')
        person = re.fullmatch(r'urn:li:person:fixture-([A-Za-z0-9][A-Za-z0-9_-]{0,63})', author) if isinstance(author, str) else None
        org = re.fullmatch(r'urn:li:organization:([1-9][0-9]{0,31})', author) if isinstance(author, str) else None
        expected = ('fixture-linkedin-person-' + person.group(1) if person else
                    'fixture-linkedin-org-' + org.group(1) if org else '')
        if destination != expected:
            raise ValueError('fixture destination mismatch')
        media = options.get('media_urn')
        if media is not None and (not isinstance(media, str) or not re.fullmatch(r'urn:li:(?:image|video):fixture-[A-Za-z0-9_-]{1,100}', media)):
            raise ValueError('fixture media required')
    elif platform == 'youtube':
        from scripts.social.channels.youtube.direct import preview_marketing_anchor
        if not re.fullmatch(r'fixture-youtube-channel-[A-Za-z0-9][A-Za-z0-9_-]{0,63}', destination):
            raise ValueError('fixture destination mismatch')
    else:
        raise ValueError('unsupported fixture platform')
    media_url = options.get('media_url')
    if media_url is not None and (not isinstance(media_url, str) or not _URL.fullmatch(media_url)):
        raise ValueError('fixture media required')
    if media_url is not None:
        kind = options.get('media_type')
        suffix = media_url.rsplit('.', 1)[-1].lower()
        if ((kind == 'IMAGE' and suffix not in ('jpg', 'jpeg', 'png'))
                or (kind in ('VIDEO', 'REELS') and suffix not in ('mp4', 'mov'))):
            raise ValueError('fixture media label mismatch')
    try:
        return preview_marketing_anchor(source=source, **options)
    except TypeError:
        raise ValueError('invalid fixture options') from None


def preview_batch(*, source: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Preview all supplied destinations in memory, or fail without partial output."""
    if (not isinstance(source, str) or len(source) > 32000 or not isinstance(entries, list)
            or not 1 <= len(entries) <= 100):
        raise ValueError('invalid fixture batch')
    entries = copy.deepcopy(entries)
    seen: set[tuple[str, str, str]] = set()
    items = []
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'platform', 'destination', 'occurrence', 'scheduled_at', 'options'}
                or not isinstance(entry['platform'], str) or not isinstance(entry['destination'], str)
                or not _LABEL.fullmatch(entry['destination']) or not isinstance(entry['occurrence'], str)
                or not _LABEL.fullmatch(entry['occurrence']) or not isinstance(entry['options'], dict)):
            raise ValueError('invalid fixture batch entry')
        _fixture_time(entry['scheduled_at'])
        identity = (entry['platform'], entry['destination'], entry['occurrence'])
        if identity in seen:
            raise ValueError('duplicate fixture occurrence')
        seen.add(identity)
        candidate = _preview(entry['platform'], entry['destination'], source, entry['options'], entry['scheduled_at'])
        items.append({'platform': entry['platform'], 'destination': entry['destination'],
                      'occurrence': entry['occurrence'], 'scheduled_at': entry['scheduled_at'], 'candidate': candidate})
    try:
        source_digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise ValueError('invalid fixture source') from None
    return {'preview_only': True, 'source_sha256': source_digest, 'items': items,
            'warnings': ['synthetic_only', 'not_persisted_or_scheduled', 'not_authorized',
                         'identities_and_media_unverified', 'source_not_authenticated']}


def prepare_fixture_batch(ledger: Any, *, source: str, entries: list[dict[str, Any]]) -> list[str]:
    """Build synthetic platform snapshots and atomically persist to caller-owned fixture."""
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    from scripts.social.instagram_v1_fixture_flow import prepare_instagram_v1_fixture
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    from scripts.social.linkedin_v1_fixture_flow import prepare_linkedin_v1_fixture
    from scripts.social.linkedin_v1_media_fixture import prepare_linkedin_v1_media_fixture
    from scripts.social.discord_v1_fixture_flow import prepare_discord_v1_fixture
    from scripts.social.telegram_v1_fixture_flow import prepare_telegram_v1_fixture
    from scripts.social.telegram_v1_media_fixture import prepare_telegram_media_fixture
    from scripts.social.x_v1_fixture_flow import prepare_x_v1_fixture
    from scripts.social.x_v1_media_fixture import prepare_x_media_fixture
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    from scripts.social.threads_v1_fixture_flow import prepare_threads_v1_fixture
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture
    from scripts.social.tiktok_v1_fixture_flow import prepare_tiktok_v1_fixture
    from scripts.social.youtube_fixture_flow import prepare_youtube_native_fixture

    if (type(ledger) is not DestinationFixtureLedger or not isinstance(source, str) or len(source) > 32000
            or not isinstance(entries, list)):
        raise ValueError('invalid fixture batch')
    entries = tuple(entries)
    if not 1 <= len(entries) <= 100:
        raise ValueError('invalid fixture batch')
    entries = copy.deepcopy(entries)
    builders = {'facebook': prepare_facebook_native_fixture, 'instagram': prepare_instagram_fixture,
                'linkedin': prepare_linkedin_fixture, 'threads': prepare_threads_fixture,
                'tiktok': prepare_tiktok_fixture, 'youtube': prepare_youtube_native_fixture,
                'discord': prepare_discord_v1_fixture, 'x': prepare_x_v1_fixture, 'telegram': prepare_telegram_v1_fixture}
    prepared = []
    source_identity: tuple[str, str] | None = None
    publication_header: str | None = None
    publication_posts: dict[str, str] = {}
    publication_anchors: dict[str, str] = {}
    with closing(sqlite3.connect(':memory:')) as con:
        temporary = DestinationFixtureLedger.initialize(con)
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {'platform', 'args'}
                    or not isinstance(entry['platform'], str) or entry['platform'] not in builders
                    or not isinstance(entry['args'], dict) or 'source' in entry['args']
                    or not isinstance(entry['args'].get('key'), dict)
                    or entry['args']['key'].get('platform') != entry['platform']):
                raise ValueError('invalid fixture batch entry')
            identity = (entry['args']['key'].get('campaign_id'), entry['args']['key'].get('content_id'))
            if any(not isinstance(value, str) or not _LEDGER_LABEL.fullmatch(value) for value in identity):
                raise ValueError('invalid fixture source identity')
            if source_identity is None:
                source_identity = identity
            elif identity != source_identity:
                raise ValueError('fixture source identity mismatch')
            if 'publication' in entry['args']:
                try:
                    publication = entry['args']['publication']
                    header = json.dumps({field: publication[field] for field in
                                         ('schema', 'post_id', 'campaign_id', 'channel_id')},
                                        ensure_ascii=False, sort_keys=True, allow_nan=False)
                    posts = publication['posts']
                    if not isinstance(posts, list):
                        raise ValueError('invalid fixture posts')
                    for post in posts:
                        if not isinstance(post, dict) or not isinstance(post.get('post_id'), str):
                            raise ValueError('invalid fixture post')
                        serialized = json.dumps(post, ensure_ascii=False, sort_keys=True, allow_nan=False)
                        previous = publication_posts.setdefault(post['post_id'], serialized)
                        if previous != serialized:
                            raise ValueError('conflicting fixture post')
                        anchor = post.get('post_content')
                        if not isinstance(anchor, str) or not anchor:
                            raise ValueError('invalid fixture post anchor')
                        previous_post = publication_anchors.setdefault(anchor, post['post_id'])
                        if previous_post != post['post_id']:
                            raise ValueError('conflicting fixture anchor')
                except (KeyError, TypeError, ValueError, RecursionError):
                    raise ValueError('invalid fixture publication') from None
                if publication_header is None:
                    publication_header = header
                elif publication_header != header:
                    raise ValueError('fixture publication mismatch')
            try:
                builder = (prepare_telegram_media_fixture if entry['platform'] == 'telegram' and 'manifest' in entry['args']
                           else prepare_x_media_fixture if entry['platform'] == 'x' and 'manifest' in entry['args']
                           else prepare_instagram_v1_fixture if entry['platform'] == 'instagram' and 'publication' in entry['args']
                           else prepare_tiktok_v1_fixture if entry['platform'] == 'tiktok' and 'publication' in entry['args']
                           else prepare_linkedin_v1_media_fixture if entry['platform'] == 'linkedin' and 'publication' in entry['args'] and 'manifest' in entry['args']
                           else prepare_linkedin_v1_fixture if entry['platform'] == 'linkedin' and 'publication' in entry['args']
                           else prepare_threads_v1_fixture if entry['platform'] == 'threads' and 'publication' in entry['args']
                           else prepare_discord_v1_fixture if entry['platform'] == 'discord' and 'publication' in entry['args']
                           else builders[entry['platform']])
                intent = builder(temporary, source=source, **entry['args'])
            except TypeError:
                raise ValueError('invalid fixture batch arguments') from None
            payload = json.loads(temporary.get(intent)['snapshot_json'])['payload']
            prepared.append((entry['args']['key'], payload))
    _validate_batch_media(prepared)
    return ledger.prepare_batch(prepared)


def _validate_batch_media(prepared: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
    """Compare synthetic source labels and LinkedIn media within one batch."""
    shared_assets: dict[tuple[str, str, str], dict[str, set[tuple[str, str]]]] = {}
    linkedin_media: dict[str, tuple[str, str, str, str, str, str]] = {}
    for key, payload in prepared:
        schema = payload.get('fixture_schema')
        if schema not in ('facebook-native-intent/1', 'x-v1-facebook-media/1', 'telegram-v1-image/1',
                          'telegram-v1-video/1', 'linkedin-v1-facebook-media/1'):
            continue
        for asset in payload['manifest']:
            identity = (key['content_id'], key['post_id'], asset['relative_path'])
            by_platform = shared_assets.setdefault(identity, {})
            by_platform.setdefault(key['platform'], set()).add((asset['kind'], asset['id']))
            if schema == 'linkedin-v1-facebook-media/1':
                source_id = (*identity, asset['kind'], asset['id'], payload['author'])
                if linkedin_media.setdefault(payload['media_urn'], source_id) != source_id:
                    raise ValueError('conflicting LinkedIn fixture media')
    for by_platform in shared_assets.values():
        if 'facebook' in by_platform and 'x' in by_platform and (
                len(by_platform['facebook']) != 1 or by_platform['facebook'] != by_platform['x']):
            raise ValueError('conflicting shared fixture asset')
        if 'telegram' in by_platform and len(by_platform['telegram']) != 1:
            raise ValueError('conflicting Telegram fixture asset')
        if 'linkedin' in by_platform and (len(by_platform['linkedin']) != 1 or any(
                values != by_platform['linkedin'] for values in by_platform.values())):
            raise ValueError('conflicting shared LinkedIn fixture asset')


def _shared_publication_entries(publication: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bind V1 fixture destinations to one caller-supplied publication snapshot."""
    publication, entries = copy.deepcopy((publication, entries))
    if (not isinstance(publication, dict) or publication.get('schema') != 'publish/2'
            or not isinstance(publication.get('posts'), list) or not 1 <= len(publication['posts']) <= 100
            or not isinstance(entries, list) or not 1 <= len(entries) <= 100):
        raise ValueError('invalid shared fixture publication')
    post_ids: set[str] = set()
    anchors: set[str] = set()
    for post in publication['posts']:
        if not isinstance(post, dict) or not isinstance(post.get('post_id'), str) or not post['post_id']:
            raise ValueError('invalid shared fixture post')
        if post['post_id'] in post_ids:
            raise ValueError('duplicate shared fixture post')
        post_ids.add(post['post_id'])
        anchor = post.get('post_content')
        if not isinstance(anchor, str) or not anchor or anchor in anchors:
            raise ValueError('invalid shared fixture post anchor')
        anchors.add(anchor)
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'platform', 'args'}
                or entry['platform'] not in ('facebook', 'youtube', 'instagram', 'tiktok', 'linkedin', 'threads', 'discord', 'x', 'telegram') or not isinstance(entry['args'], dict)
                or 'publication' in entry['args'] or 'source' in entry['args']):
            raise ValueError('invalid shared fixture entry')
        entry['args']['publication'] = publication
    return entries


def prepare_v1_fixture_batch(ledger: Any, *, source: str, publication: dict[str, Any],
                             entries: list[dict[str, Any]]) -> list[str]:
    """Prepare Facebook and YouTube fixtures against a single V1 publication."""
    return prepare_fixture_batch(ledger, source=source, entries=_shared_publication_entries(publication, entries))


def preview_v1_file_batch(*, source: str, publication: dict[str, Any],
                          entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build V1 fixture candidates without opening a database or sending requests.

    This preview is not a ledger: cross-batch media ownership and delivery state
    are not verified. Input data and identities must be synthetic fixtures.
    """
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.facebook_fixture_flow import _build as facebook
    from scripts.social.youtube_fixture_flow import _build as youtube
    from scripts.social.instagram_v1_fixture_flow import _build as instagram
    from scripts.social.tiktok_v1_fixture_flow import _build as tiktok
    from scripts.social.linkedin_v1_fixture_flow import _build as linkedin
    from scripts.social.linkedin_v1_media_fixture import _build as linkedin_media
    from scripts.social.threads_v1_fixture_flow import _build as threads
    from scripts.social.discord_v1_fixture_flow import _build as discord
    from scripts.social.x_v1_fixture_flow import _build as x
    from scripts.social.x_v1_media_fixture import _build as x_media
    from scripts.social.telegram_v1_fixture_flow import _build as telegram
    from scripts.social.telegram_v1_media_fixture import _build as telegram_media

    if not isinstance(source, str) or len(source) > 32000:
        raise ValueError('invalid fixture source')
    entries = _shared_publication_entries(publication, entries)
    builders = {'facebook': facebook, 'youtube': youtube, 'instagram': instagram, 'tiktok': tiktok,
                'linkedin': linkedin, 'threads': threads, 'discord': discord, 'x': x, 'telegram': telegram}
    identities: set[tuple[str, ...]] = set()
    items = []
    prepared = []
    for entry in entries:
        platform, args = entry['platform'], entry['args']
        key = args.get('key')
        if not isinstance(key, dict) or key.get('platform') != platform:
            raise ValueError('invalid fixture batch entry')
        builder = (linkedin_media if platform == 'linkedin' and 'manifest' in args else
                   x_media if platform == 'x' and 'manifest' in args else
                   telegram_media if platform == 'telegram' and 'manifest' in args else builders[platform])
        try:
            snapshot = builder(source=source, **args)
            values, digest, raw = DestinationFixtureLedger._encode_prepare(key, snapshot)
        except TypeError:
            raise ValueError('invalid fixture batch arguments') from None
        # A destination occurrence is unique even when account labels differ.
        identity = values[:6] + values[7:]
        if identity in identities:
            raise ValueError('duplicate fixture destination')
        identities.add(identity)
        payload = json.loads(raw)['payload']
        prepared.append((key, payload))
        items.append({'key': key, 'snapshot': payload, 'snapshot_sha256': digest})
    _validate_batch_media(prepared)
    return {'preview_only': True, 'fixture_only': True, 'items': items,
            'warnings': ['not_persisted_or_authorized', 'cross_batch_media_binding_unverified',
                         'no_provider_request_sent']}


def simulate_v1_fixture_batch(*, source: str, publication: dict[str, Any], entries: list[dict[str, Any]],
                              events: list[dict[str, Any]]) -> dict[str, Any]:
    """Simulate a common V1 publication without a network or persistent ledger."""
    return simulate_fixture_batch(source=source, entries=_shared_publication_entries(publication, entries), events=events)


def simulate_fixture_batch(*, source: str, entries: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute explicit synthetic lifecycle events on a disposable in-memory ledger."""
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger

    if not isinstance(events, list):
        raise ValueError('invalid fixture events')
    events = tuple(events)
    if len(events) > 300:
        raise ValueError('invalid fixture events')
    events = copy.deepcopy(events)
    outcomes = []
    with closing(sqlite3.connect(':memory:')) as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_fixture_batch(ledger, source=source, entries=entries)
        indices = {intent: index for index, intent in enumerate(ids)}

        def item_id(index: Any) -> str:
            if type(index) is not int or not 0 <= index < len(ids):
                raise ValueError('invalid fixture event index')
            return ids[index]

        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get('action'), str):
                raise ValueError('invalid fixture event')
            action = event['action']
            if action == 'grant' and set(event) == {'action', 'entries'}:
                grants = event['entries']
                if (not isinstance(grants, list) or not grants or any(not isinstance(item, dict)
                        or set(item) != {'index', 'version'} for item in grants)):
                    raise ValueError('invalid fixture grant')
                ledger.approve_batch([(item_id(item['index']), item['version']) for item in grants])
                outcomes.append({'action': action, 'indices': [item['index'] for item in grants]})
            elif action == 'revoke' and set(event) == {'action', 'index', 'version'}:
                ledger.revoke(item_id(event['index']), expected_version=event['version'])
                outcomes.append({'action': action, 'index': event['index']})
            elif action == 'scan' and set(event) == {'action', 'now'}:
                scanned = ledger.scan_due(now=event['now'])
                ordered = sorted(scanned['due'], key=lambda item: (
                    _fixture_time(json.loads(ledger.get(item)['snapshot_json'])['payload']['scheduled_at']), indices[item]))
                outcomes.append({'action': action, 'due': [indices[item] for item in ordered],
                                 'invalid': [indices[item] for item in scanned['invalid']]})
            elif action == 'claim' and set(event) == {'action', 'index', 'version', 'now'}:
                ledger.claim_due(item_id(event['index']), expected_version=event['version'], now=event['now'])
                outcomes.append({'action': action, 'index': event['index']})
            else:
                raise ValueError('invalid fixture event')
        items = []
        for intent in ids:
            row = ledger.get(intent)
            payload = json.loads(row['snapshot_json'])['payload']
            item = {'platform': row['platform'], 'destination': row['destination_id'],
                          'version': row['version'], 'grant_version': row['grant_version'], 'state': row['state'],
                          'scheduled_at': payload['scheduled_at'], 'candidate': payload['candidate']}
            if row['platform'] == 'tiktok':
                item['fixture_media'] = {field: payload[field] for field in ('source_anchor', 'media_id',
                                         'media_sha256_fixture', 'suggested_caption')}
            if payload.get('fixture_schema') == 'x-v1-facebook-media/1':
                item['fixture_media'] = {**payload['observation'], 'authenticated': False}
            if payload.get('fixture_schema') in ('instagram-v1-infographic/1', 'instagram-v1-reel/1',
                                                  'tiktok-v1-short-inbox/1', 'tiktok-v1-short-direct/1',
                                                  'linkedin-v1-facebook-text/1', 'linkedin-v1-facebook-media/1', 'threads-v1-facebook-text/1',
                                                  'discord-v1-facebook-text/1', 'x-v1-facebook-text/1',
                                                  'x-v1-facebook-media/1', 'telegram-v1-facebook-text/1',
                                                  'telegram-v1-image/1', 'telegram-v1-video/1'):
                source_post = payload['publication']['posts'][0]
                item['source_binding'] = {'channel': source_post['channel'], 'post_id': source_post['post_id'],
                                          'post_format': source_post['post_format'], 'anchor': source_post['post_content']}
                if payload.get('fixture_schema') == 'x-v1-facebook-media/1':
                    item['source_binding'].update(content_id=payload['content_id'], campaign_id=payload['campaign_id'])
                if payload.get('fixture_schema') == 'linkedin-v1-facebook-media/1':
                    item['source_binding'].update(content_id=payload['content_id'], campaign_id=payload['campaign_id'])
                    item['fixture_media'] = {'asset_id': payload['asset']['id'], 'media_kind': payload['media_kind'],
                                             'media_urn': payload['media_urn'], 'authenticated': False}
                if 'source_notes' in payload:
                    item['source_notes'] = payload['source_notes']
                if payload.get('fixture_schema') in ('telegram-v1-image/1', 'telegram-v1-video/1'):
                    item['fixture_media'] = {'media_kind': payload['media_kind'], 'asset_id': payload['manifest'][0]['id'],
                                             'source_caption': payload['source_caption']}
            items.append(item)
    warnings = ['synthetic_grants_not_authority', 'no_network_or_persistent_schedule',
                'submitting_does_not_mean_provider_received']
    if any(item.get('platform') == 'x' and 'fixture_media' in item for item in items):
        warnings.append('media_observation_not_authenticated')
    return {'fixture_only': True, 'items': items, 'events': outcomes, 'warnings': warnings}
