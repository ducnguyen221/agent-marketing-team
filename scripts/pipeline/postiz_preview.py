"""Build offline Postiz candidates from a JSON batch on standard input.

This command never sends, schedules, approves, uploads or writes a ledger.
Output contains the caller's content and must be handled accordingly.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from postiz_payload import build_postiz_batch_preview  # noqa: E402


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def main() -> int:
    if sys.argv[1:] in (['-h'], ['--help']):
        print('Offline Postiz preview: provide a JSON batch on standard input.')
        return 0
    if sys.argv[1:]:
        print('invalid preview arguments', file=sys.stderr)
        return 2
    try:
        data = sys.stdin.buffer.read(2_200_001)
        if len(data) > 2_200_000:
            raise ValueError('input too large')
        requests = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_keys)
        items = build_postiz_batch_preview(requests)
        output = json.dumps({'mode': 'preview_only', 'items': items}, ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        print('invalid preview input', file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
