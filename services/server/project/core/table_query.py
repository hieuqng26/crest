"""Shared filter/sort/paginate/distinct helpers for server-driven data tables.

Used by any endpoint backing a CommonDataTable instance (dataset row browser,
forecast/backtest prediction tables, credit-risk result tables, ...) so each
endpoint doesn't reimplement the same query logic. Operates on a pandas
DataFrame — callers convert their source (SQL rows, JSON blobs, parallel
arrays) into a DataFrame first.
"""

import json

import pandas as pd

DISTINCT_VALUES_LIMIT = 30

# Reserved filter key for a toolbar-level "search all columns" box, as opposed
# to a per-column filter (which uses the column's own field name as the key).
GLOBAL_SEARCH_KEY = "__search__"


def parse_filters(raw: str | None) -> dict[str, dict]:
    """Parse the `filters` query param: JSON `{field: {mode, value}}`.

    `mode` is `"contains"` (case-insensitive substring, `value` a string) or
    `"in"` (exact match against any of `value`, a list of strings). The
    reserved field `GLOBAL_SEARCH_KEY` matches against every column instead
    of one.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def apply_filters(df: pd.DataFrame, filters: dict[str, dict]) -> pd.DataFrame:
    for field, spec in filters.items():
        if not isinstance(spec, dict):
            continue
        value = spec.get("value")
        if value in (None, "", []):
            continue

        if field == GLOBAL_SEARCH_KEY:
            needle = str(value).lower()
            mask = df.apply(
                lambda row: (
                    row.astype(str).str.lower().str.contains(needle, na=False).any()
                ),
                axis=1,
            )
            df = df[mask]
            continue

        if field not in df.columns:
            continue
        mode = spec.get("mode")
        col = df[field].astype(str)
        if mode == "in":
            values = value if isinstance(value, list) else [value]
            df = df[col.isin([str(v) for v in values])]
        else:
            df = df[col.str.contains(str(value), case=False, na=False, regex=False)]
    return df


def apply_sort(
    df: pd.DataFrame, sort_column: str | None, sort_order: str | None
) -> pd.DataFrame:
    if sort_column and sort_column in df.columns:
        df = df.sort_values(
            sort_column, ascending=(sort_order != "desc"), kind="stable"
        )
    return df


def paginate(df: pd.DataFrame, page: int, page_size: int) -> pd.DataFrame:
    page = max(0, page)
    page_size = min(500, max(1, page_size))
    offset = page * page_size
    return df.iloc[offset : offset + page_size]


def query_page(
    df: pd.DataFrame,
    *,
    page: int = 0,
    page_size: int = 50,
    sort_column: str | None = None,
    sort_order: str | None = None,
    filters: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, int]:
    """Filter, sort, and paginate a DataFrame. Returns (page_df, total_after_filter)."""
    df = apply_filters(df, filters or {})
    total = len(df)
    df = apply_sort(df, sort_column, sort_order)
    df = paginate(df, page, page_size)
    return df, total


def distinct_values(
    df: pd.DataFrame, column: str, limit: int = DISTINCT_VALUES_LIMIT
) -> dict:
    """Distinct values for a column, capped at `limit`.

    `truncated=True` tells the frontend there are more unique values than the
    cap — it should fall back to a text filter instead of a dropdown.
    """
    if column not in df.columns:
        return {"values": [], "truncated": False}
    uniques = df[column].dropna().astype(str).unique().tolist()
    uniques.sort()
    truncated = len(uniques) > limit
    return {"values": uniques[:limit], "truncated": truncated}
