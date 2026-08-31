# Controller Gateway

A small workspace of independent, flat-named Python packages — each its
own `pyproject.toml`, installable on its own, no shared namespace between
them (see [`packages/atlasboxpy_controller/CHANGELOG.md`](packages/atlasboxpy_controller/CHANGELOG.md)
for why: PyTorch/NumPy/ROS/Flask all settled on this shape for a family of
related packages, not PEP 420 namespace packages).

## Packages

- [`packages/atlasboxpy_controller/`](packages/atlasboxpy_controller/) —
  a `BaseController` base class that wraps every public async method
  automatically, so a call from an API route, a worker, or an agent
  always comes back as a formatted `SuccessResponse`/`ErrorResponse` —
  no gateway object, no per-method decorator, no `try/except` in your
  routes.
- [`packages/atlasboxpy_repository/`](packages/atlasboxpy_repository/) —
  a `BaseRepository` base class with a pluggable, read-through cache —
  swap between an in-memory dict and Redis via two config constants.

## Examples

[`examples/`](examples/) has runnable demo apps exercising both packages
together — see `examples/fastapi_kanban` for the fullest one (Starlette +
SQLite, real cache invalidation via `atlasboxpy_repository`, consistent
error handling via `atlasboxpy_controller`).

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE), and each package's own copies.
