"""Read-only SQLite repository for the built Orphanet index (CONTRACT BARRIER).

All indexes are pre-computed by the builder, so this layer only reads rows.
FTS5 queries are sanitized so raw user text never reaches ``MATCH`` (which can
raise on operator characters like ``( : -``).  On FTS error a ``LIKE`` fallback
is used.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from orphanet_link.constants import MAPPING_RELATION_RANK
from orphanet_link.exceptions import DataUnavailableError

_FTS_TOKEN_RE = re.compile(r"[^\s\"]+")

#: Stable ``CASE`` expression ranking mapping relations (lower = stronger).
_MAPPING_CASE = (
    "CASE mapping_relation "
    + " ".join(f"WHEN '{rel}' THEN {rank}" for rel, rank in MAPPING_RELATION_RANK.items())
    + " ELSE 99 END"
)


class OrphanetRepository:
    """Read-only access to the built Orphanet SQLite index."""

    def __init__(self, db_path: str | Path) -> None:
        """Open a read-only connection; raises ``DataUnavailableError`` if missing."""
        self._path = Path(db_path)
        if not self._path.exists():
            raise DataUnavailableError(
                f"Orphanet database not found at {self._path}. "
                "Build it with `orphanet-link-data build`."
            )
        try:
            self._conn = sqlite3.connect(
                f"file:{self._path}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.Error as exc:  # pragma: no cover
            raise DataUnavailableError(
                f"Cannot open Orphanet database at {self._path}: {exc}."
            ) from exc
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _fts_query(text: str) -> str:
        """Build a safe FTS5 ``MATCH`` string; quote each token, prefix the last.

        Embedded double-quotes are escaped.  Returns ``'""'`` for blank input.
        """
        tokens = _FTS_TOKEN_RE.findall(text or "")
        if not tokens:
            return '""'
        quoted: list[str] = []
        for tok in tokens[:-1]:
            quoted.append('"' + tok.replace('"', '""') + '"')
        last = tokens[-1].replace('"', '""')
        quoted.append('"' + last + '"*')
        return " ".join(quoted)

    # -- provenance ------------------------------------------------------------

    def get_meta(self) -> dict[str, Any]:
        """Return build provenance from the single-row ``meta`` table."""
        try:
            row = self._conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            raise DataUnavailableError(
                f"Orphanet database at {self._path} is unreadable: {exc}."
            ) from exc
        return dict(row) if row is not None else {}

    # -- disorder records ------------------------------------------------------

    def get_disorder(self, code: str) -> dict[str, Any] | None:
        """Return the disorder row + ``synonyms`` list for ``code``, or ``None``."""
        row = self._conn.execute("SELECT * FROM disorder WHERE orpha_code = ?", (code,)).fetchone()
        if row is None:
            return None
        record: dict[str, Any] = dict(row)
        syn_rows = self._conn.execute(
            "SELECT synonym FROM disorder_synonym WHERE orpha_code = ? ORDER BY synonym",
            (code,),
        ).fetchall()
        record["synonyms"] = [r["synonym"] for r in syn_rows]
        return record

    def resolve_label(self, label: str) -> list[dict[str, Any]]:
        """Exact match via ``disorder_lookup`` (UPPER-cased); returns ``{orpha_code, name, label_type}``."""
        rows = self._conn.execute(
            "SELECT dl.orpha_code, d.name, dl.label_type "
            "FROM disorder_lookup dl "
            "JOIN disorder d ON d.orpha_code = dl.orpha_code "
            "WHERE dl.lookup_label = ?",
            (label.upper(),),
        ).fetchall()
        return [
            {"orpha_code": r["orpha_code"], "name": r["name"], "label_type": r["label_type"]}
            for r in rows
        ]

    def search(
        self,
        query: str,
        limit: int = 25,
        offset: int = 0,
        include_obsolete: bool = False,
    ) -> dict[str, Any]:
        """FTS5 search with LIKE fallback; returns ``{results, total, limit, offset}``."""
        match = self._fts_query(query)
        obs_clause = "" if include_obsolete else " AND d.is_obsolete = 0"
        sql = (
            "SELECT f.orpha_code, d.name, bm25(disorder_fts) AS score "  # noqa: S608
            "FROM disorder_fts f "
            "JOIN disorder d ON d.orpha_code = f.orpha_code "
            f"WHERE disorder_fts MATCH ?{obs_clause} "
            # score (bm25, best-first); CAST tiebreak makes equal-score ties an
            # ENFORCED contract (ORPHAcode ascending), not an implicit row order.
            "ORDER BY score, CAST(f.orpha_code AS INTEGER) LIMIT ? OFFSET ?"
        )
        count_sql = (
            "SELECT COUNT(*) AS n "  # noqa: S608
            "FROM disorder_fts f "
            "JOIN disorder d ON d.orpha_code = f.orpha_code "
            f"WHERE disorder_fts MATCH ?{obs_clause}"
        )
        try:
            rows = self._conn.execute(sql, (match, limit, offset)).fetchall()
            total = int(self._conn.execute(count_sql, (match,)).fetchone()["n"])
        except sqlite3.Error:
            return self._search_like(
                query, limit=limit, offset=offset, include_obsolete=include_obsolete
            )
        results = [
            {
                "orpha_code": r["orpha_code"],
                "name": r["name"],
                "score": round(-r["score"], 4) if r["score"] else 0.0,
            }
            for r in rows
        ]
        return {"results": results, "total": total, "limit": limit, "offset": offset}

    def _search_like(
        self, query: str, *, limit: int, offset: int, include_obsolete: bool
    ) -> dict[str, Any]:
        """``LIKE`` fallback for pathological FTS input."""
        pattern = "%" + query.upper().replace("%", "").replace("_", "") + "%"
        obs_clause = "" if include_obsolete else " AND is_obsolete = 0"
        rows = self._conn.execute(
            "SELECT orpha_code, name FROM disorder "  # noqa: S608
            f"WHERE name_upper LIKE ?{obs_clause} "
            "ORDER BY name LIMIT ? OFFSET ?",
            (pattern, limit, offset),
        ).fetchall()
        total = int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM disorder "  # noqa: S608
                f"WHERE name_upper LIKE ?{obs_clause}",
                (pattern,),
            ).fetchone()["n"]
        )
        results = [{"orpha_code": r["orpha_code"], "name": r["name"], "score": 0.0} for r in rows]
        return {"results": results, "total": total, "limit": limit, "offset": offset}

    # -- cross-references ------------------------------------------------------

    def get_xrefs(self, code: str) -> list[dict[str, Any]]:
        """Return xrefs ordered by mapping precision (E < NTBT < BTNT < ND < W)."""
        rows = self._conn.execute(
            "SELECT source, object_id, mapping_relation, icd_relation, "  # noqa: S608
            "validation_status, ref_uri "
            "FROM xref WHERE orpha_code = ? "
            f"ORDER BY {_MAPPING_CASE}, source, object_id",
            (code,),
        ).fetchall()
        return [
            {
                "source": r["source"],
                "object_id": r["object_id"],
                "mapping_relation": r["mapping_relation"],
                "icd_relation": r["icd_relation"],
                "validation_status": r["validation_status"],
                "ref_uri": r["ref_uri"],
            }
            for r in rows
        ]

    def resolve_xref(self, source: str, object_id: str) -> list[dict[str, Any]]:
        """Resolve ``source`` + ``object_id`` (case-insensitive) to ``{orpha_code, name}``."""
        rows = self._conn.execute(
            "SELECT x.orpha_code, d.name "
            "FROM xref x JOIN disorder d ON d.orpha_code = x.orpha_code "
            "WHERE x.source = ? AND x.object_id_upper = ?",
            (source, object_id.upper()),
        ).fetchall()
        return [{"orpha_code": r["orpha_code"], "name": r["name"]} for r in rows]

    # -- genes -----------------------------------------------------------------

    def get_genes(self, code: str) -> list[dict[str, Any]]:
        """Return gene associations joined with gene metadata for a disorder."""
        rows = self._conn.execute(
            "SELECT dg.gene_symbol, dg.association_type, dg.association_status, "
            "dg.source_pmids, "
            "g.gene_name, g.gene_type, g.locus, g.hgnc_id, g.omim_id, "
            "g.ensembl_id, g.swissprot_id, g.genatlas_id, g.reactome_id, g.clinvar_id "
            "FROM disorder_gene dg "
            "JOIN gene g ON g.gene_symbol = dg.gene_symbol "
            "WHERE dg.orpha_code = ? "
            "ORDER BY dg.gene_symbol",
            (code,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_disorders_by_gene(
        self, gene_symbol: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Find disorders for a gene symbol (case-insensitive); paginated envelope."""
        sym_upper = gene_symbol.upper()
        # ``disorder_gene`` has no unique constraint: a disorder linked to the
        # same gene via >1 association row would fan out the join.  DISTINCT +
        # COUNT(DISTINCT ...) keep results and ``total`` deduped and aligned.
        # (Not reproducible at fixture scale — applied defensively.)
        rows = self._conn.execute(
            "SELECT DISTINCT dg.orpha_code, d.name "
            "FROM disorder_gene dg "
            "JOIN disorder d ON d.orpha_code = dg.orpha_code "
            "WHERE UPPER(dg.gene_symbol) = ? "
            "ORDER BY d.name LIMIT ? OFFSET ?",
            (sym_upper, limit, offset),
        ).fetchall()
        total = int(
            self._conn.execute(
                "SELECT COUNT(DISTINCT orpha_code) AS n "
                "FROM disorder_gene WHERE UPPER(gene_symbol) = ?",
                (sym_upper,),
            ).fetchone()["n"]
        )
        results = [{"orpha_code": r["orpha_code"], "name": r["name"]} for r in rows]
        return {"results": results, "total": total, "limit": limit, "offset": offset}

    # -- phenotypes ------------------------------------------------------------

    def get_phenotypes(self, code: str, frequency: str | None = None) -> list[dict[str, Any]]:
        """Return HPO phenotype rows; optional ``frequency`` label filter."""
        if frequency is not None:
            rows = self._conn.execute(
                "SELECT hpo_id, hpo_term, frequency, diagnostic_criteria "
                "FROM phenotype WHERE orpha_code = ? AND frequency = ? ORDER BY hpo_id",
                (code, frequency),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT hpo_id, hpo_term, frequency, diagnostic_criteria "
                "FROM phenotype WHERE orpha_code = ? ORDER BY hpo_id",
                (code,),
            ).fetchall()
        return [
            {
                "hpo_id": r["hpo_id"],
                "hpo_term": r["hpo_term"],
                "frequency": r["frequency"],
                "diagnostic_criteria": r["diagnostic_criteria"],
            }
            for r in rows
        ]

    def find_disorders_by_phenotype(
        self, hpo_id: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Find disorders annotated with ``hpo_id``; paginated envelope."""
        # ``phenotype`` has no unique constraint: a disorder annotated with the
        # same HPO id via >1 row would fan out the join.  DISTINCT +
        # COUNT(DISTINCT ...) keep results and ``total`` deduped and aligned.
        # (Not reproducible at fixture scale — applied defensively.)
        rows = self._conn.execute(
            "SELECT DISTINCT p.orpha_code, d.name "
            "FROM phenotype p "
            "JOIN disorder d ON d.orpha_code = p.orpha_code "
            "WHERE p.hpo_id = ? "
            "ORDER BY d.name LIMIT ? OFFSET ?",
            (hpo_id, limit, offset),
        ).fetchall()
        total = int(
            self._conn.execute(
                "SELECT COUNT(DISTINCT orpha_code) AS n FROM phenotype WHERE hpo_id = ?",
                (hpo_id,),
            ).fetchone()["n"]
        )
        results = [{"orpha_code": r["orpha_code"], "name": r["name"]} for r in rows]
        return {"results": results, "total": total, "limit": limit, "offset": offset}

    # -- epidemiology ----------------------------------------------------------

    def get_prevalence(self, code: str) -> list[dict[str, Any]]:
        """Return prevalence records for a disorder."""
        rows = self._conn.execute(
            "SELECT prevalence_type, prevalence_class, val_moy, geographic, "
            "qualification, validation_status, source "
            "FROM prevalence WHERE orpha_code = ? ORDER BY prevalence_type",
            (code,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- natural history -------------------------------------------------------

    def get_natural_history(self, code: str) -> dict[str, Any]:
        """Return ``{age_of_onset: [{onset}], inheritance: [{inheritance}]}``."""
        onset_rows = self._conn.execute(
            "SELECT onset FROM age_of_onset WHERE orpha_code = ? ORDER BY onset", (code,)
        ).fetchall()
        inh_rows = self._conn.execute(
            "SELECT inheritance FROM inheritance WHERE orpha_code = ? ORDER BY inheritance",
            (code,),
        ).fetchall()
        return {
            "age_of_onset": [{"onset": r["onset"]} for r in onset_rows],
            "inheritance": [{"inheritance": r["inheritance"]} for r in inh_rows],
        }

    # -- disability ------------------------------------------------------------

    def get_disability(self, code: str) -> list[dict[str, Any]]:
        """Return functional consequence records for a disorder."""
        rows = self._conn.execute(
            "SELECT annotation, frequency, temporality, severity "
            "FROM disability WHERE orpha_code = ? ORDER BY annotation",
            (code,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- classification --------------------------------------------------------

    def get_classification(self, code: str) -> dict[str, Any]:
        """Return ``{parents, children}`` from ``classification_edge`` with names."""
        # ``classification_edge`` has no unique constraint: the same parent→child
        # edge asserted in multiple specialty trees yields duplicate rows, so we
        # DISTINCT over the projected (code, name) pair.
        parent_rows = self._conn.execute(
            "SELECT DISTINCT e.parent_code AS orpha_code, d.name "
            "FROM classification_edge e "
            "LEFT JOIN disorder d ON d.orpha_code = e.parent_code "
            "WHERE e.orpha_code = ? ORDER BY d.name",
            (code,),
        ).fetchall()
        child_rows = self._conn.execute(
            "SELECT DISTINCT e.orpha_code, d.name "
            "FROM classification_edge e "
            "LEFT JOIN disorder d ON d.orpha_code = e.orpha_code "
            "WHERE e.parent_code = ? ORDER BY d.name",
            (code,),
        ).fetchall()
        return {
            "parents": [{"orpha_code": r["orpha_code"], "name": r["name"]} for r in parent_rows],
            "children": [{"orpha_code": r["orpha_code"], "name": r["name"]} for r in child_rows],
        }

    def get_ancestors(self, code: str, limit: int = 200, offset: int = 0) -> dict[str, Any]:
        """Transitive ancestors from the closure table (self excluded); paginated."""
        rows = self._conn.execute(
            "SELECT c.ancestor_code AS orpha_code, d.name "
            "FROM classification_closure c "
            "LEFT JOIN disorder d ON d.orpha_code = c.ancestor_code "
            "WHERE c.orpha_code = ? AND c.ancestor_code != ? "
            "ORDER BY d.name LIMIT ? OFFSET ?",
            (code, code, limit, offset),
        ).fetchall()
        total = int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM classification_closure "
                "WHERE orpha_code = ? AND ancestor_code != ?",
                (code, code),
            ).fetchone()["n"]
        )
        results = [{"orpha_code": r["orpha_code"], "name": r["name"]} for r in rows]
        return {"results": results, "total": total, "limit": limit, "offset": offset}

    def get_descendants(self, code: str, limit: int = 200, offset: int = 0) -> dict[str, Any]:
        """Transitive descendants from the closure table (self excluded); paginated."""
        rows = self._conn.execute(
            "SELECT c.orpha_code, d.name "
            "FROM classification_closure c "
            "LEFT JOIN disorder d ON d.orpha_code = c.orpha_code "
            "WHERE c.ancestor_code = ? AND c.orpha_code != ? "
            "ORDER BY d.name LIMIT ? OFFSET ?",
            (code, code, limit, offset),
        ).fetchall()
        total = int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM classification_closure "
                "WHERE ancestor_code = ? AND orpha_code != ?",
                (code, code),
            ).fetchone()["n"]
        )
        results = [{"orpha_code": r["orpha_code"], "name": r["name"]} for r in rows]
        return {"results": results, "total": total, "limit": limit, "offset": offset}
