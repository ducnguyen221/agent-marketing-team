"""Discord bot and guild channel GETs without Gateway or message delivery."""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from scripts.social.channels.linkedin.readonly_auth import (
    _PROFILE, _TOKEN, _reject_constant, _unique, _unlinked,
)

_ID = re.compile(r'[1-9][0-9]{0,31}\Z')
_MAX_BODY = 65536
_ERROR_FIELDS = ('code', 'message', 'errors', 'error', 'status', 'title', 'detail')


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value)) and int(value) <= 2**64 - 1


def interpret_bot(status: int, body: Any, *, expected_bot_id: str) -> dict[str, Any]:
    if not _valid_id(expected_bot_id):
        raise ValueError('invalid expected identity')
    result: dict[str, Any] = {'identity': 'unknown', 'profile_binding_verified': False,
                              'app_binding_verified': False, 'channel_access_verified': False,
                              'publish_authorized': False}
    if (type(status) is not int or status != 200 or not isinstance(body, dict) or body.get('bot') is not True
            or any(key in body for key in (*_ERROR_FIELDS, 'type'))):
        return result
    observed = body.get('id')
    if _valid_id(observed):
        result['identity'] = 'match' if observed == expected_bot_id else 'mismatch'
    return result


def _get_json(bot_token: str, path: str) -> Any:
    if not isinstance(bot_token, str) or not _TOKEN.fullmatch(bot_token):
        raise ValueError('invalid credential')
    connection = None
    try:
        connection = http.client.HTTPSConnection('discord.com', timeout=10)
        connection.request('GET', path, headers={
            'Authorization': 'Bot ' + bot_token, 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            return None
        raw = response.read(_MAX_BODY + 1)
        if len(raw) > _MAX_BODY:
            return None
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_reject_constant)
    except (OSError, http.client.HTTPException, ValueError, UnicodeError, RecursionError):
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def check_bot(bot_token: str, expected_bot_id: str) -> dict[str, Any]:
    """Perform a single fixed-host GET and return no token or account data."""
    if not _valid_id(expected_bot_id):
        raise ValueError('invalid expected identity')
    body = _get_json(bot_token, '/api/v10/users/@me')
    return interpret_bot(200, body, expected_bot_id=expected_bot_id)


def check_bot_channel(
    bot_token: str, *, expected_bot_id: str, channel_id: str, guild_id: str,
) -> dict[str, Any]:
    """Verify the same bot credential can read the expected guild channel."""
    if not _valid_id(channel_id) or not _valid_id(guild_id):
        raise ValueError('invalid Discord target')
    result = check_bot(bot_token, expected_bot_id)
    if result['identity'] != 'match':
        return result
    body = _get_json(bot_token, f'/api/v10/channels/{channel_id}')
    result['channel_access_verified'] = (
        isinstance(body, dict)
        and not any(key in body for key in _ERROR_FIELDS)
        and body.get('id') == channel_id
        and body.get('guild_id') == guild_id
        and type(body.get('type')) is int
        and body['type'] in {0, 5}
    )
    return result


def check_profile(root: Path, alias: str) -> dict[str, Any]:
    """Read a named bot profile from a root trusted by the caller."""
    if (not isinstance(root, Path) or not root.is_absolute() or '..' in root.parts
            or str(root).startswith(('\\\\', '//')) or any(':' in part for part in root.parts[1:])
            or not isinstance(alias, str) or not _PROFILE.fullmatch(alias)
            or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', alias)):
        raise ValueError('invalid profile request')
    try:
        root_info = _unlinked(root, directory=True)
        folder = root / alias
        folder_info = _unlinked(folder, directory=True)
        path = folder / 'discord-bot-userinfo.json'
        file_info = _unlinked(path, directory=False)
        if file_info.st_size > 16384:
            raise ValueError('invalid profile')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (file_info.st_dev, file_info.st_ino)
                    or getattr(opened, 'st_file_attributes', 0) & 0x400):
                raise ValueError('invalid profile location')
            for location, previous in ((root, root_info), (folder, folder_info)):
                current = _unlinked(location, directory=True)
                if (current.st_dev, current.st_ino) != (previous.st_dev, previous.st_ino):
                    raise ValueError('invalid profile location')
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError('invalid profile')
        obj = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_reject_constant)
        if (not isinstance(obj, dict) or set(obj) != {'schema', 'provider', 'token_kind', 'application_id',
                                                       'expected_bot_id', 'bot_token'}
                or obj['schema'] != 'discord-bot-userinfo/1' or obj['provider'] != 'discord'
                or obj['token_kind'] != 'bot_token' or not _valid_id(obj['application_id'])
                or not _valid_id(obj['expected_bot_id']) or not isinstance(obj['bot_token'], str)
                or not _TOKEN.fullmatch(obj['bot_token'])):
            raise ValueError('invalid profile')
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('invalid or unavailable Discord profile') from None
    return {'config_valid': True, **check_bot(obj['bot_token'], obj['expected_bot_id'])}


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'invalid Discord read-only request\n')


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description='Discord experimental read-only bot check', allow_abbrev=False)
    parser.add_argument('--check-readonly', action='store_true')
    parser.add_argument('--profile', required=True)
    args = parser.parse_args(argv)
    if not args.check_readonly:
        print('read-only check not requested', file=sys.stderr)
        return 2
    try:
        result = check_profile(Path.home() / '.secret', args.profile)
    except ValueError:
        print('invalid or unavailable Discord profile', file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0 if result['identity'] == 'match' else 1


if __name__ == '__main__':
    raise SystemExit(main())
