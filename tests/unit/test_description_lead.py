"""D1 (Tool-Schema Documentation v1.1 rule 7): a description's first sentence says what it returns.

ponytail: the check below is copied from genefoundry-router scripts/surface.py
(`lead_states_return`); re-vendor it if this repo ever vendors surface.py.
"""

from __future__ import annotations

import re

from fastmcp import FastMCP

LEAD_CHARS = 300
_LEAD_VERBS = (  # noqa: SIM905 - copied verbatim from router surface.py
    "get fetch retrieve list look lookup search find resolve report read predict annotate "
    "compute calculate count summarize summarise map translate convert describe show check "
    "validate classify score rank query browse discover explain compare diff normalize normalise "
    "expand evaluate assess enumerate identify locate export download match suggest recommend "
    "inspect generate render estimate"
).split()
_VERB_LEAD = re.compile(
    rf"^(?:use this (?:tool )?to )?(?:{'|'.join(_LEAD_VERBS)})(?:s|es|ies)?\b", re.IGNORECASE
)
_RETURNS = re.compile(
    r"(?<!not )(?<!n't )(?<!n\u2019t )(?<!never )\breturn(?:s|ed|ing)?\b(?!\s*[~<\d])|→|->",
    re.IGNORECASE,
)
_FIELD_LIST = re.compile(r"\w+\W+\w+[^:]*:\s+[^.;:]+,")
_SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+")


def lead_states_return(description: str | None) -> bool:
    text = " ".join((description or "").split())
    lead = _SENTENCE_END.split(text, maxsplit=1)[0][:LEAD_CHARS]
    return bool(_VERB_LEAD.match(lead) or _RETURNS.search(lead) or _FIELD_LIST.search(lead))


async def test_every_tool_description_leads_with_what_it_returns(facade: FastMCP) -> None:
    failing = [t.name for t in await facade.list_tools() if not lead_states_return(t.description)]
    assert failing == []
