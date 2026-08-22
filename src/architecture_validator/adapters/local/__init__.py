"""Local deployment profile adapters — a WORKING, offline laptop stack.

The ``local`` profile is the third deployment option alongside ``gcp`` (managed Google
Cloud services) and ``onprem`` (fail-fast Google Distributed Cloud migration
placeholders). Unlike ``onprem``, every adapter here is a *real, deterministic*
implementation that runs the whole C3 intake pipeline end to end with **no Google Cloud,
no API key, and no running emulators by default**:

* Knowledge base (reg-KB retrieval) -> a ``sqlite3`` **FTS5** index over the regulatory
  passages (BM25 rank), seeded from a built-in synthetic corpus.
* Policy engine -> the deterministic in-process principle evaluator
  (:mod:`architecture_validator.domain.principles_eval`), the same rule logic the rego bundle
  encodes, so the local and managed verdicts agree by construction.
* LLM -> a deterministic, schema-driven generator (no model, no network).
* Control mapping and residency -> in-process canned signals (the laptop runs one app,
  not the whole platform, so these are NOT HTTP clients here).
* Audit -> an append-only local store (SQLite or in-memory), read-back supported.
* Tracer -> no-op spans.
* Evaluation -> delegates to the in-repo offline eval gate (``eval/run_eval.py``).
* Registry / tool catalog -> in-process A2A / MCP stores, seedable.

Everything is **seedable** so the test suite stays deterministic, and the default code
path imports **no google-cloud package at module top level**. Optional higher-fidelity
local runs route to Google's official emulators when the standard ``*_EMULATOR_HOST``
env vars are set (the google client is imported lazily, only on that branch); see
:mod:`architecture_validator.adapters.local._emulator`.
"""
