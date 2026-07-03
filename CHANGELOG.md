# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- MCP `_meta` now stamps `unsafe_for_clinical_use: True` on every tool response
  (success and error paths alike), at every `response_mode`. Previously the
  research-use disclaimer lived only in the static `get_server_capabilities`
  discovery payload; it is now emitted per-call so every response is
  self-describing, matching the fleet-wide disclaimer standardization decision.

## [0.1.2] - 2026-07-03

### Fixed

- MCP `initialize` now advertises the package version in `serverInfo.version`.
  The `FastMCP(...)` constructor lacked a `version=` argument, so the handshake
  leaked the FastMCP framework version (e.g. `3.4.2`) instead of the
  orphanet-link release. The facade now passes `version=__version__`.

### Changed

- Single-source versioning: the package version now lives **only** in
  `pyproject.toml` `[project].version`. `orphanet_link.__version__` is derived
  from installed metadata via `importlib.metadata.version("orphanet-link")`
  (falling back to `0.0.0` in an uninstalled source checkout) instead of a
  hardcoded string, so `pyproject.toml`, `__version__`, `/health`, build info,
  and MCP `serverInfo.version` can no longer drift apart. A guard test
  (`tests/unit/test_version_single_source.py`) locks the invariant.
