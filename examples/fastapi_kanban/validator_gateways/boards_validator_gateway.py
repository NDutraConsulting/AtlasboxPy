from validator_gateway import ValidatorGateway, default_logging_hook

from ..controllers.boards_controller import BoardsController
from ..services import KanbanService


class BoardsValidatorGateway(ValidatorGateway[BoardsController]):
    """The gateway for the "boards" list feature — constructs and wraps a
    BoardsController around `service`. Fail-fast (no recovery=), per
    Design Decision 8: this is a synchronous request/response call with a
    client waiting.

    `source_info` is not inferred — the caller (main.py's dependency
    factory) must say who it is, so the traffic log (logging_setup.py)
    identifies which gateway actually handled a call.
    """

    def __init__(self, service: KanbanService, *, source_info: str) -> None:
        super().__init__(BoardsController(service), on_exception=default_logging_hook())
        self.source_info = source_info
