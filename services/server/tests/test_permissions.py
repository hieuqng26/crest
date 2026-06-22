"""Tests for the permission catalog and resolver.

Run from services/server/:
    python3.11 -m pytest tests/test_permissions.py -v

No Flask app context or database required — permissions.py is pure Python.
"""

import importlib.util
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: load permissions.py by file path, bypassing project/__init__.py
# which pulls Flask (not available in this isolated test environment).
# ---------------------------------------------------------------------------

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Stub out the bare minimum so importlib can load the file
sys.modules.setdefault("project", types.ModuleType("project"))


def _import_module(name: str, rel_path: str):
    """Import a module by file path, bypassing project/__init__.py."""
    abs_path = os.path.join(_BASE, rel_path)
    spec = importlib.util.spec_from_file_location(name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_perms_mod = _import_module(
    "project.api.auth.permissions",
    "project/api/auth/permissions.py",
)

ALL_PERMISSIONS = _perms_mod.ALL_PERMISSIONS
catalog_payload = _perms_mod.catalog_payload
has_permission = _perms_mod.has_permission
is_valid_permission = _perms_mod.is_valid_permission
normalize_permissions = _perms_mod.normalize_permissions


# ---------------------------------------------------------------------------
# Tests (identical assertions to the brief)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "perm,valid",
    [
        ("dataset:read", True),
        ("credit_risk:execute", True),
        ("user:write", True),
        ("role:read", True),
        ("evaluation:write", False),  # evaluation is read-only
        ("auditlog:write", False),  # auditlog is read-only
        ("dataset:manage", False),  # 'manage' is not an action
        ("nope:read", False),  # unknown page
    ],
)
def test_is_valid_permission(perm, valid):
    assert is_valid_permission(perm) is valid


@pytest.mark.parametrize(
    "perms,perm,expected",
    [
        ({"dataset:read"}, "dataset:read", True),
        ({"dataset:read"}, "dataset:write", False),
        ({"*"}, "anything:at:all", True),  # superuser
        (set(), "dataset:read", False),
        (["dataset:read", "credit_risk:execute"], "credit_risk:execute", True),
    ],
)
def test_has_permission(perms, perm, expected):
    assert has_permission(perms, perm) is expected


def test_normalize_drops_invalid_and_sorts():
    assert normalize_permissions(
        ["dataset:write", "bad:perm", "dataset:read", "dataset:read"]
    ) == [
        "dataset:read",
        "dataset:write",
    ]


def test_catalog_payload_shape():
    payload = catalog_payload()
    pages = {p["key"] for p in payload["pages"]}
    assert {"dataset", "credit_risk", "user", "role", "auditlog"} <= pages
    evaluation = next(p for p in payload["pages"] if p["key"] == "evaluation")
    assert [a["key"] for a in evaluation["actions"]] == ["read"]
    assert "credit_risk:execute" in ALL_PERMISSIONS
