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
