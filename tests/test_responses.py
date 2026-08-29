from validator_gateway.exceptions import NotFoundError
from validator_gateway.responses import SuccessResponse, build_error_response


def test_success_response_serializes_json_safe():
    resp = SuccessResponse(data={"id": 1})
    assert resp.model_dump(mode="json") == {"status": "success", "data": {"id": 1}}


def test_build_error_response_matches_exception():
    exc = NotFoundError("User 123 not found", details={"user_id": "123"})
    resp = build_error_response(exc)
    assert resp.status == "error"
    assert resp.error.code == "not_found"
    assert resp.error.message == "User 123 not found"
    assert resp.error.details == {"user_id": "123"}
    assert resp.model_dump(mode="json") == {
        "status": "error",
        "error": {
            "code": "not_found",
            "message": "User 123 not found",
            "details": {"user_id": "123"},
        },
    }
