from atlasboxpy_controller import DomainError, register_status_mapping


class UsernameReservedError(DomainError):
    """A custom, app-specific DomainError — not one of the built-in
    subclasses — registered with its own status mapping via
    register_status_mapping() (P1-T4)."""

    code = "username_reserved"
    default_message = "This username is reserved and cannot be used."


register_status_mapping(UsernameReservedError, http_status=403, grpc_status="PERMISSION_DENIED")
