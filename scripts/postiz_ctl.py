"""Read-only host preflight and a disabled backup verification entry point.

No Postiz runtime operations or reads of backup paths are implemented here.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


class IntegrityError(ValueError):
    """A backup integrity check cannot safely be performed."""


def doctor() -> dict:
    """Probe local Docker prerequisites only; never start or inspect containers.

    On Windows use Docker Desktop's local Linux pipe explicitly, avoiding a
    user-configured remote Docker host. This does not validate Postiz, images,
    account configuration, credentials, network isolation or backup recovery.
    """
    result = {'schema': 'postiz-host-doctor/1', 'platform': platform.system(),
              'docker_cli': 'missing', 'docker_compose': 'not_checked',
              'docker_engine': 'not_checked', 'postiz': 'not_checked'}
    docker = shutil.which('docker')
    if not docker:
        return result

    def probe(args: list[str], expected: bytes | None = None) -> str:
        try:
            proc = subprocess.run([docker, *args], capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return 'unavailable'
        output = proc.stdout.strip()
        if proc.returncode != 0 or not output:
            return 'unavailable'
        if expected is not None and output.lower() != expected:
            return 'unavailable'
        return 'available'

    result['docker_cli'] = probe(['--version'])
    result['docker_compose'] = probe(['compose', 'version'])
    if os.name == 'nt':
        result['docker_engine'] = probe(['--host', 'npipe:////./pipe/dockerDesktopLinuxEngine',
                                         'version', '--format', '{{.Server.Os}}'], expected=b'linux')
    return result


def verify_manifest(root: Path, manifest: Path) -> int:
    """Fail closed without touching paths until a safe backend is reviewed.

    A future backend must prevent cloud hydration and link/path races before it
    reads either a manifest or backup data. Success must not imply restoration.
    """
    raise IntegrityError("safe backup verification backend unavailable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Postiz host preflight and backup verification")
    parser.add_argument("command", choices=["doctor", "verify-manifest"])
    parser.add_argument("backup_root", type=Path, nargs='?')
    parser.add_argument("manifest", type=Path, nargs='?')
    args = parser.parse_args(argv)
    if args.command == 'doctor':
        if args.backup_root is not None or args.manifest is not None:
            parser.error('doctor does not accept backup paths')
        result = doctor()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if all(result[k] == 'available' for k in ('docker_cli', 'docker_compose', 'docker_engine')) else 3
    if args.backup_root is None or args.manifest is None:
        parser.error('verify-manifest requires backup_root and manifest')
    try:
        verify_manifest(args.backup_root, args.manifest)
    except IntegrityError:
        print("Backup verification unavailable: safe filesystem backend not verified", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
