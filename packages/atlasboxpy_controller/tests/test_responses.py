import pytest
from pydantic import BaseModel

from atlasboxpy_controller.exceptions import DomainError, NotFoundError, ResponseStatus
from atlasboxpy_controller.responses import SuccessResponse, build_error_response


class UserOut(BaseModel):
    id: str
    name: str


def test_success_response_validates_data_against_generic_type():
    resp = SuccessResponse[UserOut](data={"id": "1", "name": "Ada"})
    assert isinstance(resp.data, UserOut)
    assert resp.data.name == "Ada"


def test_success_response_generic_rejects_invalid_data():
    with pytest.raises(Exception):
        SuccessResponse[UserOut](data={"id": "1"})


def test_success_response_serializes_json_safe():
    resp = SuccessResponse(data={"id": 1})
    assert resp.model_dump(mode="json") == {
        "status": "success",
        "response_code": 200,
        "data": {"id": 1},
    }


def test_success_response_can_be_an_event_instead_of_plain_success():
    resp = SuccessResponse(status=ResponseStatus.EVENT_FIRED, response_code=202, data={"id": 1})
    assert resp.model_dump(mode="json") == {
        "status": "event-fired",
        "response_code": 202,
        "data": {"id": 1},
    }


def test_build_error_response_matches_exception():
    exc = NotFoundError("User 123 not found", details={"user_id": "123"})
    resp = build_error_response(exc)
    assert resp.status == "not-found"
    assert resp.response_code == 404
    assert resp.error.code == "not_found"
    assert resp.error.message == "User 123 not found"
    assert resp.error.details == {"user_id": "123"}
    assert resp.model_dump(mode="json") == {
        "status": "not-found",
        "response_code": 404,
        "error": {
            "code": "not_found",
            "message": "User 123 not found",
            "details": {"user_id": "123"},
        },
    }


def test_build_error_response_for_an_unexpected_bug_is_status_exception():
    resp = build_error_response(DomainError("boom"))
    assert resp.status == "exception"
    assert resp.response_code == 500
