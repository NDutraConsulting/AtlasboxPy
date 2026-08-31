# Architecture

## The request lifecycle

```
frontend > thin api_route <-> Controller (BaseController) <-> [services...] <-> [repository, model]
                                     ^
                     workers / agents / gRPC call the controller directly, too
```

A call enters through whatever transport is in front of it — an HTTP route, a
queue worker picking up a job, an agent's tool-calling loop, or a gRPC
servicer method. Every one of those callers does the same two things:

1. `await controller.some_method(props)` — one dict argument, validated
   inside the method itself (see `validate_props` in
   [`extending.md`](extending.md)), not a payload object the caller built
2. Do something transport-specific with the returned `SuccessResponse` or
   `ErrorResponse` — turn it into a `JSONResponse` (FastAPI), set a gRPC
   status code, log it and move to the next queue item, or hand it back to an
   LLM as a tool result.

There's no gateway object and no `handle()` call — a `BaseController`
subclass's public async methods already return that response, because
`ExceptionFormatter.__init_subclass__` wraps every one of them at
class-definition time:

```
method(self, props)
  -> already returns a SuccessResponse/ErrorResponse?
       -> passed through unchanged (the preferred style: the method built
          it directly, translating whatever its service returned)
  -> returns a plain value?
       -> SuccessResponse(data=result)
  -> raises a DomainError?
       -> logged via self.logger (WARNING for 4xx-mapped, ERROR for 5xx)
       -> ErrorResponse (via build_error_response) — the convenience
          escape hatch for a method with nothing else to translate
  -> raises anything else?
       -> wrapped into a generic DomainError, same ErrorResponse path
          (message hidden behind "An unexpected error occurred." unless
          hide_internal_errors = False on the subclass)
  -> raises SystemExit / KeyboardInterrupt?
       -> propagates uncaught — these aren't "the business logic failed",
          they're "the process is stopping"
```

And the reverse path for exceptions:

```
DomainError.code  --(resolve_status / status_for_code)-->
    StatusMapping(http_status, grpc_status, response_code, response_status)
                                                                    |
        build_error_response() copies response_code/response_status onto
        the ErrorResponse envelope itself — every caller gets those two
        fields for free, no transport lookup required:
                                                                    |
              FastAPI: to_json_response(result) uses result.response_code
                        directly as the HTTP status — one number, not a
                        separate REST-only table to keep in sync with it
              gRPC:    context.set_code(mapping.grpc_status)
              Agent/worker: reads result.status / result.response_code
                        straight off the object it already has — no HTTP
                        handshake, no separate schema to learn
```

Neither transport adapter needs to know anything about *why* a `NotFoundError`
maps to 404/`NOT_FOUND`/`"not-found"` — that's decided once, in
`exceptions.py`, and every caller gets it for free.

## Why BaseController wraps method calls structurally

The design goal is a guarantee, not a convention: **every** consumer —
REST, worker, agent, or a gRPC servicer — gets a well-formatted response, no
matter which endpoint or call site invokes the controller. A guarantee that
depends on every developer remembering to wrap their route in a `try/except`
is not a guarantee; it's a lint rule someone will eventually forget.

So the wrapping is structural instead of aspirational:

- `ExceptionFormatter.__init_subclass__` wraps every public async method the
  moment a `BaseController` subclass is defined — there is no supported way
  to call one of those methods and skip the formatting, short of naming a
  method with a leading underscore (which marks it as an internal helper,
  not an entrypoint, by convention).
- The wrapper's `except Exception` clause is a catch-all boundary — nothing
  except `BaseException` subtypes like `SystemExit`/`KeyboardInterrupt`
  escapes uncaught.
- `DomainErrorRoute` (FastAPI-only, opt-in) is the belt-and-suspenders case:
  even if a `DomainError` is raised directly in a route handler — before
  ever reaching a controller method — the response still comes back
  formatted correctly.

None of this is enforced by code review or documentation — it's enforced by
the fact that calling a `BaseController` method *is* getting a formatted
response; there's no separate step to forget.

## Worker and gRPC callers need no adapter package

Because the core (`exceptions.py`, `controller.py`, `responses.py`,
`registry.py`) has zero dependency on FastAPI or any other transport
library, a worker script and a gRPC servicer use the exact same one line:

**Worker:**

```python
result = await UserController(db_session_factory).get_user({"user_id": "123"})
```

**gRPC servicer method** (equivalent shape, no adapter package required):

```python
from atlasboxpy_controller import ErrorResponse, status_for_code

result = await UserController(db_session_factory).get_user({"user_id": request.user_id})

if isinstance(result, ErrorResponse):
    context.set_code(status_for_code(result.error.code).grpc_status)
```

Both build the same `props` dict FastAPI's `extract_api_request` would
have built for them — assembled by hand here since there's no HTTP
request to extract it from.

Same controller, same method call, same response shape. The only thing that
differs between a REST route, a worker, and a gRPC servicer is what each one
does with the `SuccessResponse`/`ErrorResponse` it gets back — never how it
gets one.
