"""V2 fixture-only CLI: inspect capabilities or prepare an offline candidate."""
from __future__ import annotations

import argparse
import json
import sys

from scripts.social.capabilities import list_capabilities


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'invalid fixture command\n')


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description='Offline V2 fixture tools; no real delivery')
    parser.add_argument('action', choices=('capabilities', 'prepare', 'prepare-v1', 'prepare-linkedin',
                                           'prepare-linkedin-media', 'prepare-threads', 'prepare-instagram', 'prepare-facebook', 'prepare-facebook-reel', 'prepare-youtube', 'prepare-batch', 'simulate-batch', 'simulate-v1-batch',
                                           'preview-v1-file-batch', 'simulate-json-dispatch', 'prepare-tiktok-inbox', 'prepare-tiktok-direct', 'prepare-discord', 'prepare-x',
                                           'prepare-x-v1-media', 'prepare-telegram'))
    args = parser.parse_args(argv)
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8-sig')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        if args.action == 'capabilities':
            result = list_capabilities()
        else:
            raw = sys.stdin.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError('input too large')
            data = json.loads(raw, object_pairs_hook=_unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid number')))
            if not isinstance(data, dict):
                raise ValueError('invalid input')
            if args.action == 'prepare-linkedin':
                from scripts.social.channels.linkedin.direct import preview_marketing_anchor
                result = preview_marketing_anchor(**data)
            elif args.action == 'prepare-batch':
                from scripts.social.multichannel_fixture import preview_batch
                result = preview_batch(**data)
            elif args.action == 'preview-v1-file-batch':
                from scripts.social.multichannel_fixture import preview_v1_file_batch
                result = preview_v1_file_batch(**data)
            elif args.action == 'simulate-json-dispatch':
                from scripts.social.json_session_simulation import simulate_json_dispatch
                result = simulate_json_dispatch(**data)
            elif args.action == 'simulate-batch':
                from scripts.social.multichannel_fixture import simulate_fixture_batch
                result = simulate_fixture_batch(**data)
            elif args.action == 'simulate-v1-batch':
                from scripts.social.multichannel_fixture import simulate_v1_fixture_batch
                result = simulate_v1_fixture_batch(**data)
            elif args.action == 'prepare-linkedin-media':
                from scripts.social.channels.linkedin.media import preview_initialize
                result = preview_initialize(**data)
            elif args.action == 'prepare-threads':
                from scripts.social.channels.threads.direct import preview_marketing_anchor
                result = preview_marketing_anchor(**data)
            elif args.action == 'prepare-instagram':
                from scripts.social.channels.instagram.direct import preview_marketing_anchor
                result = preview_marketing_anchor(**data)
            elif args.action == 'prepare-facebook':
                from scripts.social.channels.facebook.direct import preview_marketing_anchor
                result = preview_marketing_anchor(**data)
            elif args.action == 'prepare-facebook-reel':
                from scripts.social.channels.facebook.direct import preview_reel_anchor
                result = preview_reel_anchor(**data)
            elif args.action == 'prepare-youtube':
                from scripts.social.channels.youtube.direct import preview_marketing_anchor
                result = preview_marketing_anchor(**data)
            elif args.action == 'prepare-discord':
                from scripts.social.channels.discord.direct import preview_message
                result = preview_message(**data)
            elif args.action == 'prepare-x':
                from scripts.social.channels.x.direct import preview_post
                result = preview_post(**data)
            elif args.action == 'prepare-telegram':
                from scripts.social.channels.telegram.direct import preview_message
                result = preview_message(**data)
            elif args.action == 'prepare-x-v1-media':
                from scripts.social.x_v1_media_preview import preview_v1_media
                result = preview_v1_media(**data)
            elif args.action in ('prepare-tiktok-inbox', 'prepare-tiktok-direct'):
                from scripts.social.channels.tiktok.direct import preview_inbox_upload, preview_direct_post
                result = (preview_inbox_upload(**data) if args.action == 'prepare-tiktok-inbox'
                          else preview_direct_post(**data))
            else:
                from scripts.social.fixture_preview import preview_fixture, preview_v1_with_assets_fixture
                result = (preview_fixture(**data) if args.action == 'prepare'
                          else preview_v1_with_assets_fixture(**data))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (TypeError, ValueError, RecursionError, UnicodeError):
        print('invalid fixture request', file=sys.stderr)
        return 2
    except OSError:
        print('fixture storage error; simulation did not finish', file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
