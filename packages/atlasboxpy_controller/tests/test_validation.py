import pytest
from pydantic import BaseModel

from atlasboxpy_controller.exceptions import ValidationFailedError
from atlasboxpy_controller.validation import validate_props


class CreateCardProps(BaseModel):
    board_id: str
    title: str
    description: str = ""


def test_validate_props_returns_a_validated_model():
    result = validate_props(CreateCardProps, {"board_id": "b1", "title": "Write docs"})
    assert isinstance(result, CreateCardProps)
    assert result.board_id == "b1"
    assert result.title == "Write docs"
    assert result.description == ""


def test_validate_props_raises_validation_failed_error_not_pydantic_error():
    with pytest.raises(ValidationFailedError) as excinfo:
        validate_props(CreateCardProps, {"board_id": "b1"})  # missing required "title"
    assert excinfo.value.code == "validation_failed"
    assert "title" in excinfo.value.message


def test_validate_props_preserves_the_original_pydantic_error_as_cause():
    with pytest.raises(ValidationFailedError) as excinfo:
        validate_props(CreateCardProps, {})
    assert excinfo.value.cause is not None
