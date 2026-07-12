#!/usr/bin/env python3
"""Reject GitHub Actions references that are not auditable commit pins.

The check scans every YAML file under ``.github`` so composite actions cannot
silently bypass the same supply-chain control applied to workflows.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

USES_RE = re.compile(
    r"^(?P<indent>\s*(?:-\s*)?)uses:\s*(?P<reference>[^\s#]+)(?P<comment>\s+#.*)?$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _iter_yaml_files(root: Path) -> list[Path]:
    """Return every workflow and composite-action YAML file below ``.github``."""
    github = root / ".github"
    return sorted(path for suffix in ("*.yml", "*.yaml") for path in github.rglob(suffix))


def _validate_file(root: Path, path: Path) -> list[str]:
    """Return pinning violations in one GitHub Actions YAML file."""
    violations: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = USES_RE.match(line)
        if match is None:
            continue
        reference = match.group("reference")
        if reference.startswith(("./", "docker://")):
            continue
        _, separator, revision = reference.rpartition("@")
        if not separator or not SHA_RE.fullmatch(revision):
            violations.append(
                f"{path.relative_to(root)}:{line_number}: {reference} must use a full "
                "40-character commit SHA"
            )
            continue
        if match.group("comment") is None:
            violations.append(
                f"{path.relative_to(root)}:{line_number}: {reference} must include an audited "
                "version comment"
            )
    return violations


def main() -> int:
    """Check every external action reference below the selected repository root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root containing .github (default: this script's repository)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    violations = [error for path in _iter_yaml_files(root) for error in _validate_file(root, path)]
    if violations:
        print("\n".join(violations))
        return 1
    print("OK: all external GitHub Actions use audited full commit SHAs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
