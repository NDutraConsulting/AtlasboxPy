from enum import Enum

import pytest
from pydantic import BaseModel

from validator_gateway import BaseController, ConflictError, NotFoundError
from validator_gateway.classifying import ClassifyingValidatorGateway, SourceJson
from validator_gateway.responses import ErrorResponse, build_error_response


class CreatePayload(BaseModel):
    name: str


class Case(Enum):
    NOT_FOUND = "not_found"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"


class Controller(BaseController):
    async def get_thing(self, thing_id: str):
        if thing_id == "missing":
            raise NotFoundError(f"{thing_id} not found")
        if thing_id == "conflict":
            raise ConflictError("already exists")
        if thing_id == "bug":
            raise RuntimeError("not a DomainError at all")
        return {"id": thing_id}

    async def create_thing(self, payload: CreatePayload, *, notify: bool = False):
        return {"name": payload.name, "notified": notify}


class ThingGateway(ClassifyingValidatorGateway[Controller]):
    _KNOWN_CASES: dict[str, Enum] = {"not_found": Case.NOT_FOUND}

    def __init__(self, *, source_json: SourceJson) -> None:
        super().__init__(Controller(), source_json=source_json)

    def _severity_fallback(self, is_server_error: bool) -> Enum:
        return Case.SERVER_ERROR if is_server_error else Case.CLIENT_ERROR

    async def _resolve(self, case, exc, action, args) -> ErrorResponse:
        if case is Case.NOT_FOUND:
            from validator_gateway.responses import ErrorDetail

            return ErrorResponse(
                error=ErrorDetail(code=exc.code, message=f"{exc.message} (custom hint)", details={})
            )
        return build_error_response(exc)


def _gateway() -> ThingGateway:
    source = SourceJson(url="/things/1", method="GET", caller_type="api_route")
    return ThingGateway(source_json=source)


def test_cannot_instantiate_without_implementing_abstract_methods():
    class Incomplete(ClassifyingValidatorGateway[Controller]):
        pass

    with pytest.raises(TypeError, match="abstract"):
        Incomplete(Controller(), source_json=SourceJson(url="/x", caller_type="api_route"))


@pytest.mark.asyncio
async def test_success_path():
    gateway = _gateway()
    resp = await gateway.handle(gateway.controller.get_thing, "123")
    assert resp.status == "success"
    assert resp.data == {"id": "123"}


@pytest.mark.asyncio
async def test_known_case_gets_custom_resolution():
    gateway = _gateway()
    resp = await gateway.handle(gateway.controller.get_thing, "missing")
    assert resp.status == "error"
    assert resp.error.message == "missing not found (custom hint)"


@pytest.mark.asyncio
async def test_unknown_code_falls_back_to_severity():
    gateway = _gateway()
    resp = await gateway.handle(gateway.controller.get_thing, "conflict")
    assert resp.status == "error"
    # not in _KNOWN_CASES -> severity fallback -> plain build_error_response
    assert resp.error.code == "conflict"


@pytest.mark.asyncio
async def test_non_domain_error_is_unclassified_but_still_formatted():
    gateway = _gateway()
    resp = await gateway.handle(gateway.controller.get_thing, "bug")
    assert resp.status == "error"
    assert resp.error.code == "domain_error"


@pytest.mark.asyncio
async def test_every_call_is_logged_with_source_json_and_case(caplog):
    import logging

    gateway = _gateway()
    with caplog.at_level(logging.INFO, logger="validator_gateway.traffic"):
        await gateway.handle(gateway.controller.get_thing, "123")
        await gateway.handle(gateway.controller.get_thing, "missing")

    messages = [r.message for r in caplog.records]
    assert any("case=success" in m and '"url": "/things/1"' in m for m in messages)
    assert any("case=not_found" in m for m in messages)


@pytest.mark.asyncio
async def test_pydantic_payload_and_kwargs_are_logged_as_json(caplog):
    import logging

    gateway = _gateway()
    with caplog.at_level(logging.INFO, logger="validator_gateway.traffic"):
        resp = await gateway.handle(
            gateway.controller.create_thing, CreatePayload(name="Ada"), notify=True
        )

    assert resp.status == "success"
    assert resp.data == {"name": "Ada", "notified": True}
    (record,) = [r for r in caplog.records if "create_thing" in r.message]
    assert '{"name": "Ada"}' in record.message  # the model, dumped to its JSON body
    assert '{"notify": true}' in record.message  # kwargs, appended as their own JSON object


def test_source_json_method_is_optional_for_non_http_callers():
    source = SourceJson(url="worker:sync-job", caller_type="worker")
    assert source.method is None
    assert source.as_dict() == {"url": "worker:sync-job", "method": None, "caller_type": "worker"}
