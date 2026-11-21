"""Experimental YouTube channel identity GET, separate from V1 and upload."""
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

_CHANNEL = re.compile(r'UC[A-Za-z0-9_-]{22}\Z')
_CLIENT = re.compile(r'[A-Za-z0-9._-]{1,256}\Z')
_MAX_BODY = 65536


def interpret_channels(status: int, body: Any, *, expected_channel_id: str) -> dict[str, Any]:
    if not isinstance(expected_channel_id, str) or not _CHANNEL.fullmatch(expected_channel_id):
        raise ValueError('invalid expected channel')
    result: dict[str, Any] = {'identity': 'unknown', 'profile_binding_verified': False,
                              'app_binding_verified': False, 'channel_permissions_verified': False,
                              'publish_authorized': False}
    if (type(status) is not int or status != 200 or not isinstance(body, dict)
            or any(key in body for key in ('error', 'errors', 'status', 'title', 'detail', 'type', 'code', 'message'))
            or ('kind' in body and body['kind'] != 'youtube#channelListResponse')
            or ('nextPageToken' in body and (not isinstance(body['nextPageToken'], str) or not body['nextPageToken']))
            or not isinstance(body.get('items'), list) or not 1 <= len(body['items']) <= 50):
        return result
    observed = []
    for item in body['items']:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not _CHANNEL.fullmatch(item['id']):
            return result
        observed.append(item['id'])
    if len(set(observed)) != len(observed):
        return result
    if expected_channel_id in observed:
        result['identity'] = 'match'
    elif 'nextPageToken' not in body:
        result['identity'] = 'mismatch'
    return result


def check_channel(access_token: str, expected_channel_id: str) -> dict[str, Any]:
    """Perform one fixed-host GET and return no token or channel ID."""
    unknown = interpret_channels(0, {}, expected_channel_id=expected_channel_id)
    if not isinstance(access_token, str) or not _TOKEN.fullmatch(access_token):
        raise ValueError('invalid credential')
    connection = None
    try:
        connection = http.client.HTTPSConnection('www.googleapis.com', timeout=10)
        connection.request('GET', '/youtube/v3/channels?part=id&mine=true&maxResults=50&fields=items%28id%29%2CnextPageToken',
                           headers={'Authorization': 'Bearer ' + access_token, 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            return unknown
        raw = response.read(_MAX_BODY + 1)
        if len(raw) > _MAX_BODY:
            return unknown
        body = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_reject_constant)
        return interpret_channels(200, body, expected_channel_id=expected_channel_id)
    except (OSError, http.client.HTTPException, ValueError, UnicodeError, RecursionError):
        return unknown
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def check_profile(root: Path, alias: str) -> dict[str, Any]:
    """Read a provider-specific profile from a root trusted by the caller."""
    if (not isinstance(root, Path) or not root.is_absolute() or '..' in root.parts
            or str(root).startswith(('\\\\', '//')) or any(':' in part for part in root.parts[1:])
            or not isinstance(alias, str) or not _PROFILE.fullmatch(alias)
            or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', alias)):
        raise ValueError('invalid profile request')
    try:
        root_info = _unlinked(root, directory=True)
        folder = root / alias
        folder_info = _unlinked(folder, directory=True)
        path = folder / 'youtube-channel-userinfo.json'
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
        if (not isinstance(obj, dict) or set(obj) != {'schema', 'provider', 'token_kind', 'client_id',
                                                       'expected_channel_id', 'access_token'}
                or obj['schema'] != 'youtube-channel-userinfo/1' or obj['provider'] != 'youtube'
                or obj['token_kind'] != 'oauth_access_token' or not isinstance(obj['client_id'], str)
                or not _CLIENT.fullmatch(obj['client_id']) or not isinstance(obj['expected_channel_id'], str)
                or not _CHANNEL.fullmatch(obj['expected_channel_id']) or not isinstance(obj['access_token'], str)
                or not _TOKEN.fullmatch(obj['access_token'])):
            raise ValueError('invalid profile')
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('invalid or unavailable YouTube profile') from None
    return {'config_valid': True, **check_channel(obj['access_token'], obj['expected_channel_id'])}


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'invalid YouTube read-only request\n')


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description='YouTube experimental read-only channel check', allow_abbrev=False)
    parser.add_argument('--check-readonly', action='store_true')
    parser.add_argument('--profile', required=True)
    args = parser.parse_args(argv)
    if not args.check_readonly:
        print('read-only check not requested', file=sys.stderr)
        return 2
    try:
        result = check_profile(Path.home() / '.secret', args.profile)
    except ValueError:
        print('invalid or unavailable YouTube profile', file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0 if result['identity'] == 'match' else 1


if __name__ == '__main__':
    raise SystemExit(main())
