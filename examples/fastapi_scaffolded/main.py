"""Demo project built by actually running:

    atlasboxpy-controller init --path examples/fastapi_scaffolded

and then adding this thin FastAPI wrapper on top — the generated
controllers/ files are otherwise unmodified. This is the proof that the
CLI's scaffold output is usable, not just importable.

Run it with:
    cd examples/fastapi_scaffolded
    uvicorn main:app --reload

Note the plain (non-dotted) import below: the CLI generates
`from controllers.example_controller import ExampleController`-style
absolute imports because a real scaffolded project has its own directory as
the sys.path root, not a subpackage of some larger repo. Running this file
as `uvicorn main:app` from inside examples/fastapi_scaffolded/ reproduces
that; the test suite's conftest.py does the equivalent sys.path insertion
so pytest can collect it too.
"""

from controllers.example_controller import ExampleController
from fastapi import APIRouter, FastAPI

from atlasboxpy_controller.fastapi_integration import to_json_response

app = FastAPI(title="atlasboxpy_controller — CLI-scaffolded example")
router = APIRouter()
controller = ExampleController()


@router.get("/examples/{example_id}")
async def get_example(example_id: str):
    result = await controller.get_example(example_id)
    return to_json_response(result)


app.include_router(router)
