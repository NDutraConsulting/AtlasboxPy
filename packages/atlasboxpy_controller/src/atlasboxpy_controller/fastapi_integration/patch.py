from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def extract_patch_data(model: BaseModel) -> dict[str, Any]:
    """Thin wrapper over model.model_dump(exclude_unset=True).

    Solves the unset-vs-null problem for PATCH semantics: a field explicitly
    set to None in the request should overwrite existing data, while a field
    omitted entirely from the request body should be left untouched.
    """
    return model.model_dump(exclude_unset=True)
