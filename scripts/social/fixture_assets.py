"""Map V1 asset conventions to fake labels without filesystem access.

This mapping is not evidence of file existence, ownership, upload or approval.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from scripts.lib.delivery_anchors import _valid_identity


def _relative(value: Any) -> bool:
    if (not isinstance(value, str) or not value or len(value) > 512 or value != value.strip()
            or any(char in value for char in ('\\', ':', ',', '?', '#'))
            or any(ord(char) < 32 for char in value)):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and bool(path.name) and '..' not in path.parts and str(path) == value


def resolve_fixture_assets(*, content_id: str, post_id: str, platform: str, post_format: str,
                           asset_ref: str, manifest: list[dict[str, str]],
                           attachment_kind: str = 'image') -> dict[str, Any]:
    """Return fake attachment labels and explicit unsupported asset roles."""
    if any(not _valid_identity(value) or not value.startswith('fixture-') for value in (content_id, post_id)):
        raise ValueError('invalid fixture identity')
    if not isinstance(asset_ref, str) or (asset_ref and not _relative(asset_ref)):
        raise ValueError('invalid fixture asset reference')
    if (platform, post_format) == ('youtube', 'youtube_video'):
        if asset_ref:
            raise ValueError('custom video/thumbnail mapping is ambiguous')
        required = {'video.mp4': ('video', 'attachment'), 'thumbnail.png': ('image', 'thumbnail')}
    elif (platform, post_format) == ('youtube', 'youtube_short'):
        if asset_ref:
            raise ValueError('custom short mapping is unsupported')
        required = {'short.mp4': ('video', 'attachment')}
    elif (platform, post_format) == ('facebook', 'reel'):
        if asset_ref:
            raise ValueError('custom reel mapping is unsupported')
        required = {'short.mp4': ('video', 'attachment')}
    elif (platform, post_format) == ('facebook', 'infographic'):
        if not asset_ref or PurePosixPath(asset_ref).suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
            raise ValueError('explicit fixture infographic required')
        required = {asset_ref: ('image', 'attachment')}
    elif (platform, post_format) == ('facebook', 'facebook_post'):
        if attachment_kind == 'video':
            if not asset_ref or PurePosixPath(asset_ref).suffix.lower() != '.mp4':
                raise ValueError('explicit fixture video filename required')
            required = {asset_ref: ('video', 'attachment')}
        elif attachment_kind == 'image':
            if asset_ref and PurePosixPath(asset_ref).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise ValueError('unsupported fixture image filename')
            required = {asset_ref or 'thumbnail.png': ('image', 'attachment')}
        else:
            raise ValueError('unsupported fixture attachment kind')
    else:
        raise ValueError('unsupported fixture asset format')
    if not isinstance(manifest, list) or len(manifest) != len(required):
        raise ValueError('fixture asset manifest incomplete')
    matched = {}
    for entry in manifest:
        if (not isinstance(entry, dict)
                or set(entry) != {'content_id', 'post_id', 'relative_path', 'kind', 'id', 'path'}
                or entry['content_id'] != content_id or entry['post_id'] != post_id
                or not _relative(entry['relative_path']) or entry['relative_path'] not in required
                or entry['relative_path'] in matched or entry['kind'] != required[entry['relative_path']][0]
                or not _valid_identity(entry['id']) or not entry['id'].startswith('fixture-')
                or entry['path'] != '/fixture/' + entry['relative_path']):
            raise ValueError('invalid fixture asset manifest')
        matched[entry['relative_path']] = entry
    media, unmapped = [], []
    for relative_path, (_, role) in required.items():
        entry = matched[relative_path]
        if role == 'attachment':
            media.append({key: entry[key] for key in ('id', 'path', 'kind')})
        else:
            unmapped.append({'relative_path': relative_path, 'role': role})
    return {'fixture_only': True, 'media': media, 'unmapped': unmapped}
