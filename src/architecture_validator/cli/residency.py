"""``residency-validator`` — the residency-scan Typer app and CI gate.

This module owns the ``scan`` and ``policy`` command bodies for the residency
scanner. It is exposed two ways:

* as its own Typer app (``app`` here) wired to the ``residency-validator`` console script,
  so a CI pipeline invokes the gate as ``residency-validator scan --plan ...``; and
* the same command functions are registered onto the primary ``architecture-validator`` CLI (see
  :mod:`architecture_validator.cli.main`) so ``architecture-validator scan`` /
  ``architecture-validator policy`` also work.

Exit codes: 0 = scan clean (gate PASS); 1 = gating violations (gate FAIL); 2 = the active
profile cannot satisfy the command; 3 = unexpected runtime error.

Import-safe: FastAPI / uvicorn / Google Cloud SDKs are imported lazily inside command
bodies, so loading this module (the console-script entry point, or ``--help``) never pulls
in a cloud SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import Container
    from ..domain.residency.models import ResidencyScan

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Residency scanner — scan IaC / configs for region and "
        "residency violations and gate a CI pipeline (region asia-southeast1)."
    ),
)

# Exit codes.
_PROFILE_EXIT = 2
_RUNTIME_EXIT = 3
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
        _fail(f"Service factories (architecture_validator.api.deps) are unavailable: {exc}")
    return deps


def _fail(message: str, *, code: int = _RUNTIME_EXIT) -> Any:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _profile() -> str:
    from ..config import Settings

    return Settings.load().profile


# --------------------------------------------------------------------------- #
# Pretty-printing
# --------------------------------------------------------------------------- #
def _print_scan(scan: ResidencyScan) -> None:
    typer.secho(
        f"Residency scan — {scan.target}",
        bold=True,
        fg=typer.colors.GREEN if scan.passed else typer.colors.RED,
    )
    typer.echo(f"  resources scanned: {scan.resources_scanned}")
    counts = ", ".join(f"{c.count} {c.severity.value}" for c in scan.verdict.counts) or "none"
    typer.echo(f"  violations: {len(scan.violations)} ({counts})")
    typer.echo(f"  gate severity: {scan.verdict.gate_severity.value}")
    if scan.requires_human_review:
        typer.secho(
            "  [HUMAN REVIEW REQUIRED] a HIGH/CRITICAL residency violation must be "
            "reviewed before any exception is granted (maker-checker, P-06).",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    for v in scan.violations:
        sev = v.severity.value.upper()
        styled = typer.style(
            sev,
            fg=typer.colors.RED if sev in ("HIGH", "CRITICAL") else typer.colors.YELLOW,
            bold=True,
        )
        region = v.found_region if v.found_region is not None else "(none)"
        typer.echo(f"  [{styled}] {v.kind.value} on {v.resource.address} ({v.resource.type})")
        typer.echo(f"      found_region={region}  evidence={v.evidence}")
        typer.echo(f"      fix: {v.remediation}")
        cites = ", ".join(f"{c.source_id} ({c.regulator.value})" for c in v.citations)
        if cites:
            typer.secho(f"      cites: {cites}", fg=typer.colors.BRIGHT_BLACK)
    verdict = "PASS" if scan.passed else "FAIL"
    typer.secho(
        f"  VERDICT: {verdict}",
        fg=typer.colors.GREEN if scan.passed else typer.colors.RED,
        bold=True,
    )


# --------------------------------------------------------------------------- #
# Commands (shared: also registered on the architecture-validator CLI)
# --------------------------------------------------------------------------- #
def scan(
    plan: str | None = typer.Option(
        None, "--plan", help="Path to a 'terraform show -json' plan file to scan."
    ),
    directory: str | None = typer.Option(
        None, "--dir", help="Path to a directory of .tf files to scan."
    ),
    project: str | None = typer.Option(
        None, "--project", help="A live project / scope (projects/ID) — uses the gcp scanner."
    ),
) -> None:
    """Scan a Terraform plan / directory / project and FAIL the build on violations.

    Exactly one of --plan / --dir / --project must be given. Exits 1 when the scan finds
    a violation at or above the gate severity (so CI fails), 0 when clean.
    """
    targets = [t for t in (plan, directory, project) if t]
    if len(targets) != 1:
        _fail("provide exactly one of --plan, --dir or --project", code=_PROFILE_EXIT)
    target = targets[0]
    action = "scan_project" if project else "scan_iac"

    def _do() -> ResidencyScan:
        svc = _deps().build_scan_service(_container())
        return svc.scan_target(target, actor=_CLI_ACTOR, action=action)

    scan_result = _run("scan", _do)
    _print_scan(scan_result)
    raise typer.Exit(scan_result.verdict.exit_code)


def policy() -> None:
    """Print the active residency policy (allowed regions, required controls, gate)."""

    def _do() -> Any:
        from ..config import Settings

        return Settings.load().build_residency_policy()

    pol = _run("policy", _do)
    controls = ", ".join(c.value for c in sorted(pol.required_controls, key=lambda x: x.value))
    typer.secho("Residency policy", bold=True, fg=typer.colors.GREEN)
    typer.echo(f"  allowed regions: {', '.join(sorted(pol.allowed_regions))}")
    typer.echo(f"  required controls: {controls}")
    typer.echo(f"  gate severity: {pol.gate_severity.value}")


def _run(action: str, fn: Any) -> Any:
    """Execute ``fn`` and translate adapter failures into clean CLI errors.

    ``NotImplementedError`` (the on-prem placeholder adapters) maps to a profile error
    that names the migration target; ``typer.Exit`` (the gate verdict) is re-raised
    unchanged; anything else surfaces as a runtime error.
    """
    profile = _profile()
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
        _fail(f"'{action}' failed: {type(exc).__name__}: {exc}")


app.command()(scan)
app.command()(policy)


if __name__ == "__main__":  # pragma: no cover
    app()
