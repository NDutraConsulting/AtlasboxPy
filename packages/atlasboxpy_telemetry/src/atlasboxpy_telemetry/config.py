"""Telemetry on/off resolution: effective-enabled is a per-request
override if one was set, else the process-wide default.

The process default comes from one environment variable, read fresh on
every check (not cached at import time) — the same `os.environ[...]`
convention `atlasboxpy_db`'s `DBQuantum.resolve_url()` already uses; no
new settings framework introduced for one boolean.

The per-request override rides `atlasboxpy_api`'s `RequestContext` — an
app wires it to a `HeaderContextMiddleware` instance (see this package's
README) so a single REST header can turn tracing on for exactly one
request, without a config change or a redeploy — the motivating case for
this whole package.
"""

from __future__ import annotations

import os

from atlasboxpy_api import RequestContext

_ENV_VAR = "ATLASBOXPY_TELEMETRY_ENABLED"
_TRUE_VALUES = {"1", "true", "yes", "on"}

# None = "no per-request override set" — falls back to the process
# default. An app's composition root wires this to a HeaderContextMiddleware
# whose `resolve` decides what counts as "on" for the header it reads.
trace_override: RequestContext[bool | None] = RequestContext(
    "atlasboxpy-telemetry-override", default=None
)


def process_default_enabled() -> bool:
    return os.environ.get(_ENV_VAR, "").strip().lower() in _TRUE_VALUES


def is_enabled() -> bool:
    override = trace_override.get()
    if override is not None:
        return override
    return process_default_enabled()
