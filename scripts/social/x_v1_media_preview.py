"""Preview one synthetic V1 Facebook attachment in an X post; no ledger or I/O."""
from __future__ import annotations

import re
from typing import Any

from scripts.lib.delivery_anchors import preview_facebook_post
from scripts.social.channels.x.direct import preview_post
from scripts.social.fixture_assets import resolve_fixture_assets


def preview_v1_media(*, source: str, publication: dict[str, Any], post_id: str,
                     manifest: list[dict[str, str]], media_kind: str, user_id: str,
                     media_id: str, adapted_text: str) -> dict[str, Any]:
    """Map one explicit V1 attachment to an untrusted, hypothetical X media ID."""
    if (not isinstance(source, str) or len(source) > 32000 or not isinstance(publication, dict)
            or media_kind not in ('image', 'video') or not isinstance(user_id, str)
            or not re.fullmatch(r'[1-9][0-9]{0,31}', user_id) or not isinstance(media_id, str)
            or not re.fullmatch(r'fixture-x-media-[A-Za-z0-9_-]{1,100}', media_id)):
        raise ValueError('invalid X V1 media preview')
    preview = preview_facebook_post(source, publication, post_id=post_id)
    post = next(item for item in publication['posts'] if item.get('post_id') == post_id)
    asset_ref = post.get('asset_ref')
    if not isinstance(asset_ref, str) or not asset_ref:
        raise ValueError('explicit fixture attachment required')
    if (not isinstance(adapted_text, str) or adapted_text.replace('\r\n', '\n').strip()
            == preview['body_raw'].replace('\r\n', '\n').strip()):
        raise ValueError('separately adapted X text required')
    media = resolve_fixture_assets(content_id=publication['post_id'], post_id=post_id, platform='facebook',
                                   post_format='facebook_post', asset_ref=asset_ref, manifest=manifest,
                                   attachment_kind=media_kind)['media'][0]
    candidate = preview_post(text=adapted_text)
    candidate['request']['body']['media'] = {'media_ids': [media_id]}
    return {'fixture_only': True, 'preview_only': True, 'user_id': user_id,
            'source_binding': {'channel': 'facebook', 'post_id': post_id, 'post_format': 'facebook_post',
                               'content_id': publication['post_id'], 'campaign_id': publication['campaign_id'],
                               'anchor': preview['anchor']},
            'asset': media, 'candidate': candidate,
            'source_notes': {'first_comment_omitted': bool(preview['first_comment_raw']),
                             'image_prompt_omitted': preview['image_prompt_present']},
            'warnings': ['synthetic_only', 'not_persisted_or_scheduled', 'media_not_uploaded',
                         'media_processing_and_ownership_unverified', 'media_id_is_caller_supplied_fixture']}
