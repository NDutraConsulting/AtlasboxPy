from dataclasses import dataclass


@dataclass(frozen=True)
class SourceJson:
    """What every *ValidatorGateway in this demo requires its caller to
    declare about itself — not inferred, not defaulted. An api_route
    passes its own real request path/method; a future worker or agent
    caller would pass its own caller_type instead of "api_route" and
    whatever url/method makes sense for it (e.g. a queue name).

    This is what the traffic log tags every line with, so a log reader can
    tell which route (or worker, or agent) actually drove a given call —
    not just which gateway class happened to handle it.
    """

    url: str
    method: str
    caller_type: str

    def as_dict(self) -> dict[str, str]:
        return {"url": self.url, "method": self.method, "caller_type": self.caller_type}
