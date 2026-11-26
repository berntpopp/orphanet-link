"""Response-Envelope v1 §1: the primary payload key of a successful data result.

A tool's list is ``results`` (array); its grouped mapping or its record is ``result``
(object). Envelope keys stay at the top level, and so do the counts, paging and
identity echoes beside a list.
"""

from __future__ import annotations

from typing import Any

#: Ops tools return no upstream data and keep their payload flat.
_OPS_TOOLS = frozenset({"get_server_capabilities", "get_diagnostics"})
#: Collection tool -> the list its service returns, served as ``results``. The tools that
#: already return ``results`` need no entry.
_RESULTS_KEY = {
    "get_disease_ancestors": "ancestors",
    "get_disease_descendants": "descendants",
    "get_disease_genes": "genes",
    "get_disease_phenotypes": "phenotypes",
    "get_disease_prevalence": "prevalence",
    "get_disease_disability": "disability",
    "resolve_xref": "matches",
}
_TOP_LEVEL = frozenset({"success", "_meta", "orphanet_version"})


def nest_payload(tool_name: str, result: dict[str, Any]) -> None:
    """Move a success payload under its primary key in place; errors and ops tools stay flat."""
    if result.get("success") is not True or tool_name in _OPS_TOOLS:
        return
    if "results" in result or "result" in result:
        return
    key = _RESULTS_KEY.get(tool_name)
    if key is not None:
        # the lean modes drop an empty list; the primary key is still required
        result["results"] = result.pop(key, [])
    elif tool_name == "map_cross_ontology":
        # the grouped mappings are the payload; orpha_code, name and count stay beside it
        result["result"] = result.pop("mappings", {})
    else:
        result["result"] = {k: result.pop(k) for k in list(result) if k not in _TOP_LEVEL}
