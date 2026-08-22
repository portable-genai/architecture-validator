# C3 Architecture & Requirements Validator — developer Makefile.
#
# The default dev/test targets run under the LOCAL profile: a real, working offline
# stack (SQLite FTS5 reg-KB + deterministic LLM) that runs the whole intake pipeline
# with NO Google Cloud SDK installed. Override PROFILE=gcp for the managed stack, or
# PROFILE=onprem for the fail-fast migration placeholders.

PYTHON      ?= python3
PIP         ?= pip
PROFILE     ?= local
SRC         := src/architecture_validator
TESTS       := tests
API_APP     := architecture_validator.api.app:app
API_HOST    ?= 127.0.0.1  # no-auth local dev binds loopback; override deliberately
API_PORT    ?= 8088
UI_DIR      := ui
TF_DIR      := infra/terraform
DEMO_PORT   ?= 8092
DEMO_OUT    ?= demo_out

export ARCH_VALIDATOR_PROFILE := $(PROFILE)

.DEFAULT_GOAL := help
.PHONY: help install install-gcp fmt lint test seed-local eval scan scan-local run-api run-ui tf-plan tf-validate clean demo demo-selftest demo-server check ui-install ui-check

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the package + dev tooling (NO GCP SDK — onprem/test profile).
	$(PIP) install -e ".[dev]"

install-gcp: ## Install with the managed-stack extra (google-adk, genai, discoveryengine, ...).
	$(PIP) install -e ".[gcp,dev]"

fmt: ## Auto-format and auto-fix lint issues.
	ruff format $(SRC) $(TESTS)
	ruff check --fix $(SRC) $(TESTS)

lint: ## Lint (ruff), check formatting (ruff format --check), and type-check (mypy).
	ruff check $(SRC) $(TESTS)
	ruff format --check $(SRC) $(TESTS)
	mypy $(SRC)

test: ## Run unit + contract tests on the local profile (no GCP SDK required).
	ARCH_VALIDATOR_PROFILE=local pytest -m 'not integration' -q

seed-local: ## Seed a tiny local corpus and run a sample validation (offline, PROFILE=local).
	ARCH_VALIDATOR_PROFILE=local $(PYTHON) -m architecture_validator.cli.main validate eval/datasets/sample_submission.json

eval: ## Run the A4 eval gate (principle accuracy / injection recall / citations / safety).
	$(PYTHON) eval/run_eval.py

scan: ## Scan the bundled sample plan (the residency CI gate; FAILs on violations).
	residency-validator scan --plan tests/fixtures/sample_plan.json

scan-local: ## Run the LIVE residency scan offline under the local profile (seeded estate, FAILs).
	ARCH_VALIDATOR_PROFILE=local residency-validator scan --project projects/demo-sg

run-api: ## Run the FastAPI service (PROFILE=$(PROFILE)).
	uvicorn $(API_APP) --host $(API_HOST) --port $(API_PORT) --reload

run-ui: ## Run the React / Next.js UI (dev server).
	cd $(UI_DIR) && npm install && npm run dev

portability: ## Execute the bounded offline/profile portability proof.
	PYTHONPATH=src $(PYTHON) scripts/portability_demo.py

check: lint test eval portability demo-selftest tf-validate ## The full offline quality gate (no node, no cloud).

ui-install: ## Install the console's pinned dependencies from the committed lockfile.
	npm ci --prefix $(UI_DIR)

ui-check: ## The console gate: types, CSP unit tests, build, then hydration against the BUILT server.
	npm --prefix $(UI_DIR) run lint
	npm --prefix $(UI_DIR) test
	NEXT_TELEMETRY_DISABLED=1 npm --prefix $(UI_DIR) run build
	# LAST, and against the artefact the build above just produced. Everything before this line
	# passed while the console was shipping dead markup: the CSP string was checkable and correct,
	# tsc was clean, the build succeeded, and the page still never hydrated. Only starting the
	# built server and reading the served bytes can tell the working case from the broken one,
	# because the response header is byte-identical in both.
	npm --prefix $(UI_DIR) run assert-hydratable

demo: ## Run the offline intake-gate demo (PROFILE=local) and render static HTML to $(DEMO_OUT)/.
	ARCH_VALIDATOR_PROFILE=local PYTHONPATH=src:tests $(PYTHON) scripts/arch_demo.py $(DEMO_OUT)/arch_demo.json
	ARCH_VALIDATOR_PROFILE=local PYTHONPATH=src:tests $(PYTHON) scripts/render_arch_ui.py $(DEMO_OUT)/arch_demo.json $(DEMO_OUT)

demo-selftest: ## Execute the real two-case demo and assert its evidence and rendered panels.
	ARCH_VALIDATOR_PROFILE=local PYTHONPATH=src:tests:scripts $(PYTHON) scripts/demo_selftest.py

demo-server: ## Run the live, click-through intake-gate demo server on :$(DEMO_PORT) (offline).
	ARCH_VALIDATOR_PROFILE=local PYTHONPATH=src:tests $(PYTHON) scripts/arch_demo_server.py --port $(DEMO_PORT)

tf-plan: ## Terraform plan for the asia-southeast1 infrastructure.
	cd $(TF_DIR) && terraform init -input=false && terraform plan

tf-validate: ## Validate Terraform format and schema offline with no cloud credentials.
	cd $(TF_DIR) && terraform fmt -check -recursive -diff \
		&& terraform init -backend=false -input=false \
		&& terraform validate -no-color

clean: ## Remove caches and build artefacts.
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov $(DEMO_OUT)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
