from validator_gateway import ValidatorGateway, default_logging_hook
from validator_gateway.classifying import SourceJson

from ..controllers.degraded_board_controller import DegradedBoardController


class DegradedBoardValidatorGateway(ValidatorGateway[DegradedBoardController]):
    """The fallback gateway BoardValidatorGateway redirects to when "the
    database" is down (see board_validator_gateway.py's UPSTREAM_UNAVAILABLE
    case) — a real, separate ValidatorGateway instance, not a bare async
    function, to demonstrate that a gateway can orchestrate a redirect to
    another gateway entirely, not just to a registered fallback callable.

    No FailureCase enum here: DegradedBoardController.get_degraded_board
    can't fail, so there's nothing to classify. Keep this gateway as
    simple as its controller — don't build machinery for failure modes
    that can't happen.
    """

    def __init__(self, *, source_json: SourceJson) -> None:
        super().__init__(DegradedBoardController(), on_exception=default_logging_hook())
        self.source_json = source_json
