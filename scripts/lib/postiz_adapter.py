"""Translate deliberately synthetic fixtures; this is not a Postiz API client.

The source-backed approval and vendor gates remain closed.  In particular the
fixture vocabulary below is not claimed to match any real Postiz response.
"""

from collections.abc import Mapping
import copy
import os
import re
import sys
import threading
from urllib.parse import urlsplit
from datetime import datetime
import uuid

if __package__:
    from .delivery_adapters import DeliveryResult
else:
    from delivery_adapters import DeliveryResult


def _opaque(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() == value and value else None


def normalize_fake_response(raw: Mapping[str, object]) -> DeliveryResult:
    """Return unknown for unsupported or incomplete synthetic responses."""
    state = raw.get('state')
    job_id = _opaque(raw.get('job_id'))
    post_id = _opaque(raw.get('platform_post_id'))
    url = _opaque(raw.get('platform_url'))
    raw_at = raw.get('published_at')
    raw_comment = raw.get('comment_id')
    if raw_comment is not None and (not isinstance(raw_comment, str) or not raw_comment.strip()
                                    or raw_comment != raw_comment.strip() or len(raw_comment) > 512
                                    or any(ord(ch) < 32 for ch in raw_comment)):
        return DeliveryResult(state='unknown')
    if raw_at is not None:
        if (not isinstance(raw_at, str) or not re.fullmatch(
                r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', raw_at)):
            return DeliveryResult(state='unknown')
        try:
            datetime.fromisoformat(raw_at.replace('Z', '+00:00'))
        except ValueError:
            return DeliveryResult(state='unknown')
    if isinstance(state, str) and state in {'submitted', 'scheduled'} and job_id and not post_id and not url:
        return DeliveryResult(state=state, remote_job_id=job_id)
    if state == 'published' and post_id and url:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return DeliveryResult(state='unknown')
        if (parsed.scheme == 'https' and parsed.hostname == 'example.invalid'
                and not parsed.username and not parsed.password):
            return DeliveryResult(state='published', remote_job_id=job_id,
                                  platform_post_id=post_id, platform_url=url,
                                  published_at=raw_at, comment_id=raw_comment)
    return DeliveryResult(state='unknown')


def classify_fake_failure(status: int | None, *,
                          definite_no_side_effect: bool = False) -> DeliveryResult:
    """Classify test fixtures only; a real adapter must independently prove rejection."""
    if type(status) is int and 400 <= status < 500 and definite_no_side_effect is True:
        return DeliveryResult(state='failed')
    return DeliveryResult(state='unknown')


class FakePostiz:
    """In-memory test double only; it has no filesystem or network client."""

    def __init__(self) -> None:
        self._jobs: dict[str, DeliveryResult] = {}
        self._payloads: dict[str, dict] = {}
        self.submission_count = 0
        self._poll_lock = threading.Lock()
        self._poll_clock = None
        self._poll_next_allowed = None
        self._poll_failures = 0
        self._poll_blocked = False
        self.instance_id = f'fake-{uuid.uuid4()}'

    def submit(self, intent_id: str, *, scheduled: bool, payload: dict | None = None) -> DeliveryResult:
        if not isinstance(intent_id, str) or not intent_id.strip():
            raise ValueError('intent id is required')
        self.submission_count += 1
        job_id = f'fake-job-{self.submission_count}'
        result = DeliveryResult(state='scheduled' if scheduled else 'submitted',
                                remote_job_id=job_id)
        self._jobs[job_id] = result
        if payload is not None:
            self._payloads[job_id] = copy.deepcopy(payload)
        return result

    def get_payload(self, remote_job_id: str) -> dict | None:
        return copy.deepcopy(self._payloads.get(remote_job_id))

    def get_delivery(self, remote_job_id: str) -> DeliveryResult:
        return self._jobs.get(remote_job_id, DeliveryResult(state='unknown'))

    def cancel(self, remote_job_id: str) -> DeliveryResult:
        current = self.get_delivery(remote_job_id)
        if current.state not in {'submitted', 'scheduled'}:
            return DeliveryResult(state='unknown')
        result = DeliveryResult(state='cancelled', remote_job_id=remote_job_id)
        self._jobs[remote_job_id] = result
        return result

    def publish(self, remote_job_id: str, *, platform_post_id: str,
                platform_url: str, published_at: str | None = None,
                comment_id: str | None = None) -> None:
        if self.get_delivery(remote_job_id).state not in {'submitted', 'scheduled'}:
            raise ValueError('fake job is not publishable')
        result = normalize_fake_response({
            'state': 'published', 'job_id': remote_job_id,
            'platform_post_id': platform_post_id, 'platform_url': platform_url,
            'published_at': published_at, 'comment_id': comment_id,
        })
        if result.state != 'published':
            raise ValueError('invalid fake publication evidence')
        self._jobs[remote_job_id] = result


def reconcile_fake(provider: FakePostiz, remote_job_id: str | None, *,
                   expected_instance_id: str) -> DeliveryResult:
    """Return an in-memory observation, without persisting it or submitting.

    Deliberately refuses even subclasses: this helper cannot be pointed at a
    network-capable adapter while the vendor gate and source binding are closed.
    """
    # Both supported import names may exist in one interpreter; they must
    # resolve to this same project file. Exact class identity rejects subclasses.
    alternate_name = ('scripts.lib.postiz_adapter' if __name__ == 'postiz_adapter'
                      else 'postiz_adapter')
    alternate = sys.modules.get(alternate_name)
    other_file = getattr(alternate, '__file__', None)
    same_file = (isinstance(other_file, str) and
                 os.path.normcase(os.path.abspath(other_file)) ==
                 os.path.normcase(os.path.abspath(__file__)))
    if (type(provider) is not FakePostiz and
            not (same_file and type(provider) is getattr(alternate, 'FakePostiz', None))):
        raise TypeError('only FakePostiz is allowed')
    if provider.instance_id != expected_instance_id:
        return DeliveryResult(state='unknown')
    if not isinstance(remote_job_id, str) or not remote_job_id:
        return DeliveryResult(state='unknown')
    observed = provider.get_delivery(remote_job_id)
    if observed.remote_job_id != remote_job_id:
        return DeliveryResult(state='unknown')
    return observed


class SyntheticRateLimitError(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__('synthetic rate limit')
