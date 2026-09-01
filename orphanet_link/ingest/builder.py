"""Assemble the local SQLite index from parsed Orphadata products.

The build is atomic: it writes a temp database under a cross-process lock, runs
the frozen schema, batch-loads every product, precomputes the classification
closure, stamps provenance into ``meta``, then ``os.replace``-s the temp file
over the target so readers never observe a partial database.

The build is also **byte-reproducible**: the same upstream snapshot must produce
the same SQLite bytes on every machine and every run. That requires two things
which are easy to lose by accident:

* every row is inserted in a *sorted*, hash-seed-independent order -- iterating a
  ``set`` orders rows by ``PYTHONHASHSEED``, which silently changes rowids and so
  the file bytes; and
* nothing about the *run* is written into the file. ``build_utc`` is derived from
  the source revision (or ``SOURCE_DATE_EPOCH``), never from the wall clock, and
  the build duration is not stored at all.

Reproducibility is not cosmetic here: the release pipeline compares a freshly
built bundle against the published one to decide whether a release is a no-op or
a collision, and a wall-clock stamp makes every rebuild look like a collision.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.constants import SCHEMA_VERSION
from orphanet_link.exceptions import BuildError
from orphanet_link.ingest.lock import build_lock
from orphanet_link.ingest.parsers import (
    _common,
    funct_consequences,
    product1,
    product3,
    product4,
    product6,
    product7,
    product9_ages,
    product9_prev,
)
from orphanet_link.ingest.schema import load_schema_sql

_BATCH = 5000
#: SOURCE_DATE_EPOCH is "an ASCII representation of an integer with no fractional
#: component" -- no sign, no whitespace, no float.
_EPOCH_VALUE = re.compile(r"[0-9]+")


def _executemany(conn: sqlite3.Connection, sql: str, rows: list[tuple[Any, ...]]) -> None:
    """Batch-insert ``rows`` with ``executemany`` in chunks of ``_BATCH``."""
    for start in range(0, len(rows), _BATCH):
        conn.executemany(sql, rows[start : start + _BATCH])


def _compute_closure(edges: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """Return ``(node, ancestor)`` pairs (incl. self) from child→parent edges.

    Memoized DFS over the classification DAG with a cycle guard; the self-pair is
    always included so descendant/ancestor queries are flat indexed lookups.
    """
    parents: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for child, parent, _sid in edges:
        if not child or not parent:
            continue
        parents.setdefault(child, set()).add(parent)
        nodes.add(child)
        nodes.add(parent)

    memo: dict[str, set[str]] = {}

    def ancestors(node: str, stack: frozenset[str]) -> set[str]:
        if node in memo:
            return memo[node]
        if node in stack:  # cycle guard (Orphanet classification is a DAG)
            return {node}
        acc = {node}
        next_stack = stack | {node}
        for parent in parents.get(node, ()):
            acc |= ancestors(parent, next_stack)
        memo[node] = acc
        return acc

    # Both loops iterate SORTED, not set order: ``nodes`` and the memoized
    # ancestor sets are ``set``s, whose iteration order follows PYTHONHASHSEED.
    # Unsorted, the same ~130k closure rows insert in a different order on every
    # run, which changes their rowids and therefore the database bytes. The
    # returned content is identical either way; only the order is pinned.
    pairs: list[tuple[str, str]] = []
    for node in sorted(nodes):
        for anc in sorted(ancestors(node, frozenset())):
            pairs.append((node, anc))
    return pairs


def _source_date_epoch() -> datetime | None:
    """Parse ``SOURCE_DATE_EPOCH`` as specified by reproducible-builds.org.

    https://reproducible-builds.org/specs/source-date-epoch/ defines the value as
    "an ASCII representation of an integer with no fractional component" counting
    seconds since the UNIX epoch, and requires that "if the value is malformed,
    the build process SHOULD exit with a non-zero error code" -- hence
    ``BuildError`` rather than a silent fallback, which would hand back exactly
    the irreproducibility the variable exists to remove. An unset or empty value
    means "not requested", the conventional reading of an absent variable.
    """
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if not raw:
        return None
    if not _EPOCH_VALUE.fullmatch(raw):
        raise BuildError(
            "SOURCE_DATE_EPOCH must be an ASCII integer number of seconds since "
            f"the UNIX epoch, got {raw!r}."
        )
    try:
        return datetime.fromtimestamp(int(raw), UTC)
    except (OSError, OverflowError, ValueError) as error:
        raise BuildError(f"SOURCE_DATE_EPOCH is out of range: {raw!r}.") from error


def _build_stamp(orphanet_date: str | None) -> str | None:
    """Return a ``build_utc`` derived from the source, not from the run clock.

    ``datetime.now()`` would make two builds of one upstream snapshot differ, so
    the stamp is the ``<JDBOR date=>`` revision the database was built from --
    already a property of the input, and therefore reproducible on its own.

    ``SOURCE_DATE_EPOCH`` is honoured as the specification requires, which is
    *clamping* rather than substitution: a build "MUST use a timestamp no later
    than the value of this variable", so a source revision that is already older
    is kept and only a later one is pulled back. Substituting unconditionally
    would discard real source provenance for no reproducibility gain. When there
    is no source revision to clamp, the field stands in for "the current date and
    time", which the specification says the variable MUST replace.

    Returns ``None`` when neither is available rather than inventing a time.
    """
    epoch = _source_date_epoch()
    revision: datetime | None = None
    if orphanet_date:
        try:
            revision = datetime.strptime(orphanet_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            revision = None
    if revision is None:
        return epoch.isoformat() if epoch is not None else None
    return min(revision, epoch).isoformat() if epoch is not None else revision.isoformat()


def _load_product1(conn: sqlite3.Connection, path: Path) -> tuple[int, int]:
    result = product1.parse(path)
    disorders, synonyms, lookups, fts = [], [], [], []
    for d in result.disorders:
        code = d["orpha_code"]
        name = d["name"] or ""
        disorders.append(
            (
                code,
                name,
                name.upper(),
                d["disorder_type"],
                d["disorder_group"],
                d["disorder_flag"],
                d["expert_link"],
                d["definition"],
                0,
            )
        )
        if name:
            lookups.append((name.upper(), code, "name"))
        syns = d["synonyms"]
        for syn in syns:
            synonyms.append((code, syn))
            lookups.append((syn.upper(), code, "synonym"))
        fts.append((code, name, " ".join(syns)))

    xrefs = [
        (
            x["orpha_code"],
            x["source"],
            x["object_id"],
            (x["object_id"] or "").upper(),
            x["mapping_relation"],
            x["icd_relation"],
            x["validation_status"],
            x["ref_uri"],
        )
        for x in result.xrefs
        if x["source"] and x["object_id"]
    ]

    _executemany(
        conn,
        "INSERT OR IGNORE INTO disorder VALUES (?,?,?,?,?,?,?,?,?)",
        disorders,
    )
    _executemany(conn, "INSERT INTO disorder_synonym VALUES (?,?)", synonyms)
    _executemany(conn, "INSERT INTO disorder_lookup VALUES (?,?,?)", lookups)
    _executemany(conn, "INSERT INTO disorder_fts VALUES (?,?,?)", fts)
    _executemany(conn, "INSERT INTO xref VALUES (?,?,?,?,?,?,?,?)", xrefs)
    return len(disorders), len(xrefs)


def _load_product6(conn: sqlite3.Connection, path: Path) -> int:
    result = product6.parse(path)
    genes = [
        (
            g["gene_symbol"],
            g["gene_name"],
            g["gene_type"],
            g["locus"],
            g["hgnc_id"],
            g["omim_id"],
            g["ensembl_id"],
            g["swissprot_id"],
            g["genatlas_id"],
            g["reactome_id"],
            g["clinvar_id"],
        )
        for g in result.genes
        if g["gene_symbol"]
    ]
    assoc = [
        (
            a["orpha_code"],
            a["gene_symbol"],
            a["association_type"],
            a["association_status"],
            a["source_pmids"],
        )
        for a in result.associations
        if a["gene_symbol"]
    ]
    _executemany(conn, "INSERT OR IGNORE INTO gene VALUES (?,?,?,?,?,?,?,?,?,?,?)", genes)
    _executemany(conn, "INSERT INTO disorder_gene VALUES (?,?,?,?,?)", assoc)
    return len(genes)


def build_database(
    data_config: OrphanetDataConfig,
    paths: Mapping[str, Path],
    classification_paths: Mapping[str, Path] | None = None,
) -> Path:
    """Build the SQLite index from the given product files; return the DB path.

    Args:
        data_config: Data-store configuration (``data_dir``, ``db_path``, lock timeout).
        paths: Map of single-file product keys (``product1``, ``product4``,
            ``product6``, ``product7``, ``product9_prev``, ``product9_ages``,
            ``funct``) to file paths. ``product1`` is required.
        classification_paths: Map of specialty id -> ``en_product3_<id>.xml`` path.

    Returns:
        The path to the freshly built database (``data_config.db_path``).

    Raises:
        BuildError: If ``product1`` is missing or the build fails.
    """
    if "product1" not in paths:
        raise BuildError("product1 is required to build the Orphanet database.")

    data_dir = data_config.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_config.db_path

    with build_lock(data_dir, timeout=data_config.build_lock_timeout):
        fd, tmp_name = tempfile.mkstemp(dir=data_dir, suffix=".sqlite.tmp")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            conn = sqlite3.connect(tmp_path)
            try:
                conn.executescript(load_schema_sql())

                disorder_count, xref_count = _load_product1(conn, Path(paths["product1"]))
                gene_count = (
                    _load_product6(conn, Path(paths["product6"])) if "product6" in paths else 0
                )

                phenotype_count = 0
                if "product4" in paths:
                    rows = [
                        (
                            r["orpha_code"],
                            r["hpo_id"],
                            r["hpo_term"],
                            r["frequency"],
                            r["diagnostic_criteria"],
                        )
                        for r in product4.parse(Path(paths["product4"]))
                        if r["hpo_id"]
                    ]
                    _executemany(conn, "INSERT INTO phenotype VALUES (?,?,?,?,?)", rows)
                    phenotype_count = len(rows)

                if "product7" in paths:
                    lin = [
                        (r["orpha_code"], r["parent_code"])
                        for r in product7.parse(Path(paths["product7"]))
                    ]
                    _executemany(conn, "INSERT INTO linearisation VALUES (?,?)", lin)

                prevalence_count = 0
                if "product9_prev" in paths:
                    prev = [
                        (
                            r["orpha_code"],
                            r["prevalence_type"],
                            r["prevalence_class"],
                            r["val_moy"],
                            r["geographic"],
                            r["qualification"],
                            r["validation_status"],
                            r["source"],
                        )
                        for r in product9_prev.parse(Path(paths["product9_prev"]))
                    ]
                    _executemany(conn, "INSERT INTO prevalence VALUES (?,?,?,?,?,?,?,?)", prev)
                    prevalence_count = len(prev)

                if "product9_ages" in paths:
                    ages = product9_ages.parse(Path(paths["product9_ages"]))
                    _executemany(conn, "INSERT INTO age_of_onset VALUES (?,?)", list(ages.onsets))
                    _executemany(
                        conn, "INSERT INTO inheritance VALUES (?,?)", list(ages.inheritance)
                    )

                if "funct" in paths:
                    disab = [
                        (
                            r["orpha_code"],
                            r["annotation"],
                            r["frequency"],
                            r["temporality"],
                            r["severity"],
                        )
                        for r in funct_consequences.parse(Path(paths["funct"]))
                    ]
                    _executemany(conn, "INSERT INTO disability VALUES (?,?,?,?,?)", disab)

                edges: list[tuple[str, str, str]] = []
                specialties: list[tuple[str, str]] = []
                for sid, cpath in (classification_paths or {}).items():
                    res = product3.parse(Path(cpath), sid)
                    edges.extend(
                        (e["orpha_code"], e["parent_code"], e["specialty_id"]) for e in res.edges
                    )
                    if res.specialty:
                        specialties.append((res.specialty["specialty_id"], res.specialty["name"]))
                _executemany(conn, "INSERT INTO classification_edge VALUES (?,?,?)", edges)
                _executemany(conn, "INSERT OR IGNORE INTO specialty VALUES (?,?)", specialties)

                closure = _compute_closure(edges)
                _executemany(conn, "INSERT INTO classification_closure VALUES (?,?)", closure)

                conn.execute("INSERT INTO disorder_fts(disorder_fts) VALUES('optimize')")

                date, version = _common.jdbor_stamp(Path(paths["product1"]))
                conn.execute(
                    "INSERT INTO meta VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        SCHEMA_VERSION,
                        version,
                        date,
                        json.dumps({"base_url": data_config.base_url}),
                        disorder_count,
                        xref_count,
                        gene_count,
                        phenotype_count,
                        prevalence_count,
                        len(closure),
                        # build_utc: source-derived, so a rebuild reproduces it.
                        _build_stamp(date),
                        # build_duration_s: how long this run took is pure run
                        # provenance -- storing it would put the wall clock back
                        # into the released bytes.
                        None,
                    ),
                )
                conn.commit()
                # Collapse the WAL back into the main file and drop the journal so
                # the atomic rename moves a single self-contained database file.
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA journal_mode=DELETE")
            finally:
                conn.close()
            os.replace(tmp_path, db_path)
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            if isinstance(exc, BuildError):
                raise
            raise BuildError(f"Failed to build the Orphanet database: {exc}") from exc

    return db_path
