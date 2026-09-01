"""A DB quantum is one physical SQL connection target — a name, a
dialect, and a URL (or the env var a REMOTE one's real URL comes from at
runtime). It's the shard type most callers use with `ShardRouter`: a
single-database app wraps exactly one `DBQuantum` in a `ShardRouter`,
and every key routes to it; a sharded app wraps several.

`DBDriver` identifies the expected SQL dialect — `DBQuantumRegistry`
validates that the resolved URL actually starts with it, so a
misconfigured quantum (wrong env var, wrong driver) fails at connection
time with a clear message instead of a confusing downstream SQL error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class DBDriver(str, Enum):
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"

    def __str__(self) -> str:
        return self.value


class DBEnv(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class DBQuantum:
    name: str
    driver: DBDriver
    env: DBEnv
    local_url: str
    remote_url_env_var: str = ""

    def resolve_url(self) -> str:
        if self.env is DBEnv.LOCAL:
            return self.local_url

        if not self.remote_url_env_var:
            raise ValueError(
                f"DBQuantum(name={self.name}, driver={self.driver}, "
                "env=REMOTE) needs remote_url_env_var set"
            )

        try:
            return os.environ[self.remote_url_env_var]
        except KeyError:
            raise RuntimeError(
                f"DBQuantum(name={self.name}, driver={self.driver}) expected "
                f"${self.remote_url_env_var} to be set"
            ) from None
