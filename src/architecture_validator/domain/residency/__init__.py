"""Residency scanning domain: deterministic region-violation rules.

This subpackage is the deterministic residency-scan core: it grades infrastructure
configuration (Terraform plan JSON / ``.tf`` files, or a live Cloud Asset Inventory
estate) against a :class:`~architecture_validator.domain.residency.models.ResidencyPolicy` and
emits a PASS/FAIL :class:`~architecture_validator.domain.residency.models.ResidencyScan` that
gates a CI pipeline.

It is namespaced under ``domain/residency`` so it sits beside C3's own flat domain
modules without colliding. It reuses the shared kernel types (``Citation``, ``Severity``,
``Regulator``, ``Jurisdiction``, ``AuditEvent``, ``utcnow``, ``SEVERITY_RANK``) from
:mod:`architecture_validator.domain.models`, and defines only the residency-specific types here.
Pure standard library — no Google Cloud / ADK / FastAPI imports.
"""
