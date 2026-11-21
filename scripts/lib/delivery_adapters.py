"""Small typed values for the offline delivery simulation only.

No object in this module can contact an external provider.
"""

from dataclasses import dataclass
import hashlib
import hmac


def validate_staged_bytes(data: bytes, *, kind: str, max_bytes: int,
                          expected_sha256: str) -> bytes:
    """Check size, digest and file signature on already-loaded synthetic media.

    This helper does not open or stage files, detect cloud placeholders, decode
    media, scan malware, or establish that the bytes are safe to publish.
    Those steps remain mandatory before any real upload is enabled.
    """
    if type(data) is not bytes or type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('invalid media input')
    if not data or len(data) > max_bytes:
        raise ValueError('invalid media size')
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError('invalid digest')
    actual = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        raise ValueError('digest mismatch')
    signatures = {
        'image/png': data.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/jpeg': data.startswith(b'\xff\xd8\xff'),
        'video/mp4': len(data) >= 12 and data[4:8] == b'ftyp',
    }
    if not isinstance(kind, str) or kind not in signatures or not signatures[kind]:
        raise ValueError('unsupported media signature')
    return data


@dataclass(frozen=True)
class DeliveryResult:
    """A simulated delivery outcome; absent identifiers remain absent."""

    state: str
    remote_job_id: str | None = None
    platform_post_id: str | None = None
    platform_url: str | None = None
    published_at: str | None = None
    comment_id: str | None = None


@dataclass(frozen=True)
class DispatchResult:
    """An offline dispatcher result, never proof of publication."""

    state: str
    reason: str
