# Contributing: `architecture-validator`

Thanks for helping improve `architecture-validator`. This is an engineering-portfolio reference repo; the bar is
production-grade style and a green offline gate.

## Setup

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"        # NO Google Cloud SDK: the onprem/test profile
```

For the managed stack: `pip install -e ".[gcp,dev]"` and run under `ARCH_VALIDATOR_PROFILE=gcp`.

## The gate (must be green before you push)

```bash
ruff check src tests            # lint: must be clean
ruff format --check src tests   # format: must be clean
pytest -m 'not integration' -q  # unit + contract: must pass
mypy src                        # type-check: should pass
python eval/run_eval.py         # `model-quality-gate` / P-08 eval gate: should pass (exit 0)
```

`make fmt` auto-formats and auto-fixes; `make lint` runs ruff + mypy; `make test` runs the
suite on the onprem profile.

## Architecture rules (do not break these)

- **Keep the domain pure.** `src/architecture_validator/domain` imports only the standard library:
  no google-cloud, ADK, FastAPI, httpx or pydantic. Models are frozen dataclasses; services
  take explicit port instances.
- **The policy engine owns the verdict.** The LLM only drafts requirement / rationale prose.
  Never let the model decide PASS/FAIL/NEEDS_INFO.
- **One source of truth for the rules.** If you change a principle check, change it in
  `domain/principles_eval.py` *and* the matching rule in `policies/principles.rego`, and add
  / update a test in `tests/unit/test_principles_eval.py`. They must agree.
- **GCP imports are lazy.** Anything in `adapters/gcp/*` must import google-* only inside
  methods or under `TYPE_CHECKING`. The wiring layers (`api`, `cli`, `agent`) must import
  with no GCP SDK installed.
- **Every adapter is `Adapter(settings: Settings)`.** Add new ports with a `gcp` and an
  `onprem` binding in `config/settings.yaml`, then extend `tests/contract` accordingly.
- **No third-party OSS product is named in the on-prem stubs.** They are migration targets.
- **A model adapter notes what answered, and samples per call.** After a successful call the
  `gcp` adapter calls `hex_service_kit.provenance.note_model(<the model id it actually called>)`,
  and `provenance.note_search()` only when an online search tool was attached to THAT call; the
  `local` stub notes `config.LOCAL_STUB_MODEL`; the `live` adapter needs nothing, because the kit
  client notes itself. `api/app.py` turns the notes into `X-Answered-By` / `X-Search-Used`, and
  the console's pills show them. `LlmRequest.temperature` is `float | None = None` and an adapter
  OMITS it when `None` (some models reject the parameter, so free means absent, never `1.0`). Pin
  `0.0` only where the output is extracted, classified, scored or compared; leave drafting and
  narration free. There is no second, harder model a flag can swap in: `generator_model` must be
  the model the adapter calls. Covered by `tests/unit/test_answer_provenance.py` and
  `tests/unit/test_sampling_per_call.py`.

### Extension touch lists

Adding an adapter requires updating its profile module, its `config/settings.yaml` binding, the
constructor/parity contract and a behavior test. Adding a port or sub-service requires updating
the `ports/` Protocol and `ports/__init__.py`, every applicable local/gcp/platform/onprem binding,
`Container` wiring, service/API/CLI composition, structural and behavioral contract tests,
configuration docs, the eval gate when claims change, and the portability/demo evidence.

## Tests

- `tests/unit`: real domain-service tests driven by the in-memory fakes in `conftest.py`.
- `tests/contract/test_port_parity.py`: proves on-prem parity with the ports.
- `tests/integration`: marked `@pytest.mark.integration`, deselected by default; may import
  GCP adapters lazily and is skipped without `GOOGLE_CLOUD_PROJECT`.

## Commits

Commits are authored solely by the contributor. Do not add `Co-Authored-By` trailers.
Branch off `main`; open a PR; the hosted `gate.yaml` check, which runs `make check`, must pass.

## Markdown style

Minimise em-dashes in all markdown. Use colons for `label: definition`, commas / semicolons
for asides, parentheses for parentheticals. Inline `→` and `·` are fine.
