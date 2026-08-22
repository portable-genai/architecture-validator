"""Concurrency regression tests for the local SQLite-backed adapters.

Under ``local serve`` the FastAPI container is process-wide (``deps.get_container`` is
``lru_cache``d, one connection per process) while the sync endpoints run in Starlette's
anyio worker threadpool. A request handled on a worker thread therefore calls
``record()`` / ``retrieve()`` on a ``sqlite3`` connection that was opened on a *different*
thread, which raises "SQLite objects created in a thread can only be used in that same
thread" and silently drops the WORM audit event (or 500s the request).

These tests drive each SQLite-backed local adapter (``LocalAppendOnlyAuditAdapter`` and
``LocalFtsKnowledgeBaseAdapter``) from many threads via a ``ThreadPoolExecutor`` and assert
no exception is raised and the final row count is correct. They FAIL before the fix
(``check_same_thread=False`` plus a serialising ``threading.Lock``) and PASS after.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from architecture_validator.adapters.local.audit import LocalAppendOnlyAuditAdapter
from architecture_validator.adapters.local.knowledge import LocalFtsKnowledgeBaseAdapter
from architecture_validator.adapters.local.scanner import LocalSeededScannerAdapter
from architecture_validator.config import LocalSettings, Settings
from architecture_validator.domain.models import (
    AuditEvent,
    Citation,
    Decision,
    Jurisdiction,
    Regulator,
)
from architecture_validator.domain.residency.models import ResourceConfig


def _settings() -> Settings:
    return Settings(local=LocalSettings(db_path=":memory:", audit_path=":memory:"))


def _event(i: int) -> AuditEvent:
    return AuditEvent(
        action="validate",
        actor=f"svc-{i}",
        decision=Decision.ALLOWED,
        summary_prompt=f"submission {i}",
        summary_response="ok",
    )


def _citation(i: int) -> Citation:
    return Citation(
        source_id=f"DOC-{i}",
        regulator=Regulator.MAS,
        jurisdiction=Jurisdiction.SG,
        title=f"Guidance {i}",
        url=f"https://example.test/{i}",
        snippet=f"resilience control requirement {i}",
    )


def test_audit_adapter_is_threadsafe_under_concurrent_records() -> None:
    """record()/read_all() from many threads must not raise and must persist every row."""
    adapter = LocalAppendOnlyAuditAdapter(_settings())
    n = 200

    def work(i: int) -> None:
        adapter.record(_event(i))
        # interleave reads with writes to exercise cross-thread reads too
        adapter.read_all()

    with ThreadPoolExecutor(max_workers=16) as pool:
        # list() forces every future's result, re-raising any worker exception here.
        list(pool.map(work, range(n)))

    assert len(adapter.read_all()) == n


def test_knowledge_adapter_is_threadsafe_under_concurrent_writes_and_reads() -> None:
    """add()/retrieve() from many threads must not raise; all added rows are retrievable."""
    adapter = LocalFtsKnowledgeBaseAdapter(_settings())
    adapter.seed([])  # start from a known-empty index
    n = 200

    def work(i: int) -> None:
        adapter.add([_citation(i)])
        adapter.retrieve("resilience control requirement", top_k=50)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(work, range(n)))

    # Every added citation is present; query a generous top_k to count them.
    hits = adapter.retrieve("resilience control requirement", top_k=n + 10)
    assert len(hits) == n


def test_scanner_adapter_is_threadsafe_under_concurrent_seeds_and_scans() -> None:
    """seed()/scan() from many threads must not raise (the residency live-scan store).

    Like the audit + KB stores, the seeded live scanner opens one ``sqlite3`` connection in
    ``__init__`` but is called from Starlette's anyio worker threads under ``local serve``,
    so it needs the same ``check_same_thread=False`` + serialising lock to survive concurrent
    cross-thread seeds and scans on the shared connection.
    """
    adapter = LocalSeededScannerAdapter(_settings())
    n = 200

    def resource(i: int) -> ResourceConfig:
        return ResourceConfig(
            address=f"google_storage_bucket.kyc_{i}",
            type="google_storage_bucket",
            region="asia-southeast1",
            attributes={"public_access_prevention": "enforced"},
            source_ref=f"main.tf:{i}",
        )

    def work(i: int) -> int:
        # Mix writes (seed a per-thread scope) and reads (scan) on the shared connection.
        scope = f"projects/p-{i}"
        adapter.seed([resource(i)], scope=scope)
        return len(adapter.scan(scope))

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(work, range(n)))

    # Every scan ran without a cross-thread error and returned exactly its seeded estate.
    assert all(r == 1 for r in results)
