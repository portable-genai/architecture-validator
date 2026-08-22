"""Local knowledge-base adapter (KnowledgeBasePort) — SQLite FTS5 over the reg corpus.

The ``local`` profile's stand-in for **File Search** (the A2 governed reg-KB): a
``sqlite3`` database with an **FTS5** virtual table over the regulatory passages, queried
with BM25 (``ORDER BY rank``). It is SDK-free, deterministic and **seedable**, so the
same code grounds the offline CLI run and the unit tests. There is no Google emulator for
File Search / Agent Search, so this path is unconditional (no emulator branch).

The adapter returns the same :class:`Citation` objects with page-level provenance as the
managed adapter, preserving interface parity. It self-seeds from the built-in synthetic
corpus on first use so an out-of-the-box local validation grounds its findings without
any ingestion step; callers may also ``seed(citations)`` a corpus of their own.

Default DB path is under a per-package local dir (``~/.architecture_validator/local.db``); tests
pass ``:memory:`` for an ephemeral, deterministic index.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain.models import Citation, Jurisdiction, Regulator
from ._seed import SEED_CITATIONS

# Default on-disk location for the local index (overridable via settings.local.db_path).
_DEFAULT_DB_DIR = Path.home() / ".architecture_validator"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "local.db"

# FTS5 query syntax is strict; keep only word characters so a free-text query never trips
# an "fts5: syntax error" (e.g. on punctuation), and OR the terms for recall.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class LocalFtsKnowledgeBaseAdapter:
    """Retrieve governed-KB citations from a local SQLite FTS5 index (BM25 ranked)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        db_path = getattr(getattr(settings, "local", None), "db_path", "") or str(_DEFAULT_DB_PATH)
        self._db_path = db_path
        # ``check_same_thread=False`` + a lock: under ``local serve`` the container is
        # process-wide (deps.get_container is lru_cached) but the sync API endpoints run in
        # Starlette's anyio worker threadpool, so retrieve()/seed() are called from worker
        # threads other than the one that opened the connection. The lock serialises access
        # (single-writer) so cross-thread use of the connection does not raise.
        self._lock = threading.Lock()
        self._conn = self._connect(db_path)
        self._init_schema()
        # Self-seed the built-in corpus so an out-of-the-box local run is grounded.
        if self._is_empty():
            self.seed(SEED_CITATIONS)
        # Surface the calls a unit test may assert on (mirrors the prior FakeKnowledgeBase).
        self.calls: list[str] = []

    # ------------------------------------------------------------------ #
    # Connection / schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        if db_path not in (":memory:", "") and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        # One FTS5 table holds the searchable text; citation metadata rides alongside as
        # UNINDEXED columns so a single query returns everything needed to cite a hit.
        with self._lock:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
                    text,
                    source_id UNINDEXED,
                    regulator UNINDEXED,
                    jurisdiction UNINDEXED,
                    title UNINDEXED,
                    url UNINDEXED,
                    version UNINDEXED,
                    page UNINDEXED,
                    score UNINDEXED
                )
                """
            )
            self._conn.commit()

    def _is_empty(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT count(*) AS n FROM passages").fetchone()
        return int(row["n"]) == 0

    # ------------------------------------------------------------------ #
    # Seeding
    # ------------------------------------------------------------------ #
    def seed(self, citations: tuple[Citation, ...] | list[Citation]) -> int:
        """Replace the index contents with ``citations`` (deterministic test/CLI seed)."""
        with self._lock:
            self._conn.execute("DELETE FROM passages")
            return self._insert_locked(list(citations))

    def add(self, citations: list[Citation]) -> int:
        """Append ``citations`` to the index without clearing existing rows."""
        with self._lock:
            return self._insert_locked(citations)

    def _insert_locked(self, citations: list[Citation]) -> int:
        # Caller must hold ``self._lock`` (single-writer serialisation across threads).
        rows = []
        for c in citations:
            rows.append(
                (
                    c.snippet or c.title,
                    c.source_id,
                    c.regulator.value,
                    c.jurisdiction.value,
                    c.title,
                    c.url,
                    c.version,
                    "" if c.page is None else str(c.page),
                    f"{(c.score if c.score is not None else 0.0):.6f}",
                )
            )
        self._conn.executemany(
            "INSERT INTO passages "
            "(text, source_id, regulator, jurisdiction, title, url, version, page, score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    # KnowledgeBasePort
    # ------------------------------------------------------------------ #
    def retrieve(self, query: str, top_k: int = 8) -> list[Citation]:
        """Return governed-KB citations relevant to ``query`` (reg context for findings)."""
        self.calls.append(query)
        match = self._build_match(query)

        with self._lock:
            if not match:
                # No usable query terms: fall back to a score-ordered scan so the pipeline
                # still gets something deterministic rather than an FTS5 syntax error.
                cursor = self._conn.execute(
                    "SELECT * FROM passages ORDER BY score DESC LIMIT ?", (max(top_k, 1),)
                )
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM passages WHERE passages MATCH ? ORDER BY rank LIMIT ?",
                    (match, max(top_k, 1)),
                )
            rows = cursor.fetchall()
        return [self._row_to_citation(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_match(text: str) -> str:
        """Build a safe FTS5 MATCH expression: OR of the alphanumeric query tokens."""
        tokens = _TOKEN_RE.findall(text or "")
        if not tokens:
            return ""
        # Quote each token so reserved words (AND/OR/NOT/NEAR) are treated as literals.
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _row_to_citation(row: sqlite3.Row) -> Citation:
        page_raw = row["page"]
        page = int(page_raw) if page_raw not in (None, "") else None
        try:
            score: float | None = float(row["score"])
        except (TypeError, ValueError):
            score = None
        return Citation(
            source_id=row["source_id"],
            regulator=LocalFtsKnowledgeBaseAdapter._parse_regulator(row["regulator"]),
            jurisdiction=LocalFtsKnowledgeBaseAdapter._parse_jurisdiction(row["jurisdiction"]),
            title=row["title"],
            url=row["url"],
            version=row["version"] or "unknown",
            page=page,
            snippet=(row["text"] or "")[:280],
            score=score,
        )

    @staticmethod
    def _parse_regulator(value: str | None) -> Regulator:
        try:
            return Regulator(str(value).upper())
        except (ValueError, AttributeError):
            return Regulator.CROSS

    @staticmethod
    def _parse_jurisdiction(value: str | None) -> Jurisdiction:
        try:
            return Jurisdiction(str(value).upper())
        except (ValueError, AttributeError):
            return Jurisdiction.GLOBAL
