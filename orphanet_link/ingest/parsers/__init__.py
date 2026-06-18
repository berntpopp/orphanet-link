"""Streaming ``lxml.iterparse`` parsers, one module per Orphadata product.

Each parser yields normalized row dicts keyed on ``orpha_code`` (string of bare
ORPHAcode digits). The shared helpers live in ``_common``.
"""
