"""Round 167: resource-safe data-source inspection.

Covers the metadata-only shape/schema (no rows loaded) and the sampled
preview/profile (never the full frame).
"""
from __future__ import annotations

import pandas as pd

from ai4bi.blocks import datastore
from ai4bi.blocks.contracts import (
    BlockType, CachedDataSource, ColumnSchema, DataBlockContract, InlineDataSource,
)
from ai4bi.ui import data_inspector as di


def _cached(df: pd.DataFrame, row_count: int | None = None) -> DataBlockContract:
    h = datastore.put_dataframe(df)
    return DataBlockContract(
        block_id="blk_cached", block_type=BlockType.fact, grain="row",
        columns=[ColumnSchema(name="city", data_type="string", nullable=True),
                 ColumnSchema(name="rev", data_type="integer", nullable=False)],
        data_source=CachedDataSource(content_hash=h,
                                     row_count=len(df) if row_count is None else row_count),
    )


def _inline(records: list[dict]) -> DataBlockContract:
    return DataBlockContract(
        block_id="blk_inline", block_type=BlockType.fact, grain="row",
        columns=[ColumnSchema(name="a", data_type="integer", nullable=True)],
        data_source=InlineDataSource(records=records),
    )


class TestMetadataOnly:
    def test_row_count_from_metadata_no_load(self):
        c = _cached(pd.DataFrame({"city": ["A", "B"], "rev": [1, 2]}), row_count=999_999)
        # uses the declared row_count, not len of stored frame → no scan
        assert datastore.source_row_count(c) == 999_999

    def test_row_count_inline(self):
        assert datastore.source_row_count(_inline([{"a": 1}, {"a": 2}, {"a": 3}])) == 3

    def test_shape_is_metadata_only(self):
        c = _cached(pd.DataFrame({"city": ["A"], "rev": [1]}), row_count=80_000)
        shape = di.source_shape(c)
        assert shape.n_cols == 2
        assert shape.row_count == 80_000
        assert shape.cost_tier == "large" and shape.is_large

    def test_classify_cost_tiers(self):
        assert di.classify_cost(10)[0] == "small"
        assert di.classify_cost(2_000)[0] == "medium"
        assert di.classify_cost(99_999)[0] == "large"
        assert di.classify_cost(None)[0] == "unknown"


class TestSchema:
    def test_schema_rows_types_and_nullable(self):
        c = _cached(pd.DataFrame({"city": ["A"], "rev": [1]}))
        rows = di.schema_rows(c)
        assert [r["欄位"] for r in rows] == ["city", "rev"]
        assert "文字" in rows[0]["型態"] and rows[0]["可空"] == "是"
        assert "整數" in rows[1]["型態"] and rows[1]["可空"] == "否"


class TestSampledPreview:
    def test_sample_caps_rows(self):
        df = pd.DataFrame({"city": list("ABCDEFGHIJ"), "rev": range(10)})
        c = _cached(df)
        assert len(datastore.sample_dataframe(c, 3)) == 3

    def test_inline_sample_does_not_build_full_frame(self):
        # 100k records but we only ask for 5 → only 5 rows are realized
        big = [{"a": i} for i in range(100_000)]
        c = _inline(big)
        sample = datastore.sample_dataframe(c, 5)
        assert len(sample) == 5

    def test_profile_runs_on_sample_only(self):
        df = pd.DataFrame({"city": ["A", "B", "A", None], "rev": [10, 20, 30, 40]})
        prof = {p["欄位"]: p for p in di.profile_sample(df)}
        assert prof["city"]["非空率"].startswith("75%")
        assert "⚠️" in prof["city"]["非空率"]  # low completeness flagged
        assert prof["city"]["種類數"] == 2
        # most-common value + count for categorical (A appears twice)
        assert prof["city"]["最常見"].startswith("A（2")
        assert prof["rev"]["最小"] == 10.0 and prof["rev"]["最大"] == 40.0
        assert prof["rev"]["非空率"] == "100%"  # full → no warning mark

    def test_profile_empty_is_safe(self):
        assert di.profile_sample(pd.DataFrame()) == []
