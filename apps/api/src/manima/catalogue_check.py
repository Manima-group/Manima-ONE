"""Helpers for contract tests: the full set of permission keys the registry declares."""

from manima.core.catalogue import PLATFORM_PERMISSIONS, all_tenant_permissions


def all_declared_permissions() -> set[str]:
    return set(all_tenant_permissions()) | set(PLATFORM_PERMISSIONS)
