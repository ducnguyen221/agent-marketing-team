"""Experimental TikTok User Info check; never posts or refreshes credentials.

Only the CLI fixes the profile root. Caller-provided profile data and expected
open_id do not independently authenticate app, account or publishing rights.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import stat
import sys
import unicodedata
from pathlib import Path
from typing import Any

from scripts.social.channels.linkedin.readonly_auth import (
    _CLIENT, _PROFILE, _TOKEN, _reject_constant, _unique, _unlinked,
)

_MAX_BODY = 65536


def _valid_open_id(value: Any) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 512
            and not any(char.isspace() or unicodedata.category(char).startswith('C') for char in value))


def interpret_userinfo(status: int, body: Any, *, expected_open_id: str) -> dict[str, Any]:
    """Compare caller-supplied identity, never infer app or publish rights."""
    if not _valid_open_id(expected_open_id):
        raise ValueError('invalid expected identity')
    result: dict[str, Any] = {'identity': 'unknown', 'profile_binding_verified': False,
                              'app_binding_verified': False, 'publish_authorized': False}
    if (type(status) is not int or status != 200 or not isinstance(body, dict)
            or not isinstance(body.get('error'), dict) or body['error'].get('code') != 'ok'
            or not isinstance(body.get('data'), dict) or not isinstance(body['data'].get('user'), dict)):
        return result
    observed = body['data']['user'].get('open_id')
    if _valid_open_id(observed):
        result['identity'] = 'match' if observed == expected_open_id else 'mismatch'
    return result


def check_userinfo(access_token: str, expected_open_id: str) -> dict[str, Any]:
    """One fixed-host GET. Output excludes credential, identifier and profile."""
    unknown = interpret_userinfo(0, {}, expected_open_id=expected_open_id)
    if not isinstance(access_token, str) or not _TOKEN.fullmatch(access_token):
        raise ValueError('invalid credential')
    connection = None
    try:
        connection = http.client.HTTPSConnection('open.tiktokapis.com', timeout=10)
        connection.request('GET', '/v2/user/info/?fields=open_id', headers={
            'Authorization': 'Bearer ' + access_token, 'Accept': 'application/json',
        })
        response = connection.getresponse()
        if response.status != 200:
            return unknown
        data = response.read(_MAX_BODY + 1)
        if len(data) > _MAX_BODY:
            return unknown
        body = json.loads(data.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_reject_constant)
        return interpret_userinfo(200, body, expected_open_id=expected_open_id)
    except (OSError, http.client.HTTPException, ValueError, UnicodeError, RecursionError):
        return unknown
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def check_profile(root: Path, alias: str) -> dict[str, Any]:
    """Read one provider-specific file; root is trusted only when fixed by CLI.

    Metadata checks do not eliminate concurrent directory/file replacement.
    """
    if (not isinstance(root, Path) or not root.is_absolute() or '..' in root.parts
            or str(root).startswith(('\\\\', '//')) or any(':' in part for part in root.parts[1:])
            or not isinstance(alias, str) or not _PROFILE.fullmatch(alias)
            or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', alias)):
        raise ValueError('invalid profile request')
    try:
        root_info = _unlinked(root, directory=True)
        folder = root / alias
        folder_info = _unlinked(folder, directory=True)
        path = folder / 'tiktok-userinfo.json'
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
        if (not isinstance(obj, dict) or set(obj) != {'schema', 'provider', 'token_kind', 'client_key',
                                                     'expected_open_id', 'access_token'}
                or obj['schema'] != 'tiktok-userinfo/1' or obj['provider'] != 'tiktok'
                or obj['token_kind'] != 'oauth_access_token' or not isinstance(obj['client_key'], str)
                or not _CLIENT.fullmatch(obj['client_key']) or not isinstance(obj['expected_open_id'], str)
                or not _valid_open_id(obj['expected_open_id']) or not isinstance(obj['access_token'], str)
                or not _TOKEN.fullmatch(obj['access_token'])):
            raise ValueError('invalid profile')
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('invalid or unavailable TikTok profile') from None
    result = check_userinfo(obj['access_token'], obj['expected_open_id'])
    return {'config_valid': True, **result}


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'invalid TikTok read-only request\n')


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description='TikTok experimental read-only identity check', allow_abbrev=False)
    parser.add_argument('--check-readonly', action='store_true')
    parser.add_argument('--profile', required=True)
    args = parser.parse_args(argv)
    if not args.check_readonly:
        print('read-only check not requested', file=sys.stderr)
        return 2
    try:
        result = check_profile(Path.home() / '.secret', args.profile)
    except ValueError:
        print('invalid or unavailable TikTok profile', file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0 if result['identity'] == 'match' else 1


if __name__ == '__main__':
    raise SystemExit(main())
