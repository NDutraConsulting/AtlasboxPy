import pytest

from validator_gateway.exceptions import (
    AlreadyExistsError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
    UnprocessableError,
    UpstreamServiceError,
    ValidationFailedError,
    known_codes,
    register_status_mapping,
    resolve_status,
)


def test_domain_error_defaults():
    err = DomainError()
    assert err.message == DomainError.default_message
    assert err.details == {}
    assert err.cause is None
    assert str(err) == DomainError.default_message


def test_domain_error_all_kwargs():
    cause = ValueError("boom")
    err = DomainError("custom message", details={"field": "x"}, cause=cause)
    assert err.message == "custom message"
    assert err.details == {"field": "x"}
    assert err.cause is cause


def test_cause_chains_via_raise_from():
    cause = ValueError("boom")
    try:
        try:
            raise cause
        except ValueError as exc:
            raise DomainError("wrapped", cause=exc) from exc
    except DomainError as err:
        assert err.__cause__ is cause
        assert err.cause is cause


@pytest.mark.parametrize(
    "exc_type",
    [
        ValidationFailedError,
        NotFoundError,
        ConflictError,
        AlreadyExistsError,
        PermissionDeniedError,
        UnauthenticatedError,
        UnprocessableError,
        UpstreamServiceError,
    ],
)
def test_subclasses_instantiate_with_defaults(exc_type):
    err = exc_type()
    assert isinstance(err, DomainError)
    assert err.message == exc_type.default_message


def test_already_exists_is_a_conflict():
    err = AlreadyExistsError()
    assert isinstance(err, AlreadyExistsError)
    assert isinstance(err, ConflictError)


def test_resolve_status_distinct_mappings():
    seen = set()
    for exc_type in [
        ValidationFailedError,
        NotFoundError,
        ConflictError,
        PermissionDeniedError,
        UnauthenticatedError,
        UnprocessableError,
        UpstreamServiceError,
    ]:
        mapping = resolve_status(exc_type())
        assert (mapping.http_status, mapping.grpc_status) not in seen
        seen.add((mapping.http_status, mapping.grpc_status))


def test_resolve_status_walks_mro_for_unmapped_subclass():
    class TooManyItemsError(ConflictError):
        pass

    mapping = resolve_status(TooManyItemsError())
    assert mapping == resolve_status(ConflictError())


def test_register_status_mapping_and_known_codes():
    class CustomError(DomainError):
        code = "custom_error"
        default_message = "Custom error."

    register_status_mapping(CustomError, 418, "UNKNOWN")
    mapping = resolve_status(CustomError())
    assert mapping.http_status == 418
    assert "custom_error" in known_codes()


def test_retryable_classification():
    assert PermissionDeniedError.retryable is False
    assert UnauthenticatedError.retryable is False
    assert ValidationFailedError.retryable is False
    assert UpstreamServiceError.retryable is True
    assert NotFoundError.retryable is True

    class UnmarkedSubclass(UpstreamServiceError):
        pass

    assert UnmarkedSubclass.retryable is True
