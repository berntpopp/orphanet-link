"""Unified entrypoint for orphanet-link (REST + MCP).

Placeholder during build-out; the full unified/http/stdio dispatch is wired in a
later task (server_manager). Importing this module must stay side-effect free.
"""

from __future__ import annotations


def main() -> None:
    """Console-script entrypoint (``orphanet-link``)."""
    raise SystemExit("orphanet-link server is not wired yet; see implementation plan.")


if __name__ == "__main__":
    main()
