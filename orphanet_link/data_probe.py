"""Deterministic, read-only semantic probe over the materialized Orphanet index.

Run inside the application container by the fleet controller:

    python -m orphanet_link.data_probe

It prints exactly one JSON object with exactly the keys ``data_schema_version``,
``record_count`` and ``query_result_sha256``. The database is opened immutably
(``mode=ro&immutable=1``), so observing the data cannot change it: no journal, no WAL
index, no write of any kind, and no network. The database path comes from the same
``ORPHANET_LINK_DATA__DATA_DIR`` / ``ORPHANET_LINK_DATA__DB_FILENAME`` settings the
serving process uses, so the probe reads the bytes that are actually being served.

``disorder`` is the primary entity of this store and ``orpha_code`` is its primary key,
so ``record_count`` counts disorders and ``query_result_sha256`` is the SHA-256 of the
UTF-8 text of the canonical first key.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

#: Schema version stamped into the single-row ``meta`` table by the builder.
SCHEMA_SQL = "SELECT schema_version FROM meta WHERE id = 1"
#: Count of the primary entity.
RECORD_COUNT_SQL = "SELECT COUNT(*) FROM disorder"
#: The canonical first primary key.
FIRST_KEY_SQL = "SELECT orpha_code FROM disorder ORDER BY orpha_code LIMIT 1"


class DataProbeError(RuntimeError):
    """The materialized store cannot answer the probe."""


def probe(db_path: Path) -> dict[str, object]:
    """Return the exact probe payload for one materialized SQLite database."""
    if not db_path.is_file():
        raise DataProbeError("the materialized Orphanet index is not present")
    try:
        with closing(
            sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
        ) as connection:
            schema = connection.execute(SCHEMA_SQL).fetchone()
            count = connection.execute(RECORD_COUNT_SQL).fetchone()
            first = connection.execute(FIRST_KEY_SQL).fetchone()
    except sqlite3.Error as exc:
        raise DataProbeError("the materialized Orphanet index is unreadable") from exc
    if schema is None or count is None or first is None or first[0] is None:
        raise DataProbeError("the materialized Orphanet index is empty")
    return {
        "data_schema_version": str(schema[0]),
        "record_count": int(count[0]),
        "query_result_sha256": hashlib.sha256(str(first[0]).encode("utf-8")).hexdigest(),
    }


def main() -> int:
    """Print the probe payload as one line of JSON; return a POSIX exit status."""
    from orphanet_link.config import settings

    try:
        payload = probe(settings.data.db_path)
    except (DataProbeError, OSError) as exc:
        # Path-free, body-free message: this runs in production and its stderr is
        # captured by the controller alongside reviewable evidence.
        sys.stderr.write(f"data probe failed: {type(exc).__name__}: {exc}\n")
        return 1
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
