from pydantic import BaseModel


class GatewayConfig(BaseModel):
    hide_internal_errors: bool = True
    include_traceback_in_details: bool = False
    default_error_code_on_unexpected: str = "internal_error"
