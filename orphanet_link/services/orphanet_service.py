"""Orchestration over the read-only Orphanet repository.

Returns plain dicts (no envelope); the MCP layer owns ``success``/``_meta``.
Every record payload carries ``orphanet_version`` (from build provenance) for
grounding. The resolution cascade (ORPHAcode -> exact label -> xref CURIE)
returns the match provenance and raises typed exceptions instead of silently
collapsing ambiguity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orphanet_link.constants import HPO_FREQUENCIES
from orphanet_link.exceptions import DataUnavailableError, InvalidInputError, NotFoundError
from orphanet_link.identifiers import normalize_hpo_id, normalize_orpha_code, parse_curie
from orphanet_link.services.compose import compose_sections
from orphanet_link.services.pagination import page_fields
from orphanet_link.services.resolution import resolve
from orphanet_link.services.shaping import (
    DEFAULT_RESPONSE_MODE,
    group_xrefs,
    shape,
    shape_search_hit,
)

_MAX_LIMIT = 1000


class OrphanetService:
    """High-level orchestrator over the :class:`OrphanetRepository`."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        repo: Any | None = None,
    ) -> None:
        """Initialise; supply ``repo`` for injection or ``db_path`` for lazy open."""
        self._db_path = Path(db_path) if db_path is not None else None
        self._repo = repo

    @property
    def repo(self) -> Any:
        """Return the (lazily-opened) repository; raises if unavailable."""
        if self._repo is not None:
            return self._repo
        if self._db_path is not None:
            from orphanet_link.data.repository import OrphanetRepository

            self._repo = OrphanetRepository(self._db_path)
            return self._repo
        raise DataUnavailableError(
            "The Orphanet index is not built. Run `orphanet-link-data build`."
        )

    def _resolve_for_hierarchy(self, term: str) -> tuple[str, str | None]:
        """Resolve term to (orpha_code, name); accepts classification-only codes."""
        code = normalize_orpha_code((term or "").strip())
        if code is not None:
            record = self.repo.get_disorder(code)
            return code, (record["name"] if record else None)
        resolved = resolve(self.repo, term)
        return resolved["orpha_code"], resolved["name"]

    def _orphanet_version(self) -> str | None:
        """Return the Orphanet release string for grounding, or ``None``."""
        try:
            meta = self.repo.get_meta()
            return meta.get("orphanet_version") if meta else None
        except DataUnavailableError:  # pragma: no cover
            return None

    def _meta(self, meta: dict[str, Any] | None, key: str) -> Any:
        return meta.get(key) if meta else None

    def get_diagnostics(self) -> dict[str, Any]:
        """Return data-source provenance and freshness; never raises if unbuilt."""
        if self._repo is None and self._db_path is None:
            return {
                "index_built": False,
                "db_path": None,
                "message": "Local Orphanet index not built. Run `orphanet-link-data build`.",
            }
        try:
            repo = self.repo
            meta = repo.get_meta()
            return {
                "index_built": True,
                # Basename only — never leak the absolute host path to callers.
                "db_path": repo._path.name,
                "orphanet_version": self._meta(meta, "orphanet_version"),
                "orphanet_date": self._meta(meta, "orphanet_date"),
                "schema_version": self._meta(meta, "schema_version"),
                "build_utc": self._meta(meta, "build_utc"),
                "disorder_count": self._meta(meta, "disorder_count"),
            }
        except DataUnavailableError as exc:
            return {
                "index_built": False,
                "db_path": self._db_path.name if self._db_path else None,
                "message": str(exc),
            }

    def resolve_disease(
        self, query: str, response_mode: str = DEFAULT_RESPONSE_MODE
    ) -> dict[str, Any]:
        """Resolve any id/label/xref to a canonical Orphanet term with provenance."""
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError(
                "query must be a non-empty ORPHAcode, label, or xref.", field="query"
            )
        resolved = resolve(self.repo, raw)
        return {
            "query": raw,
            "orpha_code": resolved["orpha_code"],
            "name": resolved["name"],
            "match_type": resolved["match_type"],
            "orphanet_version": self._orphanet_version(),
        }

    def search_diseases(
        self,
        query: str,
        limit: int = 25,
        offset: int = 0,
        include_obsolete: bool = False,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Free-text search over disease name/synonyms."""
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError("query must be a non-empty search string.", field="query")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        result = self.repo.search(
            raw, limit=limit, offset=offset, include_obsolete=include_obsolete
        )
        hits = result.get("results", [])
        total = result.get("total", len(hits))
        results = [shape_search_hit(hit, response_mode) for hit in hits]
        return {
            "query": raw,
            "results": results,
            **page_fields(total=total, returned=len(results), limit=limit, offset=offset),
            "orphanet_version": self._orphanet_version(),
        }

    def get_disease(
        self,
        term: str,
        response_mode: str = DEFAULT_RESPONSE_MODE,
        fields: list[str] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return the full disease record, optionally composing extra sections.

        ``include`` (any of genes/phenotypes/prevalence/disability) attaches those
        association sections to the single record so a full entity needs one call
        rather than a per-section fan-out (P1.1). Unknown sections raise invalid_input.
        """
        resolved = resolve(self.repo, term)
        code = resolved["orpha_code"]
        record = self.repo.get_disorder(code)
        if record is None:  # pragma: no cover
            raise NotFoundError(f"No Orphanet disorder for ORPHA:{code}.")
        nat = self.repo.get_natural_history(code)
        cls = self.repo.get_classification(code)
        payload: dict[str, Any] = {
            "orpha_code": code,
            "name": record["name"],
            "disorder_type": record.get("disorder_type"),
            "definition": record.get("definition"),
            "synonyms": record.get("synonyms", []),
            "xrefs": group_xrefs(self.repo.get_xrefs(code)),
            "age_of_onset": nat.get("age_of_onset", []),
            "inheritance": nat.get("inheritance", []),
            "parents": cls.get("parents", []),
            "children": cls.get("children", []),
            "orphanet_version": self._orphanet_version(),
        }
        if include:
            payload.update(compose_sections(self.repo, code, include))
        return shape(payload, response_mode, fields=fields)

    def get_disease_genes(
        self, term: str, response_mode: str = DEFAULT_RESPONSE_MODE
    ) -> dict[str, Any]:
        """Return gene associations for a disorder."""
        resolved = resolve(self.repo, term)
        code = resolved["orpha_code"]
        genes = self.repo.get_genes(code)
        return shape(
            {
                "orpha_code": code,
                "name": resolved["name"],
                "genes": genes,
                "count": len(genes),
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def get_disease_phenotypes(
        self, term: str, frequency: str | None = None, response_mode: str = DEFAULT_RESPONSE_MODE
    ) -> dict[str, Any]:
        """Return HPO phenotype annotations for a disorder.

        A non-null ``frequency`` is validated against the Orphanet HPO frequency
        buckets (``HPO_FREQUENCIES``): an unrecognised label raises ``invalid_input``
        (``field="frequency"``, carrying ``allowed_values``) instead of silently
        returning ``count: 0``, mirroring ``find_diseases_by_phenotype``'s id
        handling. A recognised bucket with no matching rows still returns
        ``count: 0`` (a legitimate empty, not an error).
        """
        if frequency is not None and frequency not in HPO_FREQUENCIES:
            raise InvalidInputError(
                f"'{frequency}' is not a valid HPO frequency label.",
                field="frequency",
                allowed=list(HPO_FREQUENCIES),
                hint="get_disease_phenotypes(term, frequency=, response_mode=)",
            )
        resolved = resolve(self.repo, term)
        code = resolved["orpha_code"]
        phenotypes = self.repo.get_phenotypes(code, frequency)
        return shape(
            {
                "orpha_code": code,
                "name": resolved["name"],
                "phenotypes": phenotypes,
                "count": len(phenotypes),
                "frequency_filter": frequency,
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def get_disease_prevalence(
        self, term: str, response_mode: str = DEFAULT_RESPONSE_MODE
    ) -> dict[str, Any]:
        """Return prevalence records for a disorder."""
        resolved = resolve(self.repo, term)
        code = resolved["orpha_code"]
        prevalence = self.repo.get_prevalence(code)
        return shape(
            {
                "orpha_code": code,
                "name": resolved["name"],
                "prevalence": prevalence,
                "count": len(prevalence),
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def get_disease_natural_history(
        self, term: str, response_mode: str = DEFAULT_RESPONSE_MODE
    ) -> dict[str, Any]:
        """Return natural history (onset + inheritance) for a disorder."""
        resolved = resolve(self.repo, term)
        code = resolved["orpha_code"]
        nat = self.repo.get_natural_history(code)
        return shape(
            {
                "orpha_code": code,
                "name": resolved["name"],
                "age_of_onset": nat.get("age_of_onset", []),
                "inheritance": nat.get("inheritance", []),
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def get_disease_disability(
        self, term: str, response_mode: str = DEFAULT_RESPONSE_MODE
    ) -> dict[str, Any]:
        """Return functional consequences (disability) for a disorder."""
        resolved = resolve(self.repo, term)
        code = resolved["orpha_code"]
        disability = self.repo.get_disability(code)
        return shape(
            {
                "orpha_code": code,
                "name": resolved["name"],
                "disability": disability,
                "count": len(disability),
                # Distinguish "no Orphadata functional-consequence annotation" (a valid,
                # common state) from an error: agents must not read count:0 as failure.
                "coverage": "present" if disability else "none",
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def get_disease_classification(
        self, term: str, response_mode: str = DEFAULT_RESPONSE_MODE
    ) -> dict[str, Any]:
        """Return immediate classification parents and children for a disorder."""
        resolved = resolve(self.repo, term)
        code = resolved["orpha_code"]
        cls = self.repo.get_classification(code)
        return shape(
            {
                "orpha_code": code,
                "name": resolved["name"],
                "parents": cls.get("parents", []),
                "children": cls.get("children", []),
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def get_disease_ancestors(
        self,
        term: str,
        limit: int = 200,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Return transitive ancestors of a disorder (closure walk)."""
        code, name = self._resolve_for_hierarchy(term)
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        result = self.repo.get_ancestors(code, limit=limit, offset=offset)
        rows = result.get("results", [])
        total = result.get("total", len(rows))
        return shape(
            {
                "orpha_code": code,
                "name": name,
                "ancestors": rows,
                **page_fields(total=total, returned=len(rows), limit=limit, offset=offset),
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def get_disease_descendants(
        self,
        term: str,
        limit: int = 200,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Return transitive descendants of a disorder (closure walk)."""
        code, name = self._resolve_for_hierarchy(term)
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        result = self.repo.get_descendants(code, limit=limit, offset=offset)
        rows = result.get("results", [])
        total = result.get("total", len(rows))
        return shape(
            {
                "orpha_code": code,
                "name": name,
                "descendants": rows,
                **page_fields(total=total, returned=len(rows), limit=limit, offset=offset),
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def map_cross_ontology(
        self,
        term: str,
        prefixes: list[str] | None = None,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Return all cross-ontology mappings for a disorder, grouped by source."""
        resolved = resolve(self.repo, term)
        code = resolved["orpha_code"]
        grouped = group_xrefs(self.repo.get_xrefs(code), prefixes)
        return shape(
            {
                "orpha_code": code,
                "name": resolved["name"],
                "mappings": grouped,
                "count": sum(len(v) for v in grouped.values()),
                "prefixes_filter": prefixes,
                "orphanet_version": self._orphanet_version(),
            },
            response_mode,
        )

    def resolve_xref(
        self,
        xref_id: str,
        limit: int = 50,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Reverse lookup: external CURIE -> Orphanet disorders that cross-reference it."""
        raw = (xref_id or "").strip()
        if not raw:
            raise InvalidInputError(
                "xref_id must be a non-empty CURIE like OMIM:607131.", field="xref_id"
            )
        prefix, local = parse_curie(raw)
        if prefix is None:
            raise InvalidInputError(
                f"'{raw}' is not a valid CURIE (expected PREFIX:LOCAL, e.g. OMIM:607131).",
                field="xref_id",
            )
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        all_hits = self.repo.resolve_xref(prefix, local)
        total = len(all_hits)
        hits = all_hits[offset : offset + limit]
        results = [{"orpha_code": h["orpha_code"], "name": h["name"]} for h in hits]
        return {
            "xref_id": raw,
            "source": prefix,
            "object_id": local,
            "matches": results,
            **page_fields(total=total, returned=len(results), limit=limit, offset=offset),
            "orphanet_version": self._orphanet_version(),
        }

    def find_diseases_by_gene(
        self,
        gene_symbol: str,
        limit: int = 50,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Find disorders associated with a gene symbol.

        Gene symbols have no strict canonical format to validate against, so any
        non-empty token is accepted (whitespace-trimmed; matched case-insensitively
        in the repository). An unknown symbol returns ``total: 0`` by design — that
        is a genuine "no Orphanet disorder records this gene", not a malformed input.
        """
        raw = (gene_symbol or "").strip()
        if not raw:
            raise InvalidInputError(
                "gene_symbol must be a non-empty HGNC gene symbol.", field="gene_symbol"
            )
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        result = self.repo.find_disorders_by_gene(raw, limit=limit, offset=offset)
        hits = result.get("results", [])
        total = result.get("total", len(hits))
        return {
            "gene_symbol": raw,
            "results": hits,
            **page_fields(total=total, returned=len(hits), limit=limit, offset=offset),
            "orphanet_version": self._orphanet_version(),
        }

    def find_diseases_by_phenotype(
        self,
        hpo_id: str,
        limit: int = 50,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Find disorders annotated with an HPO term.

        The ``hpo_id`` is validated for shape (``HP:NNNNNNN``) and normalized before
        the lookup, mirroring ``resolve_xref``'s CURIE handling: a malformed id
        raises ``invalid_input`` (``field="hpo_id"``) instead of silently returning
        an empty result, while a well-formed-but-absent id still returns ``total: 0``.
        """
        raw = (hpo_id or "").strip()
        if not raw:
            raise InvalidInputError(
                "hpo_id must be a non-empty HPO term id like HP:0000256.", field="hpo_id"
            )
        canonical = normalize_hpo_id(raw)
        if canonical is None:
            raise InvalidInputError(
                f"'{raw}' is not a valid HPO term id (expected HP:NNNNNNN, e.g. HP:0000256).",
                field="hpo_id",
            )
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        result = self.repo.find_disorders_by_phenotype(canonical, limit=limit, offset=offset)
        hits = result.get("results", [])
        total = result.get("total", len(hits))
        return {
            "hpo_id": canonical,
            "results": hits,
            **page_fields(total=total, returned=len(hits), limit=limit, offset=offset),
            "orphanet_version": self._orphanet_version(),
        }

    # NOTE: batch is implemented in the MCP tool layer (mcp/tools/batch.py), which
    # loops these single-item methods and shapes per-item {ok, error_code, ...} rows
    # via the shared classify_exception. No service-level *_batch helpers exist (a
    # prior pair returned a divergent {success, error} shape and were unused).
