# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Domain exception hierarchy (`DomainError` and subclasses) with HTTP/gRPC status mapping.
- `Controller` protocol, `BaseController`, and `validate_controller`.
- `ValidatorGateway` core with `handle()` as the single enforced call path.
- `SuccessResponse` / `ErrorResponse` envelope models.
- `GatewayConfig`.
- `validator_gateway.classifying.ClassifyingValidatorGateway` and `SourceJson` — an
  opt-in gateway style that classifies failures into a developer-defined enum and
  resolves each case via a visible `match`/`case` block (custom messaging, or a
  redirect to a different gateway), instead of the default uniform
  `build_error_response(exc)`. `_severity_fallback`/`_resolve` are `abstractmethod`s,
  so a subclass can't skip implementing them. `validator-gateway add-feature <name>`
  scaffolds a starting controller + gateway pair built on it.
