"""The LOC-budget exemption for vendored probes must be NARROW, and it must be derived.

``tests/conformance/behaviour.py`` is 650+ lines and vendored byte-identical from
genefoundry-router. It cannot be split — the vendoring contract is what makes every
``-link`` repo run the same gate — so ``check_file_size.py`` exempts it.

An exemption is a hole in a guard, and a hole that is wider than its reason is how the
guard stops guarding. These tests pin it to exactly its reason:

* a vendored probe (declares itself vendored, lives in tests/conformance/) is exempt;
* a repo-authored file in the SAME directory is NOT;
* a file elsewhere claiming to be "vendored" is NOT;
* the budget still fails on a genuinely oversized repo file.

Both halves of the partition are asserted, and there is no third bucket.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.check_file_size import MAX_LINES, is_vendored

REPO = Path(__file__).resolve().parents[2]


def _write(path: Path, *, lines: int, docstring: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"x = {i}" for i in range(lines))
    path.write_text(f'"""{docstring}"""\n\n{body}\n', encoding="utf-8")


def test_the_real_vendored_probe_is_exempt() -> None:
    """The file this exemption exists for."""
    probe = REPO / "tests" / "conformance" / "behaviour.py"
    assert probe.exists()
    assert probe.read_text(encoding="utf-8").count("\n") + 1 > MAX_LINES, (
        "if the vendored probe has shrunk under the budget, this exemption is no longer "
        "load-bearing and should be reconsidered"
    )
    assert is_vendored(probe, REPO)


def test_a_repo_authored_file_in_the_same_directory_is_not_exempt(tmp_path: Path) -> None:
    """The exemption is not "anything under tests/conformance/"."""
    ours = REPO / "tests" / "conformance" / "test_transport_mode.py"
    assert ours.exists()
    # It does not declare itself vendored, so it stays budgeted (it is simply short).
    assert not is_vendored(ours, REPO)


def test_a_file_outside_the_vendor_directory_cannot_claim_the_exemption(tmp_path: Path) -> None:
    """Saying "vendored" is not enough; it must actually live with the vendored probes."""
    impostor = REPO / "orphanet_link" / "_loc_budget_impostor.py"
    try:
        _write(impostor, lines=10, docstring="Vendored byte-identical from somewhere.")
        assert not is_vendored(impostor, REPO)
    finally:
        impostor.unlink(missing_ok=True)


def test_the_budget_still_fails_on_an_oversized_repo_file() -> None:
    """Prove the guard by breaking it: an oversized non-vendored file must be caught."""
    offender = REPO / "orphanet_link" / "_loc_budget_offender.py"
    try:
        _write(offender, lines=MAX_LINES + 50, docstring="A sprawling module.")
        result = subprocess.run(
            [sys.executable, "scripts/check_file_size.py"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, "an oversized repo file must fail the budget"
        assert "_loc_budget_offender.py" in result.stdout
    finally:
        offender.unlink(missing_ok=True)


def test_the_budget_passes_on_the_real_tree() -> None:
    """And with only the vendored probe over the cap, the tree is clean."""
    result = subprocess.run(
        [sys.executable, "scripts/check_file_size.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "vendored file(s) exempt" in result.stdout
