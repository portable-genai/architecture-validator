# Demo scripts - `architecture-validator`

All scripts are SDK-free and run the real intake-gate flow against the in-process
`local` profile (no Google Cloud, no API key). They use the repo's built-in synthetic
submissions from `tests/fixtures/sample_projects.py`, so run them from the repo root with
the domain package and the test fixtures on the path:

```bash
export PYTHONPATH=src:tests
export ARCH_VALIDATOR_PROFILE=local
```

| Script | What it does |
|--------|--------------|
| `arch_demo.py` | Runs the real `ValidationService` over both synthetic submissions (the blocked onboarding bot, then the clean policy assistant), prints a per-case summary, and writes the cited audit-view JSON. |
| `render_arch_ui.py` | Renders that JSON into static, audit-first HTML pages (one per case plus an index) for screenshots and slides. |
| `arch_demo_server.py` | A **live, click-through** server that runs the *real* `ValidationService` one submission per click and renders the audit-first UI (intro to blocked to clean). |
| `arch_demo_playwright.py` | A **presenter-controlled** Playwright walkthrough of the live server (or the live Next.js console): it narrates each step and waits for you to press Enter before performing it. |

## Static artifacts (slides / screenshots)

```bash
python scripts/arch_demo.py arch_demo.json              # prints the per-case summary
python scripts/render_arch_ui.py arch_demo.json ./out   # ./out/arch-case-*.html, arch-index.html
```

Or with the Makefile (writes to `demo_out/`):

```bash
make demo
```

## Live, presenter-controlled demo

Two terminals:

```bash
# 1) the live demo server  (http://localhost:8092)
PYTHONPATH=src:tests ARCH_VALIDATOR_PROFILE=local python scripts/arch_demo_server.py
# or:  make demo-server

# 2) the guided walkthrough  (a real Chrome window opens)
pip install playwright && playwright install chromium      # one-time
python scripts/arch_demo_playwright.py
```

The walkthrough is **paced by you**: it prints what the next step will do, waits for you to
press **Enter**, then clicks **Next** and spotlights the panel to look at. The three steps
are: gate ready (two submissions queued) to onboarding bot BLOCKED (8 principle FAILs +
injected requirements) to policy assistant CLEARS intake (every principle satisfied).

You can also just open `http://localhost:8092` and click **Next** / **Restart** by hand -
the server holds the live validation session, so the buttons drive the same real flow.

The demo port (`8092`) is deliberately distinct from the FastAPI API port (`8088`), so the
demo server and `make run-api` can run side by side.

### Pointing the walkthrough at the live Next.js console

Set `DEMO_URL=http://localhost:3000` to narrate over the real console (`make run-ui` +
`make run-api PROFILE=local`) instead of the demo server. The spotlight selectors fall back
gracefully if a panel is not found.

Useful environment overrides for `arch_demo_playwright.py`:

| Var | Default | Purpose |
|-----|---------|---------|
| `DEMO_URL` | `http://127.0.0.1:8092` | server (or live console) base URL |
| `HEADLESS=1` | off | run without a window (self-test / recording) |
| `DEMO_AUTO=1` | off | don't wait for Enter - advance automatically |
| `SLOWMO_MS` | `250` headed | per-action slow motion |
| `CHROME_PATH` | - | explicit Chromium / Chrome binary |
| `lock.py` | Compiles both lockfiles and puts the header back, because `uv pip compile` REPLACES the output file: it writes its own two-line provenance comment and destroys the `tag = commit` map the pin tests check against. `make lock` runs this rather than uv directly. |
