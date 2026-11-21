"""Create empty read-only profile examples; never read destination files or tokens."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from scripts.social.init_auth_templates import _SOURCE, _safe_directory, _unique_pairs

_TEMPLATES = {
    'facebook-page-userinfo': ('facebook', {'schema', 'provider', 'token_kind', 'app_id', 'expected_page_id', 'api_version', 'access_token'}),
    'instagram-facebook-userinfo': ('instagram', {'schema', 'provider', 'login_product', 'token_kind', 'app_id', 'expected_page_id', 'expected_instagram_id', 'api_version', 'access_token'}),
    'youtube-channel-userinfo': ('youtube', {'schema', 'provider', 'token_kind', 'client_id', 'expected_channel_id', 'access_token'}),
    'linkedin-userinfo': ('linkedin', {'schema', 'provider', 'token_kind', 'client_id', 'person_urn', 'access_token'}),
    'tiktok-userinfo': ('tiktok', {'schema', 'provider', 'token_kind', 'client_key', 'expected_open_id', 'access_token'}),
    'threads-userinfo': ('threads', {'schema', 'provider', 'token_kind', 'app_id', 'expected_user_id', 'api_version', 'access_token'}),
    'x-userinfo': ('x', {'schema', 'provider', 'token_kind', 'client_id', 'expected_user_id', 'access_token'}),
    'discord-bot-userinfo': ('discord', {'schema', 'provider', 'token_kind', 'application_id', 'expected_bot_id', 'bot_token'}),
    'telegram-publish-bot-userinfo': ('telegram', {'schema', 'provider', 'purpose', 'expected_bot_id', 'bot_token'}),
}
_STATIC = {'schema', 'provider', 'token_kind', 'login_product', 'purpose'}
_STATIC_VALUES = {
    'facebook-page-userinfo': {'token_kind': 'page_access_token'},
    'instagram-facebook-userinfo': {'login_product': 'facebook_login', 'token_kind': 'facebook_user_access_token'},
    'youtube-channel-userinfo': {'token_kind': 'oauth_access_token'},
    'linkedin-userinfo': {'token_kind': 'oauth_access_token'},
    'tiktok-userinfo': {'token_kind': 'oauth_access_token'},
    'threads-userinfo': {'token_kind': 'threads_user_access_token'},
    'x-userinfo': {'token_kind': 'oauth2_user_access_token'},
    'discord-bot-userinfo': {'token_kind': 'bot_token'},
    'telegram-publish-bot-userinfo': {'purpose': 'publish'},
}


def _source_template(name: str, provider: str, fields: set[str]) -> bytes:
    path = _SOURCE / f'{name}.example.json'
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & 0x400 or info.st_size > 16384):
        raise ValueError('invalid template source')
    with path.open('rb') as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('invalid template source')
    data: Any = json.loads(raw, object_pairs_hook=_unique_pairs)
    if (not isinstance(data, dict) or set(data) != fields or data.get('schema') != f'{name}/1'
            or data.get('provider') != provider
            or any(value is not None for key, value in data.items() if key not in _STATIC)
            or any(data.get(key) != value for key, value in _STATIC_VALUES[name].items())):
        raise ValueError('invalid template source')
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def create_readonly_examples(root: Path) -> dict[str, list[str]]:
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError('invalid template root')
    _safe_directory(root)
    sources = {name: _source_template(name, provider, fields) for name, (provider, fields) in _TEMPLATES.items()}
    directory = root / '_social-auth-templates'
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _safe_directory(directory)
    result: dict[str, list[str]] = {'created': [], 'existing_unverified': [], 'failed': []}
    for name, raw in sources.items():
        try:
            fd = os.open(directory / f'{name}.example.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
            result['created'].append(name)
        except FileExistsError:
            result['existing_unverified'].append(name)
        except OSError:
            result['failed'].append(name)
    return result


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'invalid template request\n')


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description='Create empty read-only social examples', allow_abbrev=False)
    parser.add_argument('--create-examples', action='store_true')
    args = parser.parse_args(argv)
    if not args.create_examples:
        print('example creation not requested', file=sys.stderr)
        return 2
    try:
        result = create_readonly_examples(Path.home() / '.secret')
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        print('could not create examples', file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 2 if result['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
