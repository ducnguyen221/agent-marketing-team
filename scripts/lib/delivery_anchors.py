"""Read one explicit marketing anchor without resolving files or approvals."""

from __future__ import annotations

import re
import unicodedata
from typing import TypedDict

_ANCHOR = re.compile(r'post:[a-z0-9_]+(?:#[1-9][0-9]*)?\Z')
_HEADING = re.compile(r'^ {0,3}##[ \t]+(post:[a-z0-9_]+(?:#[1-9][0-9]*)?)[ \t]*$')
_FACEBOOK_ANCHOR = re.compile(r'post:facebook_post(?:#[1-9][0-9]*)?\Z')
_FACEBOOK_META = re.compile(r'^ {0,3}###[ \t]+(comment_1|image_prompt)[ \t]*$')


class FacebookSourceParts(TypedDict):
    body: str
    first_comment: str | None
    image_prompt_present: bool


class FacebookReviewPreview(TypedDict):
    post_id: str
    anchor: str
    body_raw: str
    first_comment_raw: str | None
    image_prompt_present: bool


def _reserved_facebook_heading(label: str) -> bool:
    normalized = unicodedata.normalize('NFKC', label).casefold()
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    return re.match(r'^(?:comment[0-9]+|firstcomment|imageprompt)', normalized) is not None


def _split_frontmatter(content: str) -> tuple[str | None, str]:
    """Separate YAML metadata from Markdown without changing source line endings."""
    if not isinstance(content, str) or len(content) > 32 * 1024 * 1024:
        raise ValueError('invalid or oversized source content')
    try:
        if len(content.encode('utf-8')) > 32 * 1024 * 1024:
            raise ValueError('invalid or oversized source content')
    except UnicodeError:
        raise ValueError('invalid source encoding') from None
    if any(char in content for char in '\v\f\x1c\x1d\x1e\x85\u2028\u2029'):
        raise ValueError('unsupported content line separator')
    content = content.removeprefix('\ufeff')
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip('\r\n') != '---':
        return None, content
    size = 0
    for index, line in enumerate(lines):
        if index == 0:
            continue
        if line.rstrip('\r\n') == '---':
            return ''.join(lines[1:index]), ''.join(lines[index + 1:])
        size += len(line.encode('utf-8'))
        if size > 65536:
            raise ValueError('source metadata is oversized')
    raise ValueError('source metadata is incomplete')


def _valid_identity(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and len(value) <= 512
            and value == value.strip() and '*' not in value
            and not any(unicodedata.category(char).startswith('C') for char in value))


def extract_delivery_anchor(content: str, anchor: str) -> str:
    """Return one raw source block; never render, clean or authorize it.

    Only top-level Markdown h2 anchors in the canonical physical-line form are
    accepted. Fenced code, comments, quotes and indented code are not headings.
    This function does not validate the source path, the post/target mapping,
    or the content and assets to be published.
    """
    if not isinstance(content, str) or not isinstance(anchor, str) or not _ANCHOR.fullmatch(anchor):
        raise ValueError('invalid content anchor')
    _, content = _split_frontmatter(content)
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        raise ValueError('Markdown parser is unavailable') from None
    lines = content.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark', {'html': True}).parse(content)
    anchors: list[tuple[str, int, int]] = []
    for index, token in enumerate(tokens):
        if token.type != 'heading_open' or token.tag != 'h2' or token.level != 0:
            continue
        if token.map is None or index + 1 >= len(tokens):
            raise ValueError('Markdown heading location is unavailable')
        inline = tokens[index + 1]
        if inline.type != 'inline' or not inline.content.startswith('post:'):
            continue
        start, after = token.map
        if start < 0 or after != start + 1 or start >= len(lines):
            raise ValueError('unsupported content anchor heading')
        match = _HEADING.fullmatch(lines[start].rstrip('\r\n'))
        if match is None or match.group(1) != inline.content:
            raise ValueError('unsupported content anchor heading')
        anchors.append((match.group(1), start, after))
    matching = [i for i, item in enumerate(anchors) if item[0] == anchor]
    if len(matching) != 1:
        raise ValueError('content anchor must occur exactly once')
    index = matching[0]
    start = anchors[index][2]
    end = anchors[index + 1][1] if index + 1 < len(anchors) else len(lines)
    block = ''.join(lines[start:end])
    if not block.strip():
        raise ValueError('content anchor block is empty')
    return block


def split_facebook_source(content: str, anchor: str) -> FacebookSourceParts:
    """Split one raw Facebook source into body/comment and an image-prompt flag.

    Values remain raw Markdown and can contain writing instructions, template
    markers or unresolved placeholders. They are not publish-ready and this
    function does not authenticate a user, inspect files or grant approval.
    """
    if not isinstance(anchor, str) or not _FACEBOOK_ANCHOR.fullmatch(anchor):
        raise ValueError('Facebook content anchor is required')
    block = extract_delivery_anchor(content, anchor)
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        raise ValueError('Markdown parser is unavailable') from None
    lines = block.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark', {'html': True}).parse(block)
    markers: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for index, token in enumerate(tokens):
        if token.type != 'heading_open':
            continue
        if token.map is None or index + 1 >= len(tokens) or tokens[index + 1].type != 'inline':
            raise ValueError('Facebook section location is unavailable')
        inline = tokens[index + 1]
        label = inline.content
        rendered = ''.join(child.content for child in (inline.children or [])
                           if child.type in {'text', 'code_inline'})
        reserved = _reserved_facebook_heading(label) or _reserved_facebook_heading(rendered)
        if reserved and (token.tag != 'h3' or token.level != 0 or label not in {'comment_1', 'image_prompt'}):
            raise ValueError('unsupported Facebook metadata heading')
        if token.tag != 'h3' or token.level != 0:
            if markers and token.level == 0:
                raise ValueError('unsupported section after Facebook metadata')
            continue
        if label not in {'comment_1', 'image_prompt'}:
            if markers:
                raise ValueError('unsupported section after Facebook metadata')
            continue
        start, after = token.map
        if start < 0 or after != start + 1 or start >= len(lines):
            raise ValueError('unsupported Facebook metadata heading')
        match = _FACEBOOK_META.fullmatch(lines[start].rstrip('\r\n'))
        if (match is None or match.group(1) != label or label in seen
                or (label == 'comment_1' and 'image_prompt' in seen)):
            raise ValueError('invalid or duplicate Facebook metadata heading')
        seen.add(label)
        markers.append((label, start, after))
    body_end = markers[0][1] if markers else len(lines)
    body = ''.join(lines[:body_end])
    if not body.strip():
        raise ValueError('Facebook source body is empty')
    comment = None
    for index, (label, _start, after) in enumerate(markers):
        end = markers[index + 1][1] if index + 1 < len(markers) else len(lines)
        if label == 'comment_1':
            comment = ''.join(lines[after:end])
            if not comment.strip():
                raise ValueError('Facebook source comment is empty')
    return {'body': body, 'first_comment': comment, 'image_prompt_present': 'image_prompt' in seen}


def preview_facebook_post(content: str, publication: dict, *, post_id: str) -> FacebookReviewPreview:
    """Make a raw, per-post review preview from caller-supplied source data.

    The caller must obtain content and publication from the same verified source.
    This performs no file I/O, approval, sanitization, or dispatch and must not
    be treated as a publish envelope. Raw text can include instructions or PII.
    """
    if (not isinstance(content, str) or not _valid_identity(post_id)
            or not isinstance(publication, dict) or publication.get('schema') != 'publish/2'):
        raise ValueError('invalid Facebook preview request')
    posts = publication.get('posts')
    if not isinstance(posts, list) or any(not isinstance(post, dict) for post in posts):
        raise ValueError('invalid Facebook preview request')
    header, _ = _split_frontmatter(content)
    if header is None:
        raise ValueError('source content identity is unavailable')
    try:
        import yaml
    except ImportError:
        raise ValueError('source content identity parser is unavailable') from None
    class UniqueSafeLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            if any(key.tag == 'tag:yaml.org,2002:merge' for key, _ in node.value):
                raise ValueError('metadata merge is unsupported')
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in result:
                    raise ValueError('invalid or duplicate metadata key')
                result[key] = self.construct_object(value_node, deep=deep)
            return result

    try:
        frontmatter = yaml.load(header, Loader=UniqueSafeLoader)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError, UnicodeError):
        raise ValueError('source content identity is unavailable') from None
    if (not isinstance(frontmatter, dict) or frontmatter.get('schema') != 'content/1'
            or not _valid_identity(publication.get('post_id'))
            or not _valid_identity(publication.get('campaign_id'))
            or frontmatter.get('content_id') != publication['post_id']
            or frontmatter.get('campaign_id') != publication['campaign_id']):
        raise ValueError('source content identity does not match publication')
    matches = [post for post in posts if post.get('post_id') == post_id]
    if len(matches) != 1:
        raise ValueError('Facebook post is missing or ambiguous')
    post = matches[0]
    anchor = post.get('post_content')
    if (post.get('content_id') != publication['post_id']
            or post.get('channel') != 'facebook' or post.get('post_format') != 'facebook_post'
            or not isinstance(anchor, str) or not _FACEBOOK_ANCHOR.fullmatch(anchor)):
        raise ValueError('Facebook post format or anchor is invalid')
    if sum(1 for item in posts if item.get('post_content') == anchor) != 1:
        raise ValueError('Facebook anchor is shared by multiple posts')
    parts = split_facebook_source(content, anchor)
    return {'post_id': post_id, 'anchor': anchor, 'body_raw': parts['body'],
            'first_comment_raw': parts['first_comment'],
            'image_prompt_present': parts['image_prompt_present']}
