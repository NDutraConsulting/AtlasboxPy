from validator_gateway import ValidatorGateway, default_logging_hook

from ..controllers.board_controller import BoardController
from ..services import KanbanService


class BoardValidatorGateway(ValidatorGateway[BoardController]):
    """The gateway for the "board" feature (columns and cards within one
    board) — constructs and wraps a BoardController around `service`.
    Fail-fast (no recovery=), per Design Decision 8: this is a synchronous
    request/response call with a client waiting.

    `source_info` is not inferred — the caller (main.py's dependency
    factory) must say who it is, so the traffic log (logging_setup.py)
    identifies which gateway actually handled a call.
    """

    def __init__(self, service: KanbanService, *, source_info: str) -> None:
        super().__init__(BoardController(service), on_exception=default_logging_hook())
        self.source_info = source_info
