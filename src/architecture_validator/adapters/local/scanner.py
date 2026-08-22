"""Local IaC scanner adapter (IaCScannerPort) — a seeded, SQLite-backed estate.

The ``local`` profile's stand-in for the **live** Cloud Asset Inventory + Security
Command Center scanner: a ``sqlite3`` store of resource snapshots, keyed by scan scope
(``projects/...`` | ``folders/...`` | ``organizations/...``), so a ``scan --project``
returns a real, gradable resource estate **offline** (no cloud, no Google Cloud SDK).
There is no emulator for Cloud Asset Inventory, so this path is SDK-free and
unconditional.

It is **seedable**: ``seed(resources, scope=...)`` ingests a corpus (tests pass
``:memory:`` and seed their own fixtures), and the adapter self-seeds the built-in
synthetic estate (:data:`architecture_validator.adapters.local._seed.SEED_RESOURCES`) on
construction so the end-to-end CLI smoke run grades a real FAIL verdict out of the box.
A scope with no seeded rows returns the default estate, so any ``--project <id>`` the
operator passes yields a real scan rather than an empty one.

The file-based CI-gate scan (a Terraform plan / ``.tf`` path) is pure stdlib
(``architecture_validator.pipelines.terraform``) and already runs under every profile; this
adapter is only the *live* ``--project`` scan path.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain.residency.models import ResourceConfig
from ._seed import SEED_RESOURCES

_DEFAULT_DB_DIR = Path.home() / ".architecture_validator"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "local.db"

#: Sentinel scope under which the built-in synthetic estate is seeded; a scan for any
#: scope with no explicit rows falls back to this default estate.
_DEFAULT_SCOPE = "*"


def _resource_to_row(resource: ResourceConfig) -> tuple[str, str, str, str, str]:
    return (
        resource.address,
        resource.type,
        resource.region or "",
        json.dumps(resource.attributes),
        resource.source_ref,
    )


def _row_to_resource(row: sqlite3.Row) -> ResourceConfig:
    return ResourceConfig(
        address=row["address"],
        type=row["type"],
        region=row["region"] or None,
        attributes=json.loads(row["attributes"]),
        source_ref=row["source_ref"],
    )


class LocalSeededScannerAdapter:
    """Seeded live-scan stand-in: returns a real resource estate for a scope, offline."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "db_path", "") or str(_DEFAULT_DB_PATH)
        self._path = path
        if path not in (":memory:", "") and not path.startswith("file:"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` + a re-entrant lock: under ``local serve`` the
        # container is process-wide (deps.get_container is lru_cached) but the sync
        # endpoints run in Starlette's anyio worker threadpool, so scan() is called from
        # worker threads other than the one that opened the connection. The lock serialises
        # access (single-writer) so cross-thread use does not raise. ``RLock`` because the
        # public ``seed`` re-enters the guarded internals during self-seeding.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    address TEXT NOT NULL,
                    type TEXT NOT NULL,
                    region TEXT NOT NULL,
                    attributes TEXT NOT NULL,
                    source_ref TEXT NOT NULL
                )
                """
            )
            self._conn.commit()
        # Self-seed the built-in synthetic estate so the live scan grades out of the box.
        if not self._has_scope(_DEFAULT_SCOPE):
            self.seed(SEED_RESOURCES, scope=_DEFAULT_SCOPE)

    # ------------------------------------------------------------------ #
    # IaCScannerPort
    # ------------------------------------------------------------------ #
    def scan(self, target: str) -> list[ResourceConfig]:
        """Return the seeded resource estate for ``target``, or the default estate."""
        with self._lock:
            rows = self._fetch_scope(target)
            if not rows:
                rows = self._fetch_scope(_DEFAULT_SCOPE)
        return [_row_to_resource(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Seeding / ingest
    # ------------------------------------------------------------------ #
    def seed(
        self,
        resources: tuple[ResourceConfig, ...] | list[ResourceConfig],
        *,
        scope: str,
    ) -> None:
        """Ingest ``resources`` under ``scope`` (idempotent: replaces the scope's rows)."""
        with self._lock:
            self._conn.execute("DELETE FROM resources WHERE scope = ?", (scope,))
            self._conn.executemany(
                "INSERT INTO resources (scope, address, type, region, attributes, source_ref) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(scope, *_resource_to_row(r)) for r in resources],
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _fetch_scope(self, scope: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT address, type, region, attributes, source_ref FROM resources "
                "WHERE scope = ? ORDER BY id ASC",
                (scope,),
            ).fetchall()

    def _has_scope(self, scope: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM resources WHERE scope = ? LIMIT 1", (scope,)
            ).fetchone()
        return row is not None
