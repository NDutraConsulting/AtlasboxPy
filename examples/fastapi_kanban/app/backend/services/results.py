"""The envelope every service method returns:

    {status: [success, error, timeout], msg: "", result: {type: [object|array|map], data: ...}}

Services never raise DomainError and never know atlasboxpy_controller exists —
that translation is the controller's job (see
controllers/kanban_controller.py's `_unwrap` helper). A service is only
ever right or wrong about *its own* operation; it has no opinion about
HTTP status codes or response formatting.

On error, `result` is still populated — with `type: "map"` and a `data`
dict carrying a machine-readable `code` (e.g. "not_found", "conflict")
alongside any extra context. That's deliberate: the envelope has no
separate top-level "error code" field, so this is where the controller
gets enough to raise the *right* DomainError subclass instead of a generic
one, without services needing to import atlasboxpy_controller at all.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, ParamSpec

from atlasboxpy_db import StorageConflict, StorageTimeout, StorageUnavailable

ResultType = Literal["object", "array", "map"]

P = ParamSpec("P")


class ServiceStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ServiceResultData:
    type: ResultType
    data: Any


@dataclass(frozen=True)
class ServiceResult:
    status: ServiceStatus
    msg: str = ""
    result: ServiceResultData | None = None

    @classmethod
    def ok(cls, data: Any, *, type_: ResultType = "object") -> ServiceResult:
        return cls(status=ServiceStatus.SUCCESS, result=ServiceResultData(type=type_, data=data))

    @classmethod
    def error(cls, msg: str, *, code: str = "error", **extra: Any) -> ServiceResult:
        return cls(
            status=ServiceStatus.ERROR,
            msg=msg,
            result=ServiceResultData(type="map", data={"code": code, **extra}),
        )

    @classmethod
    def timeout(cls, msg: str = "Operation timed out") -> ServiceResult:
        return cls(
            status=ServiceStatus.TIMEOUT,
            msg=msg,
            result=ServiceResultData(type="map", data={"code": "timeout"}),
        )

    @property
    def error_code(self) -> str:
        """Only meaningful when status is ERROR or TIMEOUT."""
        if self.result is not None and isinstance(self.result.data, dict):
            code = self.result.data.get("code")
            if isinstance(code, str):
                return code
        return "error"


def translate_db_errors(
    fn: Callable[P, Awaitable[ServiceResult]],
) -> Callable[P, Awaitable[ServiceResult]]:
    """Wraps a service method so any real database failure — a simulated
    one (see infrastructure/database/db_connections/db_simulation.py) or
    a genuine one in production — comes back as a ServiceResult instead
    of an uncaught exception. Catches atlasboxpy_db's own backend-neutral
    exceptions, not a SQLAlchemy-specific one — this module has no idea
    which backend (or how many, across entities) is actually involved.
    Lives here (not in db_simulation.py) because it builds ServiceResults,
    a services/-only concept; db_simulation.py itself lives in
    infrastructure/database/ specifically so the storage layer can depend
    on it without depending on services/."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> ServiceResult:
        try:
            return await fn(*args, **kwargs)
        except StorageTimeout as exc:
            return ServiceResult.timeout(str(exc))
        except StorageUnavailable as exc:
            return ServiceResult.error(str(exc), code="upstream_error")
        except StorageConflict as exc:
            return ServiceResult.error(str(exc), code="conflict")

    return wrapper
