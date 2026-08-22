"""The file-based Terraform scanner — the CI-gate workhorse.

The primary residency-scan use ("runs as a CI gate") reads a local **Terraform plan
JSON** (``terraform show -json`` output) or raw ``.tf`` files and needs **no cloud and no
Google Cloud SDK**: it is pure standard library (``json`` + ``re``). It is implemented
here as a pipeline (the analogue of the toolkit's ``pipelines`` modules), not a profile
adapter, so it always runs regardless of the active profile.

Two entry points produce normalised :class:`ResourceConfig` objects the deterministic
detector grades:

* :func:`parse_plan_json` — walk ``planned_values.root_module`` (and nested
  ``child_modules``) recursively, extracting ``address``, ``type`` and a region /
  location attribute, plus the residency-relevant attributes (CMEK key, public-access
  flags, VPC-SC perimeter) the detector inspects.
* :func:`parse_tf_dir` — a light regex fallback over ``*.tf`` HCL files for repos that
  have not produced a plan yet; it extracts ``resource "<type>" "<name>"`` blocks and
  the same handful of attributes, recording a ``file:line`` source_ref.

:func:`parse_target` dispatches on the path (a ``.json`` file, a single ``.tf`` file,
or a directory of ``.tf`` files).

This module depends only on the pure domain models — no Google Cloud SDK — so it imports
and runs under every profile.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..domain.errors import ScanTargetError
from ..domain.residency.models import ResourceConfig

# Attribute keys (in a resource's planned ``values``) that may carry the region /
# location, in priority order.
_REGION_KEYS: tuple[str, ...] = ("region", "location", "zone")

# Attribute keys we lift verbatim into ResourceConfig.attributes so the detector can
# evidence residency controls. Values are coerced to strings.
_CONTROL_KEYS: tuple[str, ...] = (
    "kms_key_name",
    "kms_key_id",
    "encryption_key",
    "customer_managed_key",
    "cmek_key",
    "kms_key",
    "public_access_prevention",
    "publicly_accessible",
    "ipv4_enabled",
    "assign_public_ip",
    "public_access",
    "allow_public_egress",
    "service_perimeter",
    "vpc_sc_perimeter",
    "access_policy",
)


# --------------------------------------------------------------------------- #
# Plan JSON parsing (the primary path)
# --------------------------------------------------------------------------- #
def parse_plan_json(path: str | Path) -> list[ResourceConfig]:
    """Parse a ``terraform show -json`` plan file into :class:`ResourceConfig` list."""
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScanTargetError(f"cannot read plan file {p}: {exc}") from exc
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScanTargetError(f"{p}: invalid Terraform plan JSON: {exc}") from exc

    root = ((plan.get("planned_values") or {}).get("root_module")) or {}
    if not root and "resource_changes" not in plan:
        # Not a plan document we recognise; surface rather than silently pass.
        raise ScanTargetError(
            f"{p}: no planned_values.root_module found; is this a 'terraform show -json' plan?"
        )
    resources: list[ResourceConfig] = []
    _walk_module(root, str(p), resources)
    return resources


def _walk_module(module: dict[str, Any], source_file: str, out: list[ResourceConfig]) -> None:
    """Recursively collect resources from a module and its child_modules."""
    for resource in module.get("resources") or ():
        if not isinstance(resource, dict):
            continue
        config = _resource_from_planned(resource, source_file)
        if config is not None:
            out.append(config)
    for child in module.get("child_modules") or ():
        if isinstance(child, dict):
            _walk_module(child, source_file, out)


def _resource_from_planned(resource: dict[str, Any], source_file: str) -> ResourceConfig | None:
    """Build a ResourceConfig from one planned-values resource object."""
    address = str(resource.get("address") or "").strip()
    rtype = str(resource.get("type") or "").strip()
    if not address or not rtype:
        return None
    values = resource.get("values")
    values = values if isinstance(values, dict) else {}

    region = _extract_region(values)
    attributes = _extract_attributes(values)
    return ResourceConfig(
        address=address,
        type=rtype,
        region=region,
        attributes=attributes,
        source_ref=f"{source_file}#{address}",
    )


def _extract_region(values: dict[str, Any]) -> str | None:
    for key in _REGION_KEYS:
        val = values.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_attributes(values: dict[str, Any]) -> dict[str, str]:
    """Lift the residency-relevant control attributes into a string dict.

    Nested config blocks (e.g. ``encryption_configuration`` carrying ``kms_key_name``)
    are flattened one level so a CMEK key set inside a block is still found.
    """
    attrs: dict[str, str] = {}
    for key in _CONTROL_KEYS:
        if key in values and values[key] is not None:
            attrs[key] = _coerce(values[key])
    # One level of nested blocks (Terraform renders these as nested dicts / lists).
    for value in values.values():
        for block in _as_blocks(value):
            for key in _CONTROL_KEYS:
                if key in block and block[key] is not None and key not in attrs:
                    attrs[key] = _coerce(block[key])
    return attrs


def _as_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [b for b in value if isinstance(b, dict)]
    return []


def _coerce(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# --------------------------------------------------------------------------- #
# .tf (HCL) regex fallback
# --------------------------------------------------------------------------- #
_RESOURCE_RE = re.compile(
    r'resource\s+"(?P<type>[a-z0-9_]+)"\s+"(?P<name>[A-Za-z0-9_-]+)"\s*\{',
)
# Match `key = "value"` (string), `key = value` (bare token), within a block.
_ATTR_RE = re.compile(
    r'(?P<key>[a-z0-9_]+)\s*=\s*(?:"(?P<sval>[^"]*)"|(?P<bval>[A-Za-z0-9_.\-/]+))',
)


def parse_tf_dir(path: str | Path) -> list[ResourceConfig]:
    """Parse ``.tf`` files under ``path`` (or a single ``.tf`` file) into resources.

    A light HCL fallback for repos without a plan: it finds each top-level
    ``resource "<type>" "<name>"`` block and scans its body (until the matching brace)
    for the region / location and the residency-control attributes. Best-effort by
    design; the plan-JSON path is authoritative.
    """
    p = Path(path)
    files = [p] if p.is_file() else sorted(p.rglob("*.tf"))
    if not files:
        raise ScanTargetError(f"{p}: no .tf files found to scan")
    resources: list[ResourceConfig] = []
    for tf_file in files:
        try:
            text = tf_file.read_text(encoding="utf-8")
        except OSError:
            continue
        resources.extend(_parse_tf_text(text, str(tf_file)))
    return resources


def _parse_tf_text(text: str, source_file: str) -> list[ResourceConfig]:
    out: list[ResourceConfig] = []
    for match in _RESOURCE_RE.finditer(text):
        rtype = match.group("type")
        name = match.group("name")
        body = _block_body(text, match.end() - 1)
        line = text.count("\n", 0, match.start()) + 1
        attrs_all = _scan_attrs(body)
        region = next((attrs_all[k] for k in _REGION_KEYS if k in attrs_all), None)
        attributes = {k: v for k, v in attrs_all.items() if k in _CONTROL_KEYS}
        out.append(
            ResourceConfig(
                address=f"{rtype}.{name}",
                type=rtype,
                region=region,
                attributes=attributes,
                source_ref=f"{source_file}:{line}",
            )
        )
    return out


def _block_body(text: str, open_brace_index: int) -> str:
    """Return the substring inside the brace-balanced block starting at ``{``."""
    depth = 0
    for i in range(open_brace_index, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index + 1 : i]
    return text[open_brace_index + 1 :]


def _scan_attrs(body: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(body):
        key = m.group("key")
        if key in attrs:
            continue
        value = m.group("sval") if m.group("sval") is not None else m.group("bval")
        if value is not None:
            attrs[key] = value
    return attrs


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def parse_target(target: str | Path) -> list[ResourceConfig]:
    """Parse ``target``: a ``.json`` plan, a single ``.tf`` file, or a ``.tf`` directory."""
    p = Path(target)
    if not p.exists():
        raise ScanTargetError(f"scan target does not exist: {p}")
    if p.is_dir():
        return parse_tf_dir(p)
    if p.suffix == ".json":
        return parse_plan_json(p)
    if p.suffix == ".tf":
        return parse_tf_dir(p)
    raise ScanTargetError(f"unsupported scan target {p}: expected a .json plan or .tf file/dir")
