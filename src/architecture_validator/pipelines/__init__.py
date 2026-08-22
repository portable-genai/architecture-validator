"""Pipelines for the residency scan.

The Terraform plan / ``.tf`` parser (``terraform.py``) is the CI-gate workhorse: pure
standard library (json + re), it always runs regardless of the active profile and turns a
local plan / directory into the :class:`ResourceConfig` list the deterministic detector
grades.
"""
