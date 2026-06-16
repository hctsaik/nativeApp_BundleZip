"""
R1 Sprint P0 — baseline contract tests.
Round 007 — VisualQuerySpec BlockRef migration tests added.

Verified baseline numbers (from tests/fixtures/baseline.json):
  total_revenue  = 423_000
  North          = 175_100
  South          = 154_800
  East           =  93_100   (adjusted from spec; spec N+S+E=424000 ≠ 423000)
  2024-01        = 125_500
  2024-02        = 135_100
  2024-03        = 162_400
  Electronics    = 358_000
  Apparel        =  51_800
  Food           =   7_200
  rows           = 22  (20 with revenue, 2 null-revenue orphans)
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from ai4bi.blocks.contracts import (
    BlockType,
    DataBlockContract,
    FanoutRisk,
    InlineDataSource,
    MetricDefinition,
    PolicySpec,
    RelationshipHint,
)
from ai4bi.blocks.loader import BlockLoader
from ai4bi.planning.fanout_guard import FanoutGuard, FanoutGuardError, FanoutWarning
from ai4bi.query_spec import (
    BlockRef,
    FilterOperator,
    FilterSpec,
    MetricRef,
    VisualQuerySpec,
    VisualType,
    VisualizationSpec,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SALES_FACT_JSON = FIXTURES_DIR / "blocks" / "sales_fact.json"
BASELINE_JSON = FIXTURES_DIR / "baseline.json"

with open(BASELINE_JSON) as _f:
    BASELINE = json.load(_f)

TOTAL_REVENUE: float = BASELINE["total_revenue"]  # 423_000
ROW_COUNT: int = BASELINE["row_count"]            # 22


# ---------------------------------------------------------------------------
# Helper: minimal valid contract dict
# ---------------------------------------------------------------------------

def _minimal_contract(**overrides) -> dict:
    """Return a minimal valid DataBlockContract payload, with optional overrides."""
    base = {
        "block_id": "test_block",
        "block_type": "fact",
        "grain": "order_id",
        "version": "1.0.0",
        "data_source": {"source_type": "inline", "records": []},
    }
    base.update(overrides)
    return base


# ===========================================================================
# Test 1: Valid JSON fixture passes Pydantic validation
# ===========================================================================

class TestContractValidation:
    def test_sales_fact_json_passes_validation(self):
        """Loading the full sales_fact.json fixture must not raise."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        assert contract.block_id == "sales_fact"
        assert contract.block_type == BlockType.fact
        assert contract.grain == "order_id"
        assert contract.version == "1.0.0"
        assert isinstance(contract.data_source, InlineDataSource)
        assert len(contract.data_source.records) == ROW_COUNT

    def test_minimal_contract_passes_validation(self):
        """A minimal dict with only required fields must validate successfully."""
        contract = DataBlockContract.model_validate(_minimal_contract())
        assert contract.block_id == "test_block"
        assert contract.metrics == []
        assert contract.relationships == []

    # -----------------------------------------------------------------------
    # Test 2: Missing grain → ValidationError
    # -----------------------------------------------------------------------

    def test_missing_grain_raises_validation_error(self):
        """Omitting 'grain' must raise a Pydantic ValidationError."""
        payload = _minimal_contract()
        del payload["grain"]

        with pytest.raises(ValidationError) as exc_info:
            DataBlockContract.model_validate(payload)

        # Confirm error mentions 'grain'
        errors = exc_info.value.errors()
        field_names = {loc for e in errors for loc in e["loc"]}
        assert "grain" in field_names

    def test_blank_grain_raises_validation_error(self):
        """A whitespace-only grain string must be rejected by the validator."""
        payload = _minimal_contract(grain="   ")

        with pytest.raises(ValidationError) as exc_info:
            DataBlockContract.model_validate(payload)

        error_msgs = " ".join(str(e["msg"]) for e in exc_info.value.errors())
        assert "grain" in error_msgs.lower() or "non-empty" in error_msgs.lower()

    # -----------------------------------------------------------------------
    # Test 3: Duplicate metric names → ValidationError
    # -----------------------------------------------------------------------

    def test_duplicate_metric_names_raise_validation_error(self):
        """Two metrics with the same name in one block must raise ValidationError."""
        payload = _minimal_contract(
            metrics=[
                {"name": "revenue", "formula": "SUM(revenue)"},
                {"name": "revenue", "formula": "SUM(revenue) * 2"},  # duplicate
            ]
        )

        with pytest.raises(ValidationError) as exc_info:
            DataBlockContract.model_validate(payload)

        error_msgs = " ".join(str(e["msg"]) for e in exc_info.value.errors())
        assert "revenue" in error_msgs

    def test_unique_metric_names_pass_validation(self):
        """Two metrics with distinct names must validate successfully."""
        payload = _minimal_contract(
            metrics=[
                {"name": "revenue", "formula": "SUM(revenue)"},
                {"name": "gross_profit", "formula": "SUM(revenue - cost)"},
            ]
        )
        contract = DataBlockContract.model_validate(payload)
        assert len(contract.metrics) == 2

    # -----------------------------------------------------------------------
    # Test 4: Invalid semver → ValidationError
    # -----------------------------------------------------------------------

    def test_invalid_semver_raises_validation_error(self):
        """A version string that is not MAJOR.MINOR.PATCH must be rejected."""
        payload = _minimal_contract(version="not-semver")

        with pytest.raises(ValidationError):
            DataBlockContract.model_validate(payload)


# ===========================================================================
# Test 5: FanoutGuard — BLOCKED raises FanoutGuardError
# ===========================================================================

class TestFanoutGuard:
    def _make_rel(self, risk: FanoutRisk, target: str = "target_block") -> RelationshipHint:
        return RelationshipHint(
            target_block_id=target,
            allowed_join_keys=["id"],
            fanout_risk=risk,
        )

    def test_blocked_relationship_raises_fanout_guard_error(self):
        """A BLOCKED fanout_risk must raise FanoutGuardError before the query runs."""
        rels = [
            self._make_rel(FanoutRisk.LOW, "dim_a"),
            self._make_rel(FanoutRisk.BLOCKED, "dangerous_dim"),
        ]

        with pytest.raises(FanoutGuardError) as exc_info:
            FanoutGuard.check(rels)

        assert exc_info.value.relationship.target_block_id == "dangerous_dim"
        assert "BLOCKED" in str(exc_info.value)

    def test_high_risk_issues_warning_does_not_raise(self):
        """A HIGH fanout_risk must emit a FanoutWarning but not raise."""
        rels = [self._make_rel(FanoutRisk.HIGH, "risky_dim")]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = FanoutGuard.check(rels)

        fanout_warnings = [w for w in caught if issubclass(w.category, FanoutWarning)]
        assert len(fanout_warnings) == 1
        assert result.high_risk_relationships[0].target_block_id == "risky_dim"

    def test_low_risk_passes_silently(self):
        """LOW fanout_risk must return a result with no warnings."""
        rels = [self._make_rel(FanoutRisk.LOW, "safe_dim")]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = FanoutGuard.check(rels)

        assert not result.has_warnings
        fanout_warnings = [w for w in caught if issubclass(w.category, FanoutWarning)]
        assert len(fanout_warnings) == 0

    def test_empty_relationships_passes(self):
        """An empty relationship list must pass without error."""
        result = FanoutGuard.check([])
        assert not result.has_warnings

    def test_first_blocked_stops_evaluation(self):
        """FanoutGuardError is raised on the first BLOCKED relationship encountered."""
        rels = [
            self._make_rel(FanoutRisk.BLOCKED, "blocked_first"),
            self._make_rel(FanoutRisk.BLOCKED, "blocked_second"),
        ]

        with pytest.raises(FanoutGuardError) as exc_info:
            FanoutGuard.check(rels)

        # Only the first BLOCKED rel is reported
        assert exc_info.value.relationship.target_block_id == "blocked_first"


# ===========================================================================
# Test 6: Inline loader → Arrow table row count matches
# ===========================================================================

class TestBlockLoader:
    def test_to_arrow_row_count_matches_fixture(self):
        """Arrow table produced from InlineDataSource must have exactly 22 rows."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))
        table = loader.to_arrow(contract)

        assert table.num_rows == ROW_COUNT  # 22

    def test_to_arrow_contains_expected_columns(self):
        """Arrow table must include all columns declared in the fixture."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))
        table = loader.to_arrow(contract)

        declared_columns = {col.name for col in contract.columns}
        arrow_columns = set(table.schema.names)
        assert declared_columns.issubset(arrow_columns)

    def test_to_arrow_raises_on_non_inline_source(self):
        """to_arrow() on an ExternalDataSource must raise TypeError."""
        payload = _minimal_contract(
            data_source={
                "source_type": "execution_ref",
                "query": "SELECT 1",
                "connection_id": "prod",
            }
        )
        contract = DataBlockContract.model_validate(payload)
        loader = BlockLoader()

        with pytest.raises(TypeError, match="ExternalDataSource"):
            loader.to_arrow(contract)

    # -----------------------------------------------------------------------
    # Test 7: DuckDB query SUM(revenue) == expected total
    # -----------------------------------------------------------------------

    def test_duckdb_sum_revenue_equals_baseline(self):
        """SUM(revenue) queried through DuckDB must equal the baseline total of 423,000."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        conn = duckdb.connect(database=":memory:")
        loader.register_to_duckdb(contract, "sales_fact", conn)

        result = conn.execute("SELECT SUM(revenue) AS total_revenue FROM sales_fact").fetchone()
        conn.close()

        total = result[0]
        assert total == pytest.approx(TOTAL_REVENUE, rel=1e-6), (
            f"Expected SUM(revenue)={TOTAL_REVENUE}, got {total}"
        )

    def test_duckdb_region_revenue_breakdown(self):
        """Regional revenue breakdown must match baseline values for North, South, East."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        conn = duckdb.connect(database=":memory:")
        loader.register_to_duckdb(contract, "sales_fact", conn)

        rows = conn.execute(
            "SELECT region, SUM(revenue) AS rev "
            "FROM sales_fact WHERE region IS NOT NULL "
            "GROUP BY region ORDER BY region"
        ).fetchall()
        conn.close()

        by_region = {row[0]: row[1] for row in rows}
        expected = BASELINE["by_region"]

        for region, expected_rev in expected.items():
            assert by_region.get(region) == pytest.approx(expected_rev, rel=1e-6), (
                f"Region {region}: expected {expected_rev}, got {by_region.get(region)}"
            )

    def test_duckdb_monthly_revenue_breakdown(self):
        """Monthly revenue totals must match the baseline Jan/Feb/Mar values."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        conn = duckdb.connect(database=":memory:")
        loader.register_to_duckdb(contract, "sales_fact", conn)

        rows = conn.execute(
            "SELECT strftime(CAST(order_date AS DATE), '%Y-%m') AS month, "
            "SUM(revenue) AS rev "
            "FROM sales_fact WHERE revenue IS NOT NULL "
            "GROUP BY month ORDER BY month"
        ).fetchall()
        conn.close()

        by_month = {row[0]: row[1] for row in rows}
        expected = BASELINE["by_month"]

        for month, expected_rev in expected.items():
            assert by_month.get(month) == pytest.approx(expected_rev, rel=1e-6), (
                f"Month {month}: expected {expected_rev}, got {by_month.get(month)}"
            )

    def test_duckdb_category_revenue_breakdown(self):
        """Category revenue totals must match baseline Electronics/Apparel/Food values."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        conn = duckdb.connect(database=":memory:")
        loader.register_to_duckdb(contract, "sales_fact", conn)

        rows = conn.execute(
            "SELECT category, SUM(revenue) AS rev "
            "FROM sales_fact WHERE category IS NOT NULL "
            "GROUP BY category ORDER BY category"
        ).fetchall()
        conn.close()

        by_cat = {row[0]: row[1] for row in rows}
        expected = BASELINE["by_category"]

        for cat, expected_rev in expected.items():
            assert by_cat.get(cat) == pytest.approx(expected_rev, rel=1e-6), (
                f"Category {cat}: expected {expected_rev}, got {by_cat.get(cat)}"
            )

    def test_duckdb_null_revenue_row_count(self):
        """Exactly 2 rows must have NULL revenue (orphan rows O012 and O022)."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        conn = duckdb.connect(database=":memory:")
        loader.register_to_duckdb(contract, "sales_fact", conn)

        result = conn.execute(
            "SELECT COUNT(*) FROM sales_fact WHERE revenue IS NULL"
        ).fetchone()
        conn.close()

        assert result[0] == BASELINE["null_revenue_rows"]  # 2

    def test_duckdb_total_row_count(self):
        """The registered table must have exactly 22 rows."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        conn = duckdb.connect(database=":memory:")
        loader.register_to_duckdb(contract, "sales_fact", conn)

        result = conn.execute("SELECT COUNT(*) FROM sales_fact").fetchone()
        conn.close()

        assert result[0] == ROW_COUNT  # 22


# ===========================================================================
# Test: PolicySpec and RelationshipHint fields
# ===========================================================================

class TestPolicyAndRelationships:
    def test_sales_fact_policy_is_internal(self):
        """The sales_fact fixture policy must be data_classification=INTERNAL."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        assert contract.policy.data_classification.value == "internal"
        assert "analyst" in contract.policy.allowed_roles

    def test_sales_fact_has_product_dim_relationship(self):
        """The sales_fact fixture must declare exactly one relationship to product_dim."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        assert len(contract.relationships) == 1
        rel = contract.relationships[0]
        assert rel.target_block_id == "product_dim"
        assert rel.fanout_risk == FanoutRisk.LOW
        assert "product_id" in rel.allowed_join_keys

    def test_sales_fact_fanout_guard_passes(self):
        """FanoutGuard.check on the sales_fact relationships must complete without error."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        # Should not raise; LOW risk passes silently
        result = FanoutGuard.check(contract.relationships)
        assert not result.has_warnings


# ===========================================================================
# Test: Metric definitions
# ===========================================================================

class TestMetricDefinitions:
    def test_sales_fact_has_two_metrics(self):
        """The sales_fact fixture must define exactly two metrics."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        assert len(contract.metrics) == 2
        metric_names = {m.name for m in contract.metrics}
        assert "revenue" in metric_names
        assert "gross_profit" in metric_names

    def test_revenue_metric_formula(self):
        """The revenue metric formula must be 'SUM(revenue)'."""
        loader = BlockLoader()
        contract = loader.load_json(str(SALES_FACT_JSON))

        revenue_metric = next(m for m in contract.metrics if m.name == "revenue")
        assert revenue_metric.formula == "SUM(revenue)"
        assert revenue_metric.unit == "USD"


# ===========================================================================
# Round 007: BlockRef migration tests — VisualQuerySpec.block_refs
# ===========================================================================

class TestBlockRefMigration:
    """
    Verifies that VisualQuerySpec now uses block_refs: list[BlockRef]
    instead of the deprecated block_ids: list[str].

    These tests document the migration contract so that future refactors
    cannot silently revert to the old API.
    """

    # -----------------------------------------------------------------------
    # BlockRef construction and validation
    # -----------------------------------------------------------------------

    def test_block_ref_unpinned(self):
        """An unpinned BlockRef must have is_pinned=False and pinned_version=None."""
        ref = BlockRef(block_id="sales_fact")
        assert ref.block_id == "sales_fact"
        assert ref.pinned_version is None
        assert ref.pin_reason is None
        assert ref.pinned_at is None
        assert ref.is_pinned is False

    def test_block_ref_pinned(self):
        """A pinned BlockRef must expose is_pinned=True and validate semver."""
        ts = datetime(2024, 1, 15, 9, 0, 0)
        ref = BlockRef(
            block_id="sales_fact",
            pinned_version="1.2.0",
            pin_reason="Q1 board deck freeze",
            pinned_at=ts,
        )
        assert ref.is_pinned is True
        assert ref.pinned_version == "1.2.0"
        assert ref.pin_reason == "Q1 board deck freeze"
        assert ref.pinned_at == ts

    def test_block_ref_invalid_semver_raises(self):
        """A non-semver pinned_version must raise ValueError."""
        with pytest.raises(ValueError, match="semver"):
            BlockRef(block_id="sales_fact", pinned_version="not-a-version")

    def test_block_ref_empty_block_id_raises(self):
        """An empty block_id must raise ValueError."""
        with pytest.raises(ValueError):
            BlockRef(block_id="")

    # -----------------------------------------------------------------------
    # VisualQuerySpec uses block_refs (not block_ids)
    # -----------------------------------------------------------------------

    def test_visual_query_spec_uses_block_refs(self):
        """VisualQuerySpec must expose block_refs, not block_ids."""
        spec = VisualQuerySpec(
            spec_id="test_kpi",
            block_refs=[BlockRef(block_id="sales_fact")],
            metrics=[MetricRef(block_id="sales_fact", metric_name="revenue")],
        )
        assert hasattr(spec, "block_refs"), "block_refs attribute must exist"
        assert not hasattr(spec, "block_ids"), (
            "block_ids must NOT exist — use block_refs (Round 007 migration)"
        )
        assert len(spec.block_refs) == 1
        assert spec.block_refs[0].block_id == "sales_fact"

    def test_visual_query_spec_primary_block_id(self):
        """primary_block_id property must return the first block_ref's block_id."""
        spec = VisualQuerySpec(
            spec_id="test_kpi",
            block_refs=[
                BlockRef(block_id="sales_fact"),
                BlockRef(block_id="product_dim"),
            ],
        )
        assert spec.primary_block_id == "sales_fact"

    def test_visual_query_spec_all_block_ids(self):
        """all_block_ids must return all block IDs in order."""
        refs = [BlockRef(block_id="sales_fact"), BlockRef(block_id="product_dim")]
        spec = VisualQuerySpec(spec_id="multi_block", block_refs=refs)
        assert spec.all_block_ids == ["sales_fact", "product_dim"]

    def test_visual_query_spec_empty_block_refs_raises(self):
        """VisualQuerySpec with an empty block_refs list must raise ValueError."""
        with pytest.raises(ValueError, match="block_refs"):
            VisualQuerySpec(spec_id="bad_spec", block_refs=[])

    # -----------------------------------------------------------------------
    # Cache key stability
    # -----------------------------------------------------------------------

    def test_cache_key_stable_across_identical_specs(self):
        """Two identical VisualQuerySpecs must produce the same cache key."""
        make_spec = lambda: VisualQuerySpec(
            spec_id="kpi",
            block_refs=[BlockRef(block_id="sales_fact", pinned_version="1.0.0")],
            metrics=[MetricRef(block_id="sales_fact", metric_name="revenue")],
            data_version="v1",
        )
        assert make_spec().cache_key() == make_spec().cache_key()

    def test_cache_key_differs_when_pinned_version_changes(self):
        """Changing pinned_version must produce a different cache key."""
        spec_v1 = VisualQuerySpec(
            spec_id="kpi",
            block_refs=[BlockRef(block_id="sales_fact", pinned_version="1.0.0")],
            data_version="v1",
        )
        spec_v2 = VisualQuerySpec(
            spec_id="kpi",
            block_refs=[BlockRef(block_id="sales_fact", pinned_version="1.2.0")],
            data_version="v1",
        )
        assert spec_v1.cache_key() != spec_v2.cache_key()

    def test_cache_key_ignores_pinned_at_timestamp(self):
        """
        pinned_at is an audit field; repinning the same version must NOT
        change the cache key (avoids unnecessary cache busting).
        """
        spec_ts1 = VisualQuerySpec(
            spec_id="kpi",
            block_refs=[
                BlockRef(
                    block_id="sales_fact",
                    pinned_version="1.0.0",
                    pinned_at=datetime(2024, 1, 1),
                )
            ],
            data_version="v1",
        )
        spec_ts2 = VisualQuerySpec(
            spec_id="kpi",
            block_refs=[
                BlockRef(
                    block_id="sales_fact",
                    pinned_version="1.0.0",
                    pinned_at=datetime(2024, 6, 1),   # different timestamp
                )
            ],
            data_version="v1",
        )
        assert spec_ts1.cache_key() == spec_ts2.cache_key()

    def test_cache_key_differs_on_data_version_bump(self):
        """Bumping data_version must produce a different cache key."""
        ref = BlockRef(block_id="sales_fact")
        spec_v1 = VisualQuerySpec(spec_id="kpi", block_refs=[ref], data_version="v1")
        spec_v2 = VisualQuerySpec(spec_id="kpi", block_refs=[ref], data_version="v2")
        assert spec_v1.cache_key() != spec_v2.cache_key()

    # -----------------------------------------------------------------------
    # Fixture JSON uses block_refs format
    # -----------------------------------------------------------------------

    def test_visual_fixture_uses_block_refs(self):
        """The sales_kpi_spec.json fixture must use block_refs, not block_ids."""
        fixture_path = (
            Path(__file__).parent / "fixtures" / "visuals" / "sales_kpi_spec.json"
        )
        assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))

        assert "block_refs" in data, (
            "Fixture must use 'block_refs' (Round 007 migration); "
            "'block_ids' is no longer accepted."
        )
        assert "block_ids" not in data, (
            "'block_ids' field must not appear in Round 007+ fixtures"
        )
        assert isinstance(data["block_refs"], list)
        assert len(data["block_refs"]) >= 1
        first_ref = data["block_refs"][0]
        assert "block_id" in first_ref
        assert first_ref["block_id"] == "sales_fact"

    def test_visual_fixture_block_ref_has_correct_shape(self):
        """Each block_ref in the fixture must have block_id, pinned_version, pin_reason, pinned_at."""
        fixture_path = (
            Path(__file__).parent / "fixtures" / "visuals" / "sales_kpi_spec.json"
        )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        ref = data["block_refs"][0]

        expected_keys = {"block_id", "pinned_version", "pin_reason", "pinned_at"}
        assert expected_keys.issubset(ref.keys()), (
            f"block_ref must contain all BlockRef fields. "
            f"Missing: {expected_keys - ref.keys()}"
        )

    # -----------------------------------------------------------------------
    # VisualizationSpec is separate from VisualQuerySpec
    # -----------------------------------------------------------------------

    def test_visualization_spec_decoupled_from_query_spec(self):
        """VisualizationSpec must be a separate dataclass from VisualQuerySpec."""
        query_spec = VisualQuerySpec(
            spec_id="kpi",
            block_refs=[BlockRef(block_id="sales_fact")],
        )
        style = VisualizationSpec(
            visual_type=VisualType.kpi_card,
            title="Revenue",
        )
        # They are distinct objects — coupling them at construction time is
        # intentionally NOT supported.
        assert type(query_spec) is not type(style)
        assert style.visual_type == VisualType.kpi_card
        assert query_spec.spec_id == "kpi"
