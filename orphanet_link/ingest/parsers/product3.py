"""Parser for ``en_product3_<specialtyId>.xml`` — rare-disease classification trees.

Each product-3 file encodes one medical specialty as a ``<Classification>``
containing a recursive ``<ClassificationNode>`` tree.  Nodes reference a
``<Disorder>/<OrphaCode>`` and may contain child nodes via
``<ClassificationNodeChildList>``.

The parser walks the tree recursively and emits one edge dict per
parent→child link.  Root nodes (no parent) are never emitted as a child.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree


@dataclass
class Product3Result:
    """Parsed product-3 output.

    Attributes:
        edges: One dict per parent→child classification link.  Each dict has
            keys ``orpha_code`` (child), ``parent_code`` (parent), and
            ``specialty_id``.
        specialty: Metadata for the classification specialty, with keys
            ``specialty_id`` and ``name``, or ``None`` if not found in the
            file.
    """

    edges: list[dict] = field(default_factory=list)
    specialty: dict | None = None


def _walk(
    node: etree._Element,
    parent_code: str | None,
    specialty_id: str,
    edges: list[dict],
) -> None:
    """Recursively walk a ``<ClassificationNode>`` subtree.

    Args:
        node: A ``<ClassificationNode>`` element.
        parent_code: The ``OrphaCode`` of the parent node, or ``None`` for
            root nodes.
        specialty_id: The specialty identifier string to attach to each edge.
        edges: Accumulator list; edge dicts are appended in-place.
    """
    disorder = node.find("Disorder")
    if disorder is None:
        return

    code_el = disorder.find("OrphaCode")
    if code_el is None or not (code_el.text and code_el.text.strip()):
        return
    code = code_el.text.strip()

    if parent_code is not None:
        edges.append(
            {
                "orpha_code": code,
                "parent_code": parent_code,
                "specialty_id": specialty_id,
            }
        )

    child_list = node.find("ClassificationNodeChildList")
    if child_list is None:
        return
    for child_node in child_list.findall("ClassificationNode"):
        _walk(child_node, code, specialty_id, edges)


def parse(path: str | Path, specialty_id: str) -> Product3Result:
    """Parse a single ``en_product3_<specialtyId>.xml`` file.

    Args:
        path: Filesystem path to the XML file.
        specialty_id: The specialty identifier (matches the filename suffix and
            the ``<Classification id="...">`` attribute).

    Returns:
        A :class:`Product3Result` with ``edges`` and ``specialty`` populated.
    """
    result = Product3Result()
    tree = etree.parse(
        str(path),
        parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False),
    )
    root = tree.getroot()

    classification = root.find(".//Classification")
    if classification is not None:
        name_el = classification.find("Name")
        if name_el is not None and name_el.text and name_el.text.strip():
            result.specialty = {
                "specialty_id": specialty_id,
                "name": name_el.text.strip(),
            }

    node_root_list = root.find(".//ClassificationNodeRootList")
    if node_root_list is None:
        return result

    for root_node in node_root_list.findall("ClassificationNode"):
        _walk(root_node, None, specialty_id, result.edges)

    return result
