"""Orphanet MCP tool registration functions (one register_* per domain module)."""

from __future__ import annotations

from orphanet_link.mcp.tools.associations import register_association_tools
from orphanet_link.mcp.tools.batch import register_batch_tools
from orphanet_link.mcp.tools.classification import register_classification_tools
from orphanet_link.mcp.tools.discovery import register_discovery_tools
from orphanet_link.mcp.tools.diseases import register_disease_tools
from orphanet_link.mcp.tools.xref import register_xref_tools

__all__ = [
    "register_association_tools",
    "register_batch_tools",
    "register_classification_tools",
    "register_discovery_tools",
    "register_disease_tools",
    "register_xref_tools",
]
