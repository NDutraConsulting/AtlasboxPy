from dataclasses import dataclass


@dataclass(frozen=True)
class SourceJson:
    """What every *ValidatorGateway in this demo requires its caller to
    declare about itself — not inferred, not defaulted. An api_route
    passes its own real request path and REST method; a worker or agent
    caller has no REST method at all, so `method` is optional (defaults to
    None) — only `url` (or whatever identifies the call site: a queue
    name, a job name) and `caller_type` are actually universal.

    This is what the traffic log tags every line with, so a log reader can
    tell which route (or worker, or agent) actually drove a given call —
    not just which gateway class happened to handle it.
    """

    url: str
    caller_type: str
    method: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"url": self.url, "method": self.method, "caller_type": self.caller_type}
