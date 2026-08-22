"""A7: the kernel/vertical split is a real dependency direction, not a label.

The check that matters is not "a module named ``kernel`` exists". SPEC named the
reusable evidence / audit / evaluation / identity / citation / severity kernel and the
Rsk3 submission / principle / injection / residency vertical long before either had a
module of its own, and a ``kernel`` that merely re-exported from the mixed
``domain/models.py`` would satisfy every static reading of that claim while still
forcing a fork to import the intake-gate artifacts it is about to rewrite.

So the primary assertion here is executed, not read: a fresh interpreter imports
``architecture_validator.domain.kernel`` and reports whether
``architecture_validator.domain.models`` ended up in ``sys.modules``. Against a re-export shim
that subprocess prints the vertical module, so this file is RED for anything short of a
physical split.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from architecture_validator.domain import kernel, models

SRC = Path(__file__).resolve().parents[2] / "src"
KERNEL_PATH = SRC / "architecture_validator" / "domain" / "kernel.py"

# The vertical-neutral machinery A7 requires a fork to inherit untouched.
KERNEL_NAMES = (
    "AgentCard",
    "AgentSkill",
    "AuditEvent",
    "Citation",
    "Decision",
    "EvalMetricResult",
    "EvalReport",
    "Jurisdiction",
    "LlmMessage",
    "LlmRequest",
    "LlmResponse",
    "MemoryItem",
    "REGULATOR_JURISDICTION",
    "Regulator",
    "RetrievalQuery",
    "SEVERITY_RANK",
    "Session",
    "Severity",
    "StrEnum",
    "ThinkingLevel",
    "TokenUsage",
    "ToolSpec",
    "utcnow",
)

# The Rsk3 intake-gate artifacts a fork rewrites. None may live in the kernel.
VERTICAL_NAMES = (
    "CheckStatus",
    "InjectedRequirement",
    "Principle",
    "PrincipleFinding",
    "ProjectSubmission",
    "ValidationReport",
)


def _imported_modules(module: str) -> list[str]:
    """Import ``module`` in a FRESH interpreter and report what it pulled in."""
    program = (
        "import json, sys\n"
        f"import {module}\n"
        "print(json.dumps(sorted(m for m in sys.modules "
        "if m.startswith('architecture_validator'))))\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=str(SRC),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_importing_the_kernel_does_not_import_the_vertical_models() -> None:
    """Executed proof of the dependency direction, in a process of its own."""
    imported = _imported_modules("architecture_validator.domain.kernel")
    assert "architecture_validator.domain.kernel" in imported
    assert "architecture_validator.domain.models" not in imported, (
        "importing the kernel dragged the vertical model module in; the split is a "
        f"label, not a boundary (imported: {imported})"
    )


def test_the_vertical_models_do_import_the_kernel() -> None:
    """The arrow must exist in the other direction, or nothing is actually shared."""
    imported = _imported_modules("architecture_validator.domain.models")
    assert "architecture_validator.domain.kernel" in imported


def test_kernel_source_has_no_intra_package_imports() -> None:
    """Static backstop: the kernel depends on the stdlib and the commons only."""
    tree = ast.parse(KERNEL_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"kernel makes a relative import of {node.module!r}"
            assert not (node.module or "").startswith("architecture_validator"), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("architecture_validator"), alias.name


@pytest.mark.parametrize("name", KERNEL_NAMES)
def test_kernel_names_are_defined_in_the_kernel_and_re_exported(name: str) -> None:
    """Backward-compatible re-exports keep every existing import site working."""
    assert hasattr(kernel, name), f"{name} is not in the kernel"
    assert getattr(models, name) is getattr(kernel, name), (
        f"models.{name} is not the same object as kernel.{name}"
    )


@pytest.mark.parametrize("name", VERTICAL_NAMES)
def test_vertical_artifacts_stay_out_of_the_kernel(name: str) -> None:
    assert hasattr(models, name)
    assert not hasattr(kernel, name), f"{name} is vertical and must not sit in the kernel"
