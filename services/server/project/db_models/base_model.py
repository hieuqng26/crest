from project import db


class DBBaseModel(db.Model):
    """Abstract base for ORM models.

    Currently a thin marker; Phase 10 adds a shared ``to_dict()`` serializer
    here to replace the per-model hand-written versions.
    """

    __abstract__ = True
