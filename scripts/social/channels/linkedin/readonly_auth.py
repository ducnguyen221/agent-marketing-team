"""Read-only LinkedIn member identity probe. Not connected to V1 or dispatch.

The profile reader and CLI are experimental and not approved for live use;
the caller must independently bind credential and author to the same app.
Never use this for publication.
"""
from __future__ import annotations

import http.client
import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from scripts.social.channels.linkedin.direct import interpret_userinfo

_MAX_BODY = 65536
_TOKEN = re.compile(r'[A-Za-z0-9._~+/=-]{1,4096}\Z')
_PROFILE = re.compile(r'[a-z0-9](?:[a-z0-9_-]{0,46}[a-z0-9])?\Z')
_CLIENT = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_PERSON = re.compile(r'urn:li:person:[A-Za-z0-9_-]{1,128}\Z')


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('invalid response')
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError('invalid response')


def check_userinfo(access_token: str, expected_author: str) -> dict[str, Any]:
    """Perform one fixed-host GET; output never contains token or profile.

    A match is not a verified application binding or permission to publish.
    """
    unknown = interpret_userinfo(0, {}, expected_author=expected_author)
    if not isinstance(access_token, str) or not _TOKEN.fullmatch(access_token):
        raise ValueError('invalid credential')
    connection = None
    try:
        connection = http.client.HTTPSConnection('api.linkedin.com', timeout=10)
        connection.request('GET', '/v2/userinfo', headers={
            'Authorization': 'Bearer ' + access_token, 'Accept': 'application/json',
        })
        response = connection.getresponse()
        if response.status != 200:
            return unknown
        data = response.read(_MAX_BODY + 1)
        if len(data) > _MAX_BODY:
            return unknown
        body = json.loads(data.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_reject_constant)
        return interpret_userinfo(200, body, expected_author=expected_author)
    except (OSError, http.client.HTTPException, ValueError, UnicodeError, RecursionError):
        return unknown
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def _unlinked(path: Path, *, directory: bool) -> os.stat_result:
    info = path.lstat()
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not expected or stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or (not directory and info.st_nlink != 1)):
        raise ValueError('invalid profile location')
    return info


def check_profile(root: Path, alias: str) -> dict[str, Any]:
    """Read a named LinkedIn profile; root must be selected by a trusted caller.

    File metadata checks cannot eliminate directory replacement races on all OSes.
    App ownership is owner-asserted, not proven by this operation.
    """
    if (not isinstance(root, Path) or not root.is_absolute() or '..' in root.parts
            or str(root).startswith(('\\\\', '//'))
            or any(':' in component for component in root.parts[1:])
            or not isinstance(alias, str) or not _PROFILE.fullmatch(alias)
            or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', alias)):
        raise ValueError('invalid profile request')
    try:
        root_info = _unlinked(root, directory=True)
        folder = root / alias
        folder_info = _unlinked(folder, directory=True)
        path = folder / 'linkedin-userinfo.json'
        file_info = _unlinked(path, directory=False)
        if file_info.st_size > 16384:
            raise ValueError('invalid profile')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags)
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
            data = stream.read(16385)
        if len(data) > 16384:
            raise ValueError('invalid profile')
        obj = json.loads(data.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_reject_constant)
        if (not isinstance(obj, dict) or set(obj) != {'schema', 'provider', 'token_kind', 'client_id', 'person_urn', 'access_token'}
                or obj['schema'] != 'linkedin-userinfo/1' or obj['provider'] != 'linkedin'
                or obj['token_kind'] != 'oauth_access_token' or not isinstance(obj['client_id'], str)
                or not _CLIENT.fullmatch(obj['client_id']) or not isinstance(obj['person_urn'], str)
                or not _PERSON.fullmatch(obj['person_urn']) or not isinstance(obj['access_token'], str)
                or not _TOKEN.fullmatch(obj['access_token'])):
            raise ValueError('invalid profile')
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('invalid or unavailable LinkedIn profile') from None
    result = check_userinfo(obj['access_token'], obj['person_urn'])
    return {'config_valid': True, 'identity': result['identity'], 'profile_binding_verified': False,
            'app_binding_verified': False, 'publish_authorized': False}


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'invalid LinkedIn read-only request\n')


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description='LinkedIn experimental read-only identity check', allow_abbrev=False)
    parser.add_argument('--check-readonly', action='store_true')
    parser.add_argument('--profile', required=True)
    args = parser.parse_args(argv)
    if not args.check_readonly:
        print('read-only check not requested', file=sys.stderr)
        return 2
    try:
        result = check_profile(Path.home() / '.secret', args.profile)
    except ValueError:
        print('invalid or unavailable LinkedIn profile', file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0 if result['identity'] == 'match' else 1


if __name__ == '__main__':
    raise SystemExit(main())
