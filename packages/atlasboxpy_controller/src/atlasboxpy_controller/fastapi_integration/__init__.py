from atlasboxpy_controller.fastapi_integration.exception_handlers import to_json_response
from atlasboxpy_controller.fastapi_integration.openapi import (
    apply_registry_to_route,
    build_custom_openapi,
    iter_api_routes,
)
from atlasboxpy_controller.fastapi_integration.patch import extract_patch_data
from atlasboxpy_controller.fastapi_integration.route import DomainErrorRoute

__all__ = [
    "DomainErrorRoute",
    "apply_registry_to_route",
    "build_custom_openapi",
    "extract_patch_data",
    "iter_api_routes",
    "to_json_response",
]
