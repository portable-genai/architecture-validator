"""``architecture-validator`` — the Typer CLI for the C3 Architecture & Requirements Validator.

This is a thin presentation layer over the domain services. It owns no business logic:
every command builds the wiring from :func:`architecture_validator.config.build_container` and the
factory functions in :mod:`architecture_validator.api.deps`, invokes one domain service, and
pretty-prints the cited result.

Design constraints honoured here:

* **Import-safe.** Importing this module (e.g. as the ``[project.scripts]`` entry point,
  or ``--help``) must never pull in FastAPI, uvicorn or the Google Cloud SDKs. All of
  those are imported *lazily inside command bodies*, so the on-prem/test profile — which
  installs no Google Cloud SDK — can still load the CLI and run ``--help``.
* **Profile-aware.** ``ARCH_VALIDATOR_PROFILE`` selects the adapter stack. The ``onprem``
  profile binds placeholder adapters that raise ``NotImplementedError``; when a command
  trips one, the CLI fails clearly (exit code 2) naming the migration target rather than
  dumping a traceback.
* **Citations are first-class.** Findings and injected requirements are printed with their
  principle / regulatory provenance, because an intake verdict a reviewer cannot trace is
  worthless.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime top level
    from ..config import Container
    from ..domain.models import (
        InjectedRequirement,
        Principle,
        PrincipleFinding,
        ProjectSubmission,
        ValidationReport,
    )

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "C3 Architecture & Requirements Validator — policy-as-code intake gate over the 12 "
        "General Principles, on the Gemini Enterprise Agent Platform (region asia-southeast1)."
    ),
)

_PROFILE_EXIT = 2
_RUNTIME_EXIT = 1
_CLI_ACTOR = "cli:operator"


# --------------------------------------------------------------------------- #
# Wiring helpers (all imports lazy, so this module stays import-safe)
# --------------------------------------------------------------------------- #
def _container() -> Container:
    from ..config import build_container

    return build_container()


def _deps() -> Any:
    try:
        from ..api import deps  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - defensive wiring guard
        _fail(
            f"Service factories (architecture_validator.api.deps) are unavailable: {exc}",
            code=_RUNTIME_EXIT,
        )
    return deps


def _fail(message: str, *, code: int = _RUNTIME_EXIT) -> Any:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _run(action: str, fn: Any) -> Any:
    """Execute ``fn`` and translate adapter failures into clean CLI errors."""
    from ..config import Settings

    profile = Settings.load().profile
    try:
        return fn()
    except NotImplementedError as exc:
        detail = str(exc) or "method not implemented"
        _fail(
            f"'{action}' is not available under profile '{profile}'. "
            f"This profile uses placeholder adapters (on-prem migration target): {detail}",
            code=_PROFILE_EXIT,
        )
    except KeyError as exc:
        _fail(f"'{action}' has no adapter wired for profile '{profile}': {exc}", code=_PROFILE_EXIT)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary: no tracebacks to operators
        _fail(f"'{action}' failed: {type(exc).__name__}: {exc}", code=_RUNTIME_EXIT)


def _load_submission(path: str) -> ProjectSubmission:
    """Read a JSON submission file into a ``ProjectSubmission``."""
    from pathlib import Path

    from ..domain.models import ProjectSubmission

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"could not read submission JSON at {path}: {exc}", code=_RUNTIME_EXIT)
    return ProjectSubmission(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        requirements=str(raw.get("requirements", "")),
        declared_region=raw.get("declared_region"),
        declared_controls=tuple(raw.get("declared_controls", []) or ()),
        uses_pii=bool(raw.get("uses_pii", False)),
        uses_rag=bool(raw.get("uses_rag", False)),
        uses_fine_tuning=bool(raw.get("uses_fine_tuning", False)),
        has_exit_plan=bool(raw.get("has_exit_plan", False)),
        attributes={str(k): str(v) for k, v in (raw.get("attributes") or {}).items()},
    )


# --------------------------------------------------------------------------- #
# Pretty-printing
# --------------------------------------------------------------------------- #
_STATUS_COLOR = {
    "PASS": typer.colors.GREEN,
    "FAIL": typer.colors.RED,
    "NEEDS_INFO": typer.colors.YELLOW,
    "NOT_APPLICABLE": typer.colors.BRIGHT_BLACK,
}


def _echo_citations(citations: Any, indent: str = "    ") -> None:
    if not citations:
        return
    for c in citations:
        page = f" p.{c.page}" if getattr(c, "page", None) is not None else ""
        reg = c.regulator.value if hasattr(c.regulator, "value") else str(c.regulator)
        typer.secho(f"{indent}- [{c.source_id}, {reg}{page}] {c.url}", fg=typer.colors.BRIGHT_BLACK)


def _print_report(report: ValidationReport) -> None:
    sub = report.submission
    verdict = "PASS" if report.passed else "FAIL"
    color = typer.colors.GREEN if report.passed else typer.colors.RED
    typer.secho(f"Validation report — {sub.id}: {sub.name}", bold=True)
    typer.secho(f"  verdict: {verdict}", fg=color, bold=True)
    if report.requires_human_review:
        typer.secho(
            "  [HUMAN REVIEW REQUIRED] maker-checker gate (P-06) — a qualified reviewer "
            "must sign off before intake proceeds.",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    typer.echo("")
    typer.secho("  Findings:", bold=True)
    for f in report.findings:
        sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
        status = f.status.value if hasattr(f.status, "value") else str(f.status)
        styled = typer.style(status.ljust(14), fg=_STATUS_COLOR.get(status, typer.colors.WHITE))
        typer.echo(f"  {styled} {f.principle_id} ({sev})  {f.evidence}")
        _echo_citations(f.citations)
    if report.injected_requirements:
        typer.echo("")
        typer.secho("  Injected requirements:", bold=True)
        for r in report.injected_requirements:
            typer.secho(f"  [{r.principle_id}] {r.requirement_text}", fg=typer.colors.CYAN)
            typer.echo(f"      rationale: {r.rationale}")
            _echo_citations(r.citations, indent="      ")


def _print_injected(requirements: list[InjectedRequirement]) -> None:
    typer.secho(f"Injected requirements ({len(requirements)})", bold=True)
    if not requirements:
        typer.secho(
            "  (no missing requirements — every principle is satisfied)", fg=typer.colors.GREEN
        )
        return
    for r in requirements:
        sev = r.severity.value if hasattr(r.severity, "value") else str(r.severity)
        typer.secho(f"  [{r.principle_id}] ({sev}) {r.requirement_text}", fg=typer.colors.CYAN)
        typer.echo(f"      rationale: {r.rationale}")
        _echo_citations(r.citations, indent="      ")


def _print_principles(principles: list[Principle]) -> None:
    typer.secho(f"General Principles ({len(principles)})", bold=True)
    for p in principles:
        typer.secho(f"  {p.id}  {p.title}", bold=True)
        typer.echo(f"      {p.statement}")
        typer.secho(f"      rule: {p.machine_rule}", fg=typer.colors.BRIGHT_BLACK)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def validate(
    submission: str = typer.Argument(..., help="Path to a JSON project-submission file."),
) -> None:
    """Validate a project submission against the 12 General Principles at intake."""

    def _do() -> ValidationReport:
        sub = _load_submission(submission)
        svc = _deps().build_validation_service(_container())
        return svc.validate(sub, actor=_CLI_ACTOR)

    report = _run("validate", _do)
    _print_report(report)
    if not report.passed:
        raise typer.Exit(0)  # a FAIL verdict is a successful run, not a CLI error


@app.command(name="inject-requirements")
def inject_requirements(
    submission: str = typer.Argument(..., help="Path to a JSON project-submission file."),
) -> None:
    """Show the missing non-functional requirements for a submission's unmet principles."""

    def _do() -> list[InjectedRequirement]:
        from ..domain import principles_eval

        sub = _load_submission(submission)
        container = _container()
        findings: list[PrincipleFinding] = principles_eval.evaluate_all(sub)
        injector = _deps().build_injection_service(container)
        return injector.inject(sub, findings, [])

    result = _run("inject-requirements", _do)
    _print_injected(result)


@app.command(name="principles")
def principles() -> None:
    """List the 12 General Principles (P-01..P-12) the intake gate enforces."""

    def _do() -> list[Principle]:
        from ..domain.principles import all_principles

        return all_principles()

    _print_principles(_run("principles", _do))


# Residency scan commands. The bodies live in ``cli.residency`` (which
# also backs the ``residency-validator`` console script) so both CLIs share one impl and
# one set of gating exit codes (0 clean / 1 gating / 2 profile / 3 runtime).
from .residency import policy as _residency_policy  # noqa: E402
from .residency import scan as _residency_scan  # noqa: E402

app.command(name="scan")(_residency_scan)
app.command(name="policy")(_residency_policy)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address for the API server."),
    port: int = typer.Option(8088, help="TCP port for the API server."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code change (dev only)."),
) -> None:
    """Run the FastAPI app (A2A card, REST endpoints) under uvicorn."""

    def _do() -> None:
        import uvicorn

        deps = _deps()
        if not hasattr(deps, "create_app"):
            _fail(
                "architecture_validator.api.deps does not expose create_app().",
                code=_RUNTIME_EXIT,
            )
        typer.secho(
            f"serving architecture-validator on http://{host}:{port} (profile={_profile_label()})",
            fg=typer.colors.GREEN,
        )
        uvicorn.run(
            "architecture_validator.api.deps:create_app",
            factory=True,
            host=host,
            port=port,
            reload=reload,
        )

    _run("serve", _do)


@app.command()
def eval(  # noqa: A001 - "eval" is the documented command name in SPEC §
    dataset: str | None = typer.Option(
        None,
        "--dataset",
        "-d",
        help="Path to the golden eval dataset (defaults to the bundled set).",
    ),
) -> None:
    """Run the A4 promotion eval gate (principle accuracy / injection recall / citations)."""

    def _do() -> int:
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "eval" / "run_eval.py"
        if not script.exists():
            _fail(f"eval gate script not found at {script}", code=_RUNTIME_EXIT)
        cmd = [sys.executable, str(script)]
        if dataset:
            cmd += ["--dataset", dataset]
        typer.secho(f"running eval gate: {script}", fg=typer.colors.CYAN)
        completed = subprocess.run(cmd, check=False)  # noqa: S603 - trusted local script
        return completed.returncode

    code = _run("eval", _do)
    typer.secho(
        "eval gate: PASS" if code == 0 else "eval gate: FAIL",
        fg=typer.colors.GREEN if code == 0 else typer.colors.RED,
        bold=True,
    )
    raise typer.Exit(int(code))


def _profile_label() -> str:
    from ..config import Settings

    return Settings.load().profile


if __name__ == "__main__":  # pragma: no cover
    app()
