"""Backend-neutral exceptions a connection/session layer raises instead
of leaking a SQLAlchemy-specific one. A caller reacts to what happened
(a conflict, an unavailable backend), not to which database driver
happens to be configured for this quantum right now.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base for every backend-neutral storage exception."""


class StorageConflict(StorageError):
    """The write would violate a uniqueness/consistency constraint."""


class StorageTimeout(StorageError):
    """The backend didn't respond in time — distinct from StorageUnavailable
    (the backend is reachable but slow/exhausted, not down)."""


class StorageUnavailable(StorageError):
    """The backend couldn't be reached at all."""


class UnsupportedBackendError(StorageError):
    """A backend deliberately not supported, not merely unimplemented —
    for a caller to raise (with its own reasoning attached) so a
    developer reaching for that backend gets an answer immediately
    instead of a stack trace three layers down or a silent assumption
    that it just hasn't been built yet."""
