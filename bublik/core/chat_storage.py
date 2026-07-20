# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 OKTET Labs Ltd. All rights reserved.
"""
Storage seam for AI-chat generated files.

Every caller goes through this module rather than a concrete backend. Two
backends exist and the choice is implicit, driven by whether object storage is
configured at all:

* ``S3_ENDPOINT_URL`` set -> :mod:`bublik.core.s3` (the bundled SeaweedFS, or
  any S3-compatible endpoint including real AWS S3);
* ``S3_ENDPOINT_URL`` empty -> :mod:`bublik.core.local_storage`, writing under
  ``CHAT_FILE_STORAGE_DIR``.

Backends are imported lazily so a deployment that never uses S3 does not pay
for boto3 (nor require it to be importable at model-load time).

Object keys are backend-neutral: the same ``chat/<thread>/<file>/<name>``
string is a bucket key for S3 and a path relative to the storage root on disk.

All functions are synchronous; async callers must run them in a thread
(``anyio.to_thread.run_sync`` / ``sync_to_async``).
"""

from __future__ import annotations

from django.conf import settings


__all__ = [
    'chat_file_key',
    'delete_prefix',
    'public_download_url',
    'read_object',
    'setting',
    'upload_bytes',
    'use_s3',
]

# getattr with defaults (matching the settings templates) so a deployment
# running a settings.py generated before these settings existed degrades
# sensibly instead of raising AttributeError. Note that a settings.py
# generated while S3 was the only backend carries a non-empty
# S3_ENDPOINT_URL, so such a deployment keeps using S3 after an upgrade.
_DEFAULTS = {
    # Empty means "no object storage configured", which selects local disk.
    'S3_ENDPOINT_URL': '',
    'S3_PUBLIC_ENDPOINT_URL': '',
    'S3_ACCESS_KEY': 'bublik',
    'S3_SECRET_KEY': 'bublik-secret-key',
    'S3_BUCKET': 'bublik-chat-files',
    'S3_REGION': 'us-east-1',
    'S3_PRESIGN_EXPIRY': 300,
    # No usable default on purpose; see local_storage.root().
    'CHAT_FILE_STORAGE_DIR': '',
}


def setting(name: str) -> str | int:
    return getattr(settings, name, _DEFAULTS[name])


def use_s3() -> bool:
    """Whether generated files go to object storage rather than local disk."""
    return bool(setting('S3_ENDPOINT_URL'))


def _backend():
    """The active storage backend module."""
    if use_s3():
        from bublik.core import s3  # noqa: PLC0415

        return s3
    from bublik.core import local_storage  # noqa: PLC0415

    return local_storage


def chat_file_key(thread_id: str, file_id: str, filename: str) -> str:
    """Key for a generated chat file; prefixed per-thread so cleanup is a prefix."""
    return f'chat/{thread_id}/{file_id}/{filename}'


def thread_prefix(thread_id: str) -> str:
    """The key prefix holding every generated file of one thread."""
    return f'chat/{thread_id}/'


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    """Store one object."""
    _backend().upload_bytes(key, data, content_type)


def read_object(key: str) -> bytes:
    """Read a whole object into memory (objects are capped by CHAT_FILE_MAX_SIZE)."""
    return _backend().read_object(key)


def delete_prefix(prefix: str) -> None:
    """Best-effort bulk delete of every object under ``prefix``."""
    _backend().delete_prefix(prefix)


def public_download_url(key: str, filename: str) -> str | None:
    """A browser-reachable URL for the object, or ``None`` to proxy it instead.

    Only S3 with a configured public endpoint can hand the browser a URL of
    its own; local files, and S3 endpoints that are not browser-reachable
    (the bundled SeaweedFS listens on loopback), must be proxied by the
    download endpoint.
    """
    return _backend().public_download_url(key, filename)
