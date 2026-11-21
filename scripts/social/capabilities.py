"""Offline V2 action catalogue; entries never enable a real provider route.

`fixture_preview` denotes only candidate generation with synthetic inputs.
It is not evidence of permissions, account support, upload, dispatch or UAT.
"""
from __future__ import annotations

# Keys are platform, destination type, action. Methods describe the intended
# execution path and do not assert a platform currently supports that path.
_ACTIONS = {
    ('facebook', 'page', 'post_text'): (('api',), True),
    ('facebook', 'page', 'post_image'): (('api',), True),
    ('facebook', 'page', 'post_video'): (('api',), True),
    ('facebook', 'page', 'post_reel'): (('api',), True),
    ('facebook', 'group', 'post_image'): (('ui', 'manual'), False),
    ('facebook', 'group', 'post_text'): (('ui', 'manual'), False),
    ('facebook', 'group', 'post_video'): (('ui', 'manual'), False),
    ('youtube', 'channel', 'post_video'): (('api',), True),
    ('instagram', 'account', 'post_image'): (('api',), True),
    ('instagram', 'account', 'post_video'): (('api',), True),
    ('linkedin', 'account', 'post_text'): (('api',), True),
    ('linkedin', 'account', 'post_image'): (('api',), True),
    ('linkedin', 'account', 'post_video'): (('api',), True),
    ('threads', 'account', 'post_text'): (('api',), True),
    ('threads', 'account', 'post_image'): (('api',), True),
    ('threads', 'account', 'post_video'): (('api',), True),
    ('discord', 'channel', 'post_text'): (('api',), True),
    ('telegram', 'channel', 'post_text'): (('api',), True),
    ('telegram', 'channel', 'post_image'): (('api',), True),
    ('telegram', 'channel', 'post_video'): (('api',), True),
    ('x', 'account', 'post_text'): (('api',), True),
    ('tiktok', 'profile', 'upload_video'): (('api',), True),
    ('tiktok', 'profile', 'post_video'): (('api',), True),
    ('tiktok', 'profile', 'create_duet'): (('ui', 'manual'), False),
    ('tiktok', 'profile', 'create_stitch'): (('ui', 'manual'), False),
}

_NATIVE_PREVIEWS = {('linkedin', 'account', action): 'linkedin_native'
                    for action in ('post_text', 'post_image', 'post_video')}
_NATIVE_PREVIEWS.update({('facebook', 'page', action): 'facebook_native'
                         for action in ('post_text', 'post_image', 'post_video')})
_NATIVE_PREVIEWS.update({('threads', 'account', action): 'threads_native'
                         for action in ('post_text', 'post_image', 'post_video')})
_NATIVE_PREVIEWS.update({('tiktok', 'profile', action): 'tiktok_native'
                         for action in ('upload_video', 'post_video')})
_NATIVE_PREVIEWS.update({('instagram', 'account', action): 'instagram_native'
                         for action in ('post_image', 'post_video')})
_NATIVE_PREVIEWS[('youtube', 'channel', 'post_video')] = 'youtube_native'
_NATIVE_PREVIEWS[('facebook', 'page', 'post_reel')] = 'facebook_reel_start'
_NATIVE_PREVIEWS[('discord', 'channel', 'post_text')] = 'discord_native'
_NATIVE_PREVIEWS[('telegram', 'channel', 'post_text')] = 'telegram_native'
_NATIVE_PREVIEWS[('telegram', 'channel', 'post_image')] = 'telegram_native'
_NATIVE_PREVIEWS[('telegram', 'channel', 'post_video')] = 'telegram_native'
_NATIVE_PREVIEWS[('x', 'account', 'post_text')] = 'x_native'


def capabilities(*, platform: str, destination: str, action: str) -> dict[str, object]:
    """Describe a known planned or exercised action without granting authority."""
    if any(not isinstance(value, str) for value in (platform, destination, action)):
        raise ValueError('invalid fixture capability')
    entry = _ACTIONS.get((platform, destination, action))
    if entry is None:
        raise ValueError('unknown fixture capability')
    methods, supported = entry
    key = (platform, destination, action)
    preview_schema = _NATIVE_PREVIEWS.get(key)
    if supported and preview_schema is None:
        raise ValueError('fixture preview schema missing')
    return {'platform': platform, 'destination': destination, 'action': action,
            'planned_methods': list(methods), 'fixture_preview': supported, 'live_enabled': False,
            'preview_schema': preview_schema,
            'scope': 'offline_candidate_only' if supported else 'planned',
            'requires_account_validation': True}


def list_capabilities() -> list[dict[str, object]]:
    """List known actions in deterministic order, returning fresh objects."""
    return [capabilities(platform=platform, destination=destination, action=action)
            for platform, destination, action in sorted(_ACTIONS)]
