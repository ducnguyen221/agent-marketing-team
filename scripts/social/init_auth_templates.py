"""Create empty example files; no authentication, token reads or connections.

The command writes only fixed *.example.json names, never active V1 config.
The helper accepts a test-owned root for tests; CLI fixes the user secret root.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

PLATFORMS = ('facebook', 'instagram', 'youtube', 'linkedin', 'tiktok', 'threads', 'x', 'discord', 'telegram')
_SOURCE = Path(__file__).resolve().parents[2] / 'templates' / 'social_auth'
_FIELDS = {
    'facebook': {'app_id', 'app_secret', 'page_id', 'page_token'},
    'instagram': {'login_product', 'app_id', 'app_secret', 'instagram_account_id', 'access_token'},
    'youtube': {'oauth_client_json_path', 'authorized_user_token_path', 'channel_id'},
    'linkedin': {'client_id', 'client_secret', 'redirect_uri', 'access_token', 'refresh_token_if_available',
                 'author_type', 'author_urn', 'requested_scopes', 'granted_scopes_verified'},
    'tiktok': {'client_key', 'client_secret', 'redirect_uri', 'access_token', 'refresh_token', 'open_id', 'posting_method'},
    'threads': {'app_id', 'app_secret', 'redirect_uri', 'access_token', 'threads_user_id'},
    'x': {'auth_scheme', 'client_id', 'client_secret_if_applicable', 'redirect_uri', 'access_token',
          'refresh_token_if_available', 'user_id'},
    'discord': {'application_id', 'bot_token', 'guild_id', 'channel_id'},
    'telegram': {'bot_purpose', 'bot_token', 'chat_id'},
}


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate template field')
        result[key] = value
    return result


def _safe_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise ValueError('template directory unavailable') from None
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('linked template directories are unsupported')


def _template(platform: str) -> bytes:
    path = _SOURCE / f'{platform}.example.json'
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & 0x400 or info.st_size > 16384):
        raise ValueError('invalid template source')
    with path.open('rb') as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('invalid template source')
    data = json.loads(raw, object_pairs_hook=_unique_pairs)
    if (not isinstance(data, dict) or set(data) != {'schema', 'template_only', 'platform', 'fields'}
            or data['schema'] != 'social-auth-template/1' or data['template_only'] is not True
            or data['platform'] != platform or not isinstance(data['fields'], dict)
            or set(data['fields']) != _FIELDS[platform]
            or any(not isinstance(key, str) or value is not None for key, value in data['fields'].items())):
        raise ValueError('invalid template source')
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def create_templates(root: Path) -> dict[str, list[str]]:
    """Create missing fixed templates in a pre-existing root; do not read destinations."""
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError('invalid template root')
    _safe_directory(root)
    # Validate every repository template before writing anything.
    sources = {platform: _template(platform) for platform in PLATFORMS}
    directory = root / '_social-auth-templates'
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _safe_directory(directory)
    result: dict[str, list[str]] = {'created': [], 'existing_unverified': [], 'failed': []}
    for platform in PLATFORMS:
        path = directory / f'{platform}.example.json'
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(sources[platform])
            result['created'].append(platform)
        except FileExistsError:
            result['existing_unverified'].append(platform)
        except OSError:
            # A partial file may remain; do not delete or overwrite it.
            result['failed'].append(platform)
    return result


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'invalid template request\n')


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description='Create empty social authentication examples', allow_abbrev=False)
    parser.add_argument('--create-examples', action='store_true')
    args = parser.parse_args(argv)
    if not args.create_examples:
        print('example creation not requested', file=sys.stderr)
        return 2
    try:
        result = create_templates(Path.home() / '.secret')
        print(json.dumps(result))
        return 2 if result['failed'] else 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        print('could not create examples', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
