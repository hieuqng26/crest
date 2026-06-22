from project.api.roles import registry
from project.api.roles.defaults import SYSADMIN_ROLE
from project.api.roles.models import RoleModel


def test_default_roles_seeded(app):
    names = {r.name for r in RoleModel.query.all()}
    assert {"viewer", "analyst", SYSADMIN_ROLE} <= names


def test_sysadmin_is_protected_superuser(app):
    sysadmin = RoleModel.query.filter_by(name=SYSADMIN_ROLE).first()
    assert sysadmin.is_system is True
    assert sysadmin.permissions == ["*"]


def test_registry_resolves_permissions(app):
    assert "dataset:write" in registry.permissions_for("analyst")
    assert registry.permissions_for("viewer") == {
        "dataset:read",
        "model_config:read",
        "calibration:read",
        "forecast:read",
        "evaluation:read",
        "credit_risk:read",
    }
    assert registry.permissions_for("nonexistent") == set()


def test_registry_invalidate_picks_up_edits(app):
    from project import db

    role = RoleModel.query.filter_by(name="viewer").first()
    role.permissions = ["dataset:read", "dataset:write"]
    db.session.commit()
    registry.invalidate()
    assert "dataset:write" in registry.permissions_for("viewer")
