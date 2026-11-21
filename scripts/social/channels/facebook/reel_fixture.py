"""One in-memory synthetic Reel lifecycle; never performs external actions."""
from __future__ import annotations

import re
import threading
from typing import Any

from scripts.social.channels.facebook.direct import _check_page, _text


def preview_upload(*, api_version: str, video_id: str, media_id: str) -> dict[str, Any]:
    _check_page('1', api_version)
    if (not isinstance(video_id, str) or not re.fullmatch(r'fixture-reel-[A-Za-z0-9_-]{1,100}', video_id)
            or not isinstance(media_id, str) or not re.fullmatch(r'fixture-video(?:-[A-Za-z0-9_-]{1,100})?', media_id)):
        raise ValueError('invalid Reel fixture upload')
    return {'preview_only': True, 'request': {'method': 'POST', 'host': 'rupload.facebook.com',
            'path': f'/video-upload/{api_version}/{video_id}',
            'headers': {'file_url': f'https://fixture.example.test/assets/{media_id}.mp4'}},
            'warnings': ['not_uploaded', 'provider_and_media_unverified']}


def preview_finish(*, page_id: str, api_version: str, video_id: str, caption: str) -> dict[str, Any]:
    _check_page(page_id, api_version)
    if not isinstance(video_id, str) or not re.fullmatch(r'fixture-reel-[A-Za-z0-9_-]{1,100}', video_id):
        raise ValueError('invalid Reel fixture finish')
    return {'preview_only': True, 'request': {'method': 'POST', 'host': 'graph.facebook.com',
            'path': f'/{api_version}/{page_id}/video_reels',
            'params': {'upload_phase': 'finish', 'video_id': video_id, 'video_state': 'PUBLISHED',
                       'description': _text(caption)}},
            'warnings': ['not_authorized', 'would_publish_if_sent', 'provider_and_media_unverified']}


class ReelFixtureSession:
    """Caller observations are fake and cannot establish identity or publication."""

    def __init__(self, *, page_id: str, api_version: str, media_id: str, caption: str, attempt: str) -> None:
        _check_page(page_id, api_version)
        if (not isinstance(media_id, str) or not re.fullmatch(r'fixture-video(?:-[A-Za-z0-9_-]{1,100})?', media_id)
                or not isinstance(attempt, str) or not re.fullmatch(r'fixture-attempt-[A-Za-z0-9_-]{1,100}', attempt)):
            raise ValueError('invalid Reel fixture session')
        self._page, self._version, self._media, self._attempt = page_id, api_version, media_id, attempt
        self._caption = _text(caption)
        self._video: str | None = None
        self._state = 'start_pending'
        self._lock = threading.RLock()

    @property
    def status(self) -> str:
        with self._lock:
            return self._state

    def accept_start(self, *, attempt: str, page_id: str, video_id: str) -> dict[str, Any]:
        with self._lock:
            if (self._state != 'start_pending' or attempt != self._attempt or page_id != self._page
                    or not isinstance(video_id, str) or not re.fullmatch(r'fixture-reel-[A-Za-z0-9_-]{1,100}', video_id)):
                raise ValueError('invalid Reel start observation')
            self._video = video_id
            self._state = 'upload_pending'
            return preview_upload(api_version=self._version, video_id=video_id, media_id=self._media)

    def accept_upload(self, *, attempt: str, video_id: str, success: bool) -> dict[str, Any]:
        with self._lock:
            if (self._state != 'upload_pending' or attempt != self._attempt or video_id != self._video
                    or success is not True):
                raise ValueError('invalid Reel upload observation')
            self._state = 'finish_pending'
            return preview_finish(page_id=self._page, api_version=self._version, video_id=self._video,
                                  caption=self._caption)

    def accept_finish(self, *, attempt: str, video_id: str, success: bool) -> None:
        with self._lock:
            if (self._state != 'finish_pending' or attempt != self._attempt or video_id != self._video
                    or success is not True):
                raise ValueError('invalid Reel finish observation')
            self._state = 'processing_unverified'

    def finish_unknown(self, *, attempt: str, video_id: str) -> None:
        with self._lock:
            if self._state != 'finish_pending' or attempt != self._attempt or video_id != self._video:
                raise ValueError('invalid Reel unknown transition')
            self._state = 'unknown'
