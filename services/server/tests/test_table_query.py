"""Unit tests for the shared server-table filter/sort/paginate/distinct helper.

Pure pandas — no Flask app context required.
Run from services/server/: pytest tests/test_table_query.py -v
"""

import pandas as pd
import pytest

from project.core import table_query


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "name": ["alice", "bob", "carol", "dave", "erin"],
            "country": ["US", "US", "UK", "UK", "DE"],
            "score": [5, 3, 4, 1, 2],
        }
    )


class TestParseFilters:
    def test_none_or_empty_returns_empty_dict(self):
        assert table_query.parse_filters(None) == {}
        assert table_query.parse_filters("") == {}

    def test_invalid_json_returns_empty_dict(self):
        assert table_query.parse_filters("{not json") == {}

    def test_non_dict_json_returns_empty_dict(self):
        assert table_query.parse_filters("[1, 2, 3]") == {}

    def test_valid_json_roundtrips(self):
        raw = '{"country": {"mode": "in", "value": ["US"]}}'
        assert table_query.parse_filters(raw) == {
            "country": {"mode": "in", "value": ["US"]}
        }


class TestApplyFilters:
    def test_contains_is_case_insensitive_substring(self, df):
        out = table_query.apply_filters(
            df, {"name": {"mode": "contains", "value": "A"}}
        )
        assert sorted(out["name"]) == ["alice", "carol", "dave"]

    def test_in_matches_any_listed_value(self, df):
        out = table_query.apply_filters(
            df, {"country": {"mode": "in", "value": ["UK", "DE"]}}
        )
        assert sorted(out["name"]) == ["carol", "dave", "erin"]

    def test_unknown_column_is_ignored(self, df):
        out = table_query.apply_filters(
            df, {"nope": {"mode": "contains", "value": "x"}}
        )
        assert len(out) == len(df)

    def test_empty_value_is_ignored(self, df):
        out = table_query.apply_filters(df, {"name": {"mode": "contains", "value": ""}})
        assert len(out) == len(df)
        out = table_query.apply_filters(df, {"country": {"mode": "in", "value": []}})
        assert len(out) == len(df)


class TestApplySort:
    def test_ascending_by_default(self, df):
        out = table_query.apply_sort(df, "score", None)
        assert out["score"].tolist() == [1, 2, 3, 4, 5]

    def test_descending(self, df):
        out = table_query.apply_sort(df, "score", "desc")
        assert out["score"].tolist() == [5, 4, 3, 2, 1]

    def test_unknown_column_is_noop(self, df):
        out = table_query.apply_sort(df, "nope", "asc")
        assert out["score"].tolist() == df["score"].tolist()


class TestPaginate:
    def test_slices_by_page_and_size(self, df):
        out = table_query.paginate(df, page=1, page_size=2)
        assert out["name"].tolist() == ["carol", "dave"]

    def test_negative_page_clamped_to_zero(self, df):
        out = table_query.paginate(df, page=-5, page_size=2)
        assert out["name"].tolist() == ["alice", "bob"]

    def test_page_size_capped_at_500(self, df):
        out = table_query.paginate(df, page=0, page_size=10_000)
        assert len(out) == len(df)


class TestQueryPage:
    def test_filters_then_sorts_then_paginates(self, df):
        page, total = table_query.query_page(
            df,
            page=0,
            page_size=2,
            sort_column="score",
            sort_order="desc",
            filters={"country": {"mode": "in", "value": ["US", "UK"]}},
        )
        # US+UK rows: alice(5), bob(3), carol(4), dave(1) -> sorted desc: alice, carol, bob, dave
        assert total == 4
        assert page["name"].tolist() == ["alice", "carol"]

    def test_no_filters_or_sort_returns_first_page(self, df):
        page, total = table_query.query_page(df, page=0, page_size=3)
        assert total == 5
        assert len(page) == 3


class TestDistinctValues:
    def test_returns_sorted_unique_values_under_limit(self, df):
        result = table_query.distinct_values(df, "country", limit=30)
        assert result == {"values": ["DE", "UK", "US"], "truncated": False}

    def test_truncates_when_over_limit(self, df):
        result = table_query.distinct_values(df, "name", limit=3)
        assert result["truncated"] is True
        assert len(result["values"]) == 3

    def test_unknown_column_returns_empty(self, df):
        assert table_query.distinct_values(df, "nope") == {
            "values": [],
            "truncated": False,
        }

    def test_drops_nulls(self):
        df = pd.DataFrame({"x": ["a", None, "b", None]})
        result = table_query.distinct_values(df, "x")
        assert result["values"] == ["a", "b"]
