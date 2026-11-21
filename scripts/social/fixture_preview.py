"""Build an offline candidate from caller-supplied synthetic marketing text.

This does not authenticate, resolve paths, upload media, approve or publish.
The fake labels do not represent real Postiz uploads or a V1-to-V2 grant.
"""
from __future__ import annotations

import re
from typing import Any

from scripts.lib.delivery_anchors import _split_frontmatter, _valid_identity, extract_delivery_anchor, split_facebook_source
from scripts.lib.postiz_payload import build_postiz_create_candidate

_ANCHORS = {
    'facebook': {'post:facebook_post'},
    'youtube': {'post:youtube_desc'},
    'linkedin': {'post:linkedin_post'},  # synthetic extension; not a V1 enum
    'instagram': {'post:infographic'},
    # These anchors are synthetic extensions, not supported V1 data-model values.
    'threads': {'post:threads_post'},
    'discord': {'post:discord_post'},
    'x': {'post:x_post'},
    'tiktok': {'post:tiktok_post'},
}


def preview_fixture(*, source: str, anchor: str, integration_id: str, provider: str,
                    media: list[dict[str, str]], settings: dict[str, Any],
                    date_utc: str) -> dict[str, Any]:
    """Convert one synthetic anchor to a candidate, without reading any file."""
    if (not isinstance(integration_id, str) or not integration_id.startswith('fixture-')
            or not isinstance(media, list) or len(media) > 100):
        raise ValueError('fixture inputs required')
    if (not isinstance(anchor, str) or not isinstance(provider, str)
            or re.sub(r'#[1-9][0-9]*$', '', anchor) not in _ANCHORS.get(provider, set())):
        raise ValueError('fixture anchor and provider mismatch')
    if provider == 'discord' and (not isinstance(settings, dict) or set(settings) != {'__type', 'channel'}):
        raise ValueError('unsupported fixture settings')
    for entry in media:
        if (not isinstance(entry, dict) or not isinstance(entry.get('id'), str)
                or not entry['id'].startswith('fixture-') or not isinstance(entry.get('path'), str)
                or not entry['path'].startswith('/fixture/') or '..' in entry['path']):
            raise ValueError('fixture media required')
    first_comment = None
    if provider == 'facebook' and anchor.startswith('post:facebook_post'):
        parts = split_facebook_source(source, anchor)
        content = parts['body']
        first_comment = parts['first_comment']
    else:
        content = extract_delivery_anchor(source, anchor)
        if provider in {'linkedin', 'threads', 'discord', 'x', 'tiktok'}:
            from markdown_it import MarkdownIt
            tokens = MarkdownIt('commonmark', {'html': True}).parse(content)
            if any(token.type in {'heading_open', 'html_block'}
                   or any(child.type == 'html_inline' for child in (token.children or [])) for token in tokens):
                raise ValueError('unsupported fixture metadata')
            # A terminal newline belongs to the Markdown file, not the post.
            content = content.removesuffix('\n').removesuffix('\r')
        if provider == 'instagram':
            from markdown_it import MarkdownIt
            lines = content.splitlines()
            matches = []
            caption_end = None
            for token in MarkdownIt('commonmark').parse(content):
                if token.type != 'paragraph_open' or token.level != 0 or token.map is None:
                    continue
                start, end = token.map
                if lines[start].startswith('**Caption:**'):
                    if end != start + 1:
                        raise ValueError('fixture caption is multiline')
                    match = re.fullmatch(r'\*\*Caption:\*\*[ \t]*(\S.*?)[ \t]*', lines[start])
                    if match is None or '<' in match.group(1) or '>' in match.group(1):
                        raise ValueError('invalid fixture caption')
                    matches.append(match.group(1))
                    caption_end = end
            if len(matches) != 1:
                raise ValueError('fixture caption is missing or ambiguous')
            if any(line.strip() not in ('', '---') for line in lines[caption_end:]):
                raise ValueError('unsupported content after fixture caption')
            # Structured infographic data is not a caption. Only the single
            # explicit line is previewed; multiline captions need a new parser.
            content = matches[0].strip()
    candidate = build_postiz_create_candidate(
        integration_id=integration_id, provider=provider, content=content, uploaded_media=media,
        mode='schedule', date_utc=date_utc, settings=settings, first_comment=first_comment)
    warnings = ['synthetic_only', 'not_approved', 'media_not_uploaded', 'provider_unverified']
    if provider == 'tiktok' and settings.get('content_posting_method') == 'UPLOAD':
        warnings.append('awaiting_creator')
        warnings.append('upload_ignores_some_settings')
    if provider == 'x':
        warnings.append('x_weighted_length_unchecked')
    return {'preview_only': True, 'candidate': candidate, 'warnings': warnings}


def preview_v1_fixture(*, source: str, publication: dict[str, Any], post_id: str,
                       integration_id: str, provider: str, media: list[dict[str, str]],
                       settings: dict[str, Any], date_utc: str) -> dict[str, Any]:
    """Bind supplied V1-shaped fixture documents; never verify ownership or approval.

    No file is opened. Synthetic IDs are required. The source and publication
    must come from a caller-controlled fixture, not from a real station.
    Media are synthetic labels and are not bound to V1 asset paths.
    """
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        def construct_mapping(self, node: Any, deep: bool = False) -> dict[str, Any]:
            result = {}
            for key_node, value_node in node.value:
                if key_node.tag == 'tag:yaml.org,2002:merge':
                    raise ValueError('fixture metadata merge is not supported')
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in result:
                    raise ValueError('invalid fixture metadata')
                result[key] = self.construct_object(value_node, deep=deep)
            return result

    header, _ = _split_frontmatter(source)
    if header is None:
        raise ValueError('fixture source identity missing')
    try:
        metadata = yaml.load(header, Loader=UniqueLoader)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        raise ValueError('fixture source identity invalid') from None
    if not isinstance(publication, dict) or not isinstance(metadata, dict):
        raise ValueError('invalid fixture source')
    ids = (post_id, publication.get('post_id'), publication.get('campaign_id'), publication.get('channel_id'))
    if (any(not _valid_identity(value) or not value.startswith('fixture-') or len(value) > 256 for value in ids)
            or publication.get('schema') != 'publish/2' or metadata.get('schema') != 'content/1'
            or metadata.get('content_id') != publication['post_id']
            or metadata.get('campaign_id') != publication['campaign_id']):
        raise ValueError('fixture source identity mismatch')
    posts = publication.get('posts')
    if not isinstance(posts, list) or len(posts) > 100 or any(not isinstance(row, dict) for row in posts):
        raise ValueError('invalid fixture posts')
    matches = [row for row in posts if row.get('post_id') == post_id]
    if len(matches) != 1:
        raise ValueError('fixture post is missing or ambiguous')
    row = matches[0]
    contract = {'facebook': ('facebook_post', 'post:facebook_post'),
                'youtube': ('youtube_video', 'post:youtube_desc')}.get(provider)
    anchor = row.get('post_content')
    if (contract is None or row.get('content_id') != publication['post_id']
            or row.get('channel') != provider or row.get('post_format') != contract[0]
            or not isinstance(anchor, str)
            or re.sub(r'#[1-9][0-9]*$', '', anchor) != contract[1]
            or sum(item.get('post_content') == anchor for item in posts) != 1):
        raise ValueError('fixture post contract mismatch')
    result = preview_fixture(source=source, anchor=anchor, integration_id=integration_id,
                             provider=provider, media=media, settings=settings, date_utc=date_utc)
    result['source_post_id'] = post_id
    result['warnings'].extend(['v1_approval_not_inherited', 'v1_brand_not_verified',
                               'media_not_bound_to_v1_asset'])
    return result


def preview_v1_with_assets_fixture(*, source: str, publication: dict[str, Any], post_id: str,
                                   integration_id: str, provider: str, manifest: list[dict[str, str]],
                                   settings: dict[str, Any], date_utc: str) -> dict[str, Any]:
    """Bind V1-shaped fixture metadata to synthetic asset labels and preview."""
    from scripts.social.fixture_assets import resolve_fixture_assets
    if not isinstance(publication, dict) or not isinstance(publication.get('posts'), list):
        raise ValueError('invalid fixture posts')
    posts = publication['posts']
    if len(posts) > 100 or any(not isinstance(row, dict) for row in posts):
        raise ValueError('invalid fixture posts')
    rows = [row for row in posts if row.get('post_id') == post_id]
    if len(rows) != 1:
        raise ValueError('fixture post is missing or ambiguous')
    row = rows[0]
    assets = resolve_fixture_assets(content_id=publication.get('post_id'), post_id=post_id,
                                    platform=provider, post_format=row.get('post_format'),
                                    asset_ref=row.get('asset_ref'), manifest=manifest)
    result = preview_v1_fixture(source=source, publication=publication, post_id=post_id,
                                integration_id=integration_id, provider=provider, media=assets['media'],
                                settings=settings, date_utc=date_utc)
    result['unmapped_assets'] = assets['unmapped']
    result['warnings'].remove('media_not_bound_to_v1_asset')
    result['warnings'].append('fixture_manifest_labels_matched_files_unverified')
    return result
