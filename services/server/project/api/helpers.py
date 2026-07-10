"""Thin, transport-bound helpers shared across route modules.

These live in the ``api`` layer (they read ``flask.request`` and shape HTTP
responses) — deliberately *not* in ``services`` / ``core``. They remove the
copy-pasted pagination, table-query arg parsing, and get-or-404 blocks that
were duplicated across the domain route modules.
"""

from typing import Any

import pandas as pd
from flask import request
from pydantic import ValidationError

from project.core import table_query
from project.exceptions import NotFoundError


def validation_message(exc: ValidationError) -> str:
    """First pydantic error as a ``'<field>: <msg>'`` string.

    Used by the admin/auth endpoints that must keep the ``{"message": ...}``
    error shape their frontend views read (``response.data.message``), instead
    of letting the ValidationError reach the boundary's ``{"error": ...}`` form.
    """
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", ()))
    msg = first.get("msg", "Invalid request")
    return f"{loc}: {msg}" if loc else msg


def get_or_404(model, description: str = "Resource not found", **filters):
    """Fetch a single row by ``filters`` or raise ``NotFoundError`` (-> 404).

    Replaces the ubiquitous ``r = Model.query.filter_by(...).first();
    if not r: return jsonify({"error": ...}), 404`` block.
    """
    row = model.query.filter_by(**filters).first()
    if row is None:
        raise NotFoundError(description)
    return row


def pagination_envelope(items: list, paged) -> dict[str, Any]:
    """Standard ORM list envelope for a Flask-SQLAlchemy ``paginate()`` result.

    ``items`` is the (possibly enriched) serialised page; ``paged`` is the
    pagination object. Shape matches the pre-refactor hand-built dict exactly.
    """
    return {
        "items": items,
        "total": paged.total,
        "page": paged.page,
        "pages": paged.pages,
    }


def table_query_args() -> dict[str, Any]:
    """Parse the CommonDataTable query params into ``table_query.query_page`` kwargs.

    Mirrors the 0-based ``page`` / ``page_size`` / ``sort_column`` /
    ``sort_order`` / ``filters`` (JSON) convention used by every backtest-table
    endpoint.
    """
    return {
        "page": request.args.get("page", 0, type=int),
        "page_size": request.args.get("page_size", 50, type=int),
        "sort_column": request.args.get("sort_column"),
        "sort_order": request.args.get("sort_order"),
        "filters": table_query.parse_filters(request.args.get("filters")),
    }


def dataframe_page_response(
    df: pd.DataFrame, *, include_columns: bool = True
) -> dict[str, Any]:
    """Filter/sort/paginate ``df`` per the request and shape the table payload."""
    page_df, total = table_query.query_page(df, **table_query_args())
    # NaN is not valid JSON — coerce to null, matching the pre-refactor
    # `.where(pd.notnull(...), None)` the table endpoints applied by hand.
    rows = page_df.where(pd.notnull(page_df), None).to_dict(orient="records")
    payload: dict[str, Any] = {"rows": rows, "total": total}
    if include_columns:
        payload["columns"] = list(df.columns)
    return payload


def dataframe_distinct_response(df: pd.DataFrame, column: str) -> dict[str, Any]:
    """Distinct values for one column, for a table's filter dropdown."""
    return table_query.distinct_values(df, column)
