# The Validation Layer That's Trapped Inside Your HTTP Framework

*Pydantic and FastAPI make request validation feel solved. It isn't — it's just solved for the one caller you originally had in mind. The moment a worker, an agent, or a gRPC service needs the same business logic, the coupling you didn't know you had starts costing you.*

---

## The ticket that started this

The ticket read something like: *"Clearing a user's middle name from their profile wipes their last name too."*

The endpoint was an unremarkable `PATCH /users/{id}`, backed by a model like this:

```python
class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
```

And a handler like this:

```python
@app.patch("/users/{id}")
async def update_user(id: int, update: UserUpdate):
    for field, value in update.dict().items():
        setattr(user, field, value)
    await db.save(user)
```

The bug is almost too simple once you see it: `Optional[str] = None` can't tell the difference between *"the client explicitly set this to null"* and *"the client never mentioned this field."* A frontend that only sends the fields it changed — the normal, sane way to build a PATCH request — ends up wiping every field it didn't send, because `update.dict()` includes the defaults too.

The fix is one keyword: `update.model_dump(exclude_unset=True)`. Fine. Ticket closed.

Except it wasn't really about that one endpoint. It was the first visible symptom of something structural.

## Three bugs, one root cause

Zoom out a little and a pattern shows up. Here are three gaps in the Pydantic/FastAPI validation story that look unrelated on the surface:

**1. The PATCH bug above.** Solvable, but only if every endpoint author remembers `exclude_unset=True` every single time — it's opt-in, not the default, and nothing warns you when you forget it.

**2. Validators can't be async.** `field_validator` and `model_validator` run synchronously, even inside an `async def` route. So the moment a business rule needs I/O — *is this email already registered?*, *does this SKU exist?* — it can't live in the model. It has to move into the route body, after "validation" has already technically passed. Now your actual business rules are split across two places, and only one of them is enforced by the type system.

**3. `response_model` fails after the side effect already happened.** FastAPI re-validates your return value against the declared response schema. If your endpoint logic returns something that doesn't quite match — a `None` where a `str` was expected, a field your ORM didn't hydrate — you get an opaque 500 at serialization time. Often *after* the database write already committed. The failure arrives too late to matter for correctness and too vague to debug quickly.

None of these are really about *validating shapes*. Pydantic is excellent at that part. They're about the fact that business-rule enforcement, error formatting, and response shaping have all quietly become the HTTP layer's job — code written under the assumption that it's always running inside one request/response cycle, for one waiting HTTP client.

That assumption is invisible for as long as HTTP is the only caller. It stops being invisible the moment something else needs the same logic.

## Example 1: the worker that drains the event queue

Say your system also has a background worker consuming a `UserUpdated` event off a queue — Kafka, SQS, a Redis stream, doesn't matter — to keep a search index and a couple of downstream services in sync. It needs to apply *the same* update logic as the PATCH endpoint: the same partial-update semantics, the same business rules (say, a rule that email domain changes require re-verification), the same "was this actually cleared or just not sent" distinction.

At this point you have exactly two bad options.

**Duplicate the logic.** The worker gets its own version of the update path — its own unset-handling, its own business rule checks, its own error handling. It works fine on day one. Six months later, someone adds a new business rule to the API route (say, a domain allow-list check) and forgets the worker exists. Now bad data can slip in through the queue path, silently, because the two implementations drifted apart. This isn't a hypothetical — it's the default outcome of copy-pasted business logic with no mechanism forcing the copies to stay in sync.

**Call your own API over HTTP.** The worker makes a request to `localhost:8000/users/{id}` (or an internal service URL) purely to reuse validation and error handling it already wrote for browsers. Now a same-process, same-deploy operation — conceptually just a function call — has to survive a real network hop: connection resets, timeouts, retries-on-retries, an auth story for a trust boundary that shouldn't need one, and JSON serialization in both directions for data that was already in memory. You've turned "call a function" into "operate a distributed system," to avoid writing the validation logic twice.

Both are the same tax, paid two different ways: the validation and error-handling contract lives *behind* the router instead of *inside* the controller itself.

The fix: make the controller enforce that contract itself. Not by routing every call through a separate gateway object, but by having its own base class wrap every public method automatically, the moment the class is defined:

```python
# controllers.py — shared by the FastAPI route and the worker below
from atlasboxpy_controller import BaseController

class UserController(BaseController):
    def __init__(self, user_service):
        super().__init__()
        self.user_service = user_service

    async def apply_update(self, user_id, patch):
        return await self.user_service.apply_update(user_id, patch)
```

```python
# worker.py — drains an event queue, no REST layer involved
from atlasboxpy_controller.exceptions import is_retryable
from app.controllers import UserController

controller = UserController(user_service)

async def drain_event_queue(queue):
    async for event in queue:
        result = await controller.apply_update(event.user_id, event.patch)

        if result.status == "error":
            if is_retryable(result.error.code):
                await queue.retry_later(event)
            else:
                logger.warning("dead-lettering event %s: %s", event.id, result.error.code)
                await queue.dead_letter(event)
        else:
            await queue.ack(event)
```

`UserController` here is the *exact same class* the FastAPI route uses — there's no `ValidatorGateway` to construct around it, and no `.handle()` call. `apply_update` already returns a formatted `SuccessResponse`/`ErrorResponse` the moment it's called, because `BaseController` wrapped it automatically when the class was defined. No HTTP call, no second implementation, no drift.

Note what's deliberately *not* here: there's no attached recovery engine deciding on the worker's behalf whether to retry. `is_retryable(code)` gives the worker a real, structured answer — instead of a string it has to guess at — but the retry loop itself, the backoff, the dead-letter threshold, stays the worker's own code. That's a deliberate boundary: the package's job is making every caller agree on *what happened and whether it's worth retrying*, not owning the retry policy itself.

## The shape of the fix

Stated plainly, the pattern is: **stop letting the router own the contract, and stop routing every caller through a separate object to get it.** Subclass a controller base class that wraps every public method automatically — call in, formatted response out, try/except guaranteed by inheritance — and let every caller use it directly.

```
frontend > thin api_route \
                            \
event_queue worker  ------>  Controller (BaseController) -> Services -> Repository
                            /
security agent ------------/
```

That gives you, structurally rather than by convention:

- **One call path** — there's no route or worker that "forgot" to wrap its call in a try/except, because the method it's calling was never unwrapped to begin with. Unlike routing everything through a separate gateway object, there's nothing extra to remember to construct at every call site, either.
- **One response shape** — a `SuccessResponse` or `ErrorResponse`, whether the caller is a browser, a queue consumer, or an agent.
- **One error vocabulary** — a small `DomainError` hierarchy (`NotFoundError`, `ConflictError`, `PermissionDeniedError`, ...), each carrying its own HTTP status, gRPC status mapping, and a `retryable` flag, so a service never has to know which transport is calling it, and a caller never has to guess whether trying again could possibly help.
- **One place a failure gets logged** — automatically, through `self.logger`, without any caller having to wire up a hook.

This isn't a new idea — business logic in the center, transports as interchangeable edges around it, is an old pattern. What's changed is the trigger: for a long time the only "other caller" anyone needed to support was a CLI script or a test harness. Now it's routinely an autonomous agent, and agents make the cost of not having done this a lot more visible, a lot faster.

## Example 2: the security agent looking for exposed card numbers in your logs

Here's where it gets sharper. Say you're running an autonomous agent as part of a recurring security review: it pulls batches of application logs, looks for sensitive data that shouldn't be there — credit card numbers, SSNs, API keys, anything matching your PII patterns — and files a finding whenever it spots one, so a human can follow up and get it redacted at the source.

This agent needs to call into real business logic, not just emit a report to stdout:

- **Deduplication** — don't file five findings for the same log line the agent happens to re-scan.
- **PCI-scoping** — a finding involving a card number needs a different tag and a different downstream workflow than a finding involving an email address.
- **Rate limiting** — an agent in a loop is exactly the kind of caller that can accidentally flood a queue if nothing stops it.

All of that is *identical* to the business logic behind the human-facing "flag a finding" button in your security dashboard. It shouldn't be reimplemented for the agent — it should be the same controller, called directly:

```python
# security_agent.py — autonomous log-review agent, no REST layer involved
from atlasboxpy_controller.exceptions import is_retryable
from app.controllers import SecurityFindingController

controller = SecurityFindingController(finding_service)

async def review_log_batch(log_lines: list[str]):
    for line in log_lines:
        for finding in detect_sensitive_data(line):  # e.g. a Luhn-valid card number, an SSN pattern, an email
            result = await controller.flag_finding(
                finding_type=finding.kind,          # "credit_card", "ssn", "pii_email", ...
                log_ref=finding.log_ref,
                masked_value=finding.masked_value,  # the raw sensitive value never leaves the detector
            )

            if result.status == "error" and result.error.code == "permission_denied":
                await escalate_to_security_team(finding, result.error)
```

A couple of things worth calling out about `detect_sensitive_data` before going further: it's a stand-in for whatever detection approach you use — a Luhn checksum plus a digit-length filter catches most exposed card numbers, and regex patterns cover common PII shapes — and the only hard rule that matters architecturally is that the raw sensitive value never gets passed downstream. The controller receives `masked_value`, not the card number itself. That's true regardless of which pattern you use, but it's worth stating plainly since this example handles real sensitive data.

The part that's specific to this pattern is what happens when `flag_finding` comes back with an error. An agent, unlike a human clicking a button, can't just read an error message and decide what to do — it needs a *structured* signal to reason over, because it's going to keep running unattended. This is exactly what the typed `DomainError` codes are for:

- `already_exists` — this finding was already filed. Not a failure at all, just move to the next line.
- `upstream_error` — the redaction pipeline is temporarily down. `is_retryable("upstream_error")` returns `True`, so the agent knows it's safe to back off and try again — the backoff loop itself is the agent's own code, not something hidden inside the package.
- `permission_denied` — the agent's service account doesn't have write access to file PCI-scoped findings. **Not retryable, ever** — retrying a permission failure can't succeed, and an agent that doesn't know that will burn its entire loop budget hammering a wall. This is why `DomainError` subclasses carry a `retryable` flag: `PermissionDeniedError.retryable` is `False` by construction, and `is_retryable("permission_denied")` reflects that — so the agent's own decision logic can check it before deciding whether to try again or escalate to a human, without parsing an error string to guess.

That last point is really the payoff of the whole pattern for agent workflows specifically. An agent operating unattended needs to know the difference between *"try again"* and *"stop and get a human"* far more urgently than a person clicking a retry button does. Giving it that distinction as a typed, structured field — rather than a string it has to parse or guess at — is what makes it safe to let the agent run the loop unsupervised in the first place. Deciding what to actually *do* with that signal is still the agent's job; the package's only promise is that the signal itself is trustworthy.

## Where this leaves you

The insight underneath all of this is small, but it compounds: **put the enforced validation and error-handling contract inside the controller itself, not behind the router, and not behind a separate object every caller has to remember to construct.** Do that, and a background worker, an autonomous agent, and eventually a gRPC servicer all get identical guarantees — one call path, one response shape, one error vocabulary — without a single line of adapter code written on their behalf. They just import the same controller class and call it directly.

The alternative — the thing that got that PATCH bug filed in the first place — is validation logic that only knows how to be an HTTP framework's helper. It works fine right up until something other than a browser needs to ask your business logic a question. Increasingly, something else always does.
