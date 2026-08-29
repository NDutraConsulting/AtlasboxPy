from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from validator_gateway.exceptions import is_retryable, known_codes
from validator_gateway.recovery.models import RecoveryAction, RecoveryStep


class PolicyValidationError(Exception):
    """Raised when a policy file references an unknown DomainError code, or
    configures a RETRY step against a code marked non-retryable (P1-T5)."""


@runtime_checkable
class PolicyStore(Protocol):
    def get_policy(self, code: str) -> list[RecoveryStep]: ...


def _validate_and_build(raw: dict[str, list[dict[str, object]]]) -> dict[str, list[RecoveryStep]]:
    known = known_codes()
    policies: dict[str, list[RecoveryStep]] = {}
    for code, steps_raw in raw.items():
        if code not in known:
            raise PolicyValidationError(
                f"Unknown DomainError code in policy file: {code!r}. "
                f"Known codes: {sorted(known)}"
            )
        steps = [RecoveryStep.model_validate(step) for step in steps_raw]
        for step in steps:
            if step.action == RecoveryAction.RETRY and not is_retryable(code):
                raise PolicyValidationError(
                    f"Policy for code {code!r} includes a RETRY step, but {code!r} "
                    "is marked non-retryable (retrying it can never succeed)."
                )
        policies[code] = steps
    return policies


class JSONFilePolicyStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        raw = json.loads(self._path.read_text())
        self._policies = _validate_and_build(raw)

    def get_policy(self, code: str) -> list[RecoveryStep]:
        return self._policies.get(code, [])


class DBPolicyStore(Protocol):
    """Documented seam for a future database-backed PolicyStore (no runtime
    implementation shipped in this phase).

    Intended shape: a table keyed by `code` storing a JSON blob of
    `RecoveryStep` objects, applying the same validation rules as
    `JSONFilePolicyStore` (`_validate_and_build` above) on *write*, not just
    on read. `PolicyStore` is already a sufficient seam for this — implement
    a class satisfying `PolicyStore.get_policy(code) -> list[RecoveryStep]`
    backed by whatever storage you choose; no interface change is needed
    here. See `docs/recovery_policies.md`.
    """

    def get_policy(self, code: str) -> list[RecoveryStep]: ...
