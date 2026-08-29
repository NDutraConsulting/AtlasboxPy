"""Demo project built by actually running:

    validator-gateway init --path examples/fastapi_scaffolded

and then adding this thin FastAPI wrapper on top — the generated
controllers/ and validator_gateways/ files are otherwise unmodified. This
is the proof that the CLI's scaffold output is usable, not just importable.

Run it with:
    cd examples/fastapi_scaffolded
    uvicorn main:app --reload

Note the plain (non-dotted) imports below: the CLI generates
`from controllers.example_controller import ExampleController`-style
absolute imports because a real scaffolded project has its own directory as
the sys.path root, not a subpackage of some larger repo. Running this file
as `uvicorn main:app` from inside examples/fastapi_scaffolded/ reproduces
that; the test suite's conftest.py does the equivalent sys.path insertion
so pytest can collect it too.
"""

from fastapi import APIRouter, FastAPI
from validator_gateways.example_gateway import gateway

from validator_gateway.fastapi_integration import to_json_response

app = FastAPI(title="validator_gateway — CLI-scaffolded example")
router = APIRouter()


@router.get("/examples/{example_id}")
async def get_example(example_id: str):
    result = await gateway.handle(gateway.controller.get_example, example_id)
    return to_json_response(result)


app.include_router(router)
