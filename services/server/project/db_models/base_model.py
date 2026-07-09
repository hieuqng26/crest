from datetime import datetime

from project import db


class SerializerMixin:
    """Default column-based ``to_dict`` for ORM models.

    Dumps every mapped column, ISO-formatting ``datetime`` values and honouring
    ``__serialize_exclude__``. Models whose serialised shape is a plain column
    dump can inherit this and drop their hand-written ``to_dict``; models that
    rename columns, add computed/joined fields, or use a non-ISO datetime format
    keep their own ``to_dict`` (which may still call :meth:`column_dict`).
    """

    #: Column names to omit from the serialised dict (e.g. password hashes).
    __serialize_exclude__: tuple[str, ...] = ()

    def column_dict(self, exclude: tuple[str, ...] = ()) -> dict:
        skip = set(self.__serialize_exclude__) | set(exclude)
        out = {}
        for col in self.__table__.columns:
            if col.name in skip:
                continue
            value = getattr(self, col.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            out[col.name] = value
        return out

    def to_dict(self) -> dict:
        return self.column_dict()


class DBBaseModel(db.Model):
    """Abstract base for ORM models (thin marker; prefer ``SerializerMixin``
    for serialisation)."""

    __abstract__ = True
