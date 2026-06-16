"""Execute governed visual query specifications against DataBlock JSON."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

from ai4bi.blocks.contracts import DataBlockContract, DisaggregationMethod
from ai4bi.blocks.loader import BlockLoader
from ai4bi.blocks.registry import BlockRegistryProtocol
from ai4bi.planning.join_planner import QueryPlanningError, ResolvedJoin, SafeJoinPlanner
from ai4bi.query_spec import (
    AggFunction,
    BlockRef,
    DimensionRef,
    FilterOperator,
    FilterSpec,
    HavingSpec,
    MetricRef,
    VisualQuerySpec,
)

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "blocks"


# ---------------------------------------------------------------------------
# ResultMetadata — spec section 7.4
# ---------------------------------------------------------------------------

@dataclass
class ResultMetadata:
    """Execution lineage returned alongside each query result.

    Satisfies spec 7.4 (ResultMetadata) and the "Explain before trust" principle.
    Stored in st.session_state["metadata_by_component"][component_id].
    """
    component_id: str
    row_count: int
    executed_at: str                          # ISO 8601 UTC
    blocks_used: list[str] = field(default_factory=list)
    relationships_used: list[str] = field(default_factory=list)  # "A → B (many_to_one)"
    metrics_used: list[dict] = field(default_factory=list)       # {name, formula, agg}
    dimensions_used: list[str] = field(default_factory=list)
    filters_applied: list[str] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)
    data_freshness: dict[str, str] = field(default_factory=dict)  # block_id → ISO timestamp
    sql_preview: str = ""                     # first 400 chars of generated SQL
_APPROVED_AGGREGATIONS = {
    DisaggregationMethod.sum: AggFunction.sum,
    DisaggregationMethod.average: AggFunction.avg,
    DisaggregationMethod.count: AggFunction.count,
    DisaggregationMethod.count_distinct: AggFunction.count_distinct,
    DisaggregationMethod.min: AggFunction.min,
    DisaggregationMethod.max: AggFunction.max,
}


# ---------------------------------------------------------------------------
# Derived metric formula sandbox — Round 045
#
# A metric with disaggregation_method == none is a *derived* metric: its
# `formula` is an aggregate expression such as
#     SUM(revenue) / NULLIF(SUM(order_count), 0)
# We must never interpolate arbitrary SQL, so the formula is tokenised and
# every identifier is checked against an allow-list of functions/keywords or
# a known column of the primary block. Column references are re-qualified with
# the block prefix. Anything else (unknown identifier, statement terminator,
# comment) is rejected — this closes the SQL-injection vector flagged in the
# gap analysis while unlocking margin / conversion-rate / AOV metrics.
# ---------------------------------------------------------------------------

_FORMULA_ALLOWED_WORDS = frozenset({
    # aggregate / scalar functions
    "sum", "avg", "count", "min", "max", "count_distinct",
    "nullif", "coalesce", "abs", "round", "cast", "floor", "ceil",
    "percentile_cont", "percentile_disc", "stddev", "stddev_samp",
    "stddev_pop", "variance", "var_samp", "var_pop", "median", "greatest", "least",
    # control flow / clauses
    "case", "when", "then", "else", "end",
    "within", "group", "order", "by", "as", "distinct",
    "and", "or", "not", "is", "null", "between", "in",
    # cast target types
    "decimal", "double", "integer", "bigint", "float", "numeric", "real", "varchar",
})

_FORMULA_TOKEN_RE = re.compile(
    r"'[^']*'"                        # single-quoted string literal
    r"|@[A-Za-z_][A-Za-z0-9_]*"       # what-if parameter reference (Round 060)
    r"|\d+\.?\d*"                     # numeric literal
    r"|[A-Za-z_][A-Za-z0-9_]*"        # identifier / keyword
    r"|<=|>=|<>|!=|[-+*/%(),.<>=]"    # operators / punctuation
)

_FORMULA_FORBIDDEN = (";", "--", "/*", "*/")


def _build_derived_formula_expr(
    formula: str,
    primary_block_id: str,
    column_names: set[str],
    parameters: dict[str, float] | None = None,
) -> str:
    """Validate a derived-metric formula and return a safely-qualified expression.

    Round 060: ``@name`` tokens are what-if parameters; each is replaced by its
    current numeric value (a literal), so parameters can never inject SQL.

    Raises QueryPlanningError if the formula references an unknown identifier,
    an undefined parameter, or contains a disallowed sequence.
    """
    parameters = parameters or {}
    formula = (formula or "").strip()
    if not formula:
        raise QueryPlanningError("Derived metric has an empty formula.")
    for bad in _FORMULA_FORBIDDEN:
        if bad in formula:
            raise QueryPlanningError(
                f"Derived metric formula contains a disallowed sequence: {bad!r}"
            )
    column_lower = {name.lower(): name for name in column_names}
    out: list[str] = []
    pos = 0
    for match in _FORMULA_TOKEN_RE.finditer(formula):
        gap = formula[pos:match.start()]
        if gap.strip():
            raise QueryPlanningError(
                f"Unexpected characters in derived formula: {gap.strip()!r}"
            )
        pos = match.end()
        tok = match.group(0)
        first = tok[0]
        if first == "@":
            name = tok[1:]
            if name not in parameters:
                raise QueryPlanningError(
                    f"Derived formula references undefined parameter '@{name}'."
                )
            out.append(repr(float(parameters[name])))  # inline as numeric literal
        elif first == "'" or first.isdigit():
            out.append(tok)                       # literal — safe as-is
        elif first.isalpha() or first == "_":
            low = tok.lower()
            if low in column_lower:
                out.append(_qualified(primary_block_id, column_lower[low]))
            elif low in _FORMULA_ALLOWED_WORDS:
                out.append(tok)
            else:
                raise QueryPlanningError(
                    f"Unknown identifier '{tok}' in derived metric formula "
                    f"(not a column of '{primary_block_id}' nor an allowed function)."
                )
        else:
            out.append(tok)                       # operator / punctuation
    trailing = formula[pos:]
    if trailing.strip():
        raise QueryPlanningError(
            f"Unexpected trailing characters in derived formula: {trailing.strip()!r}"
        )
    return " ".join(out)


def _quote(name: str) -> str:
    """Double quote a DuckDB identifier."""
    return f'"{name}"'


def _qualified(block_id: str, column_name: str) -> str:
    return f"{_quote(block_id)}.{_quote(column_name)}"


def _column_names(contract: DataBlockContract) -> set[str]:
    return {column.name for column in contract.columns}


def _require_column(
    contracts: dict[str, DataBlockContract],
    block_id: str,
    column_name: str,
) -> None:
    if block_id not in contracts or column_name not in _column_names(contracts[block_id]):
        raise QueryPlanningError(f"Unknown column '{block_id}.{column_name}'.")


def _build_filter_clause(spec: FilterSpec, params: list[Any]) -> str:
    col = _qualified(spec.block_id, spec.column_name)
    op = spec.operator
    val = spec.value

    if op == FilterOperator.eq:
        params.append(val)
        return f"{col} = ?"
    if op == FilterOperator.neq:
        params.append(val)
        return f"{col} != ?"
    if op == FilterOperator.gt:
        params.append(val)
        return f"{col} > ?"
    if op == FilterOperator.gte:
        params.append(val)
        return f"{col} >= ?"
    if op == FilterOperator.lt:
        params.append(val)
        return f"{col} < ?"
    if op == FilterOperator.lte:
        params.append(val)
        return f"{col} <= ?"
    if op == FilterOperator.in_:
        if not val:
            return "1=0"
        params.extend(val)
        return f"{col} IN ({', '.join(['?'] * len(val))})"
    if op == FilterOperator.not_in:
        if not val:
            return "1=1"
        params.extend(val)
        return f"{col} NOT IN ({', '.join(['?'] * len(val))})"
    if op == FilterOperator.between:
        params.extend([val[0], val[1]])
        return f"{col} BETWEEN ? AND ?"
    if op == FilterOperator.like:
        params.append(val)
        return f"{col} LIKE ?"
    if op == FilterOperator.is_null:
        return f"{col} IS NULL"
    if op == FilterOperator.is_not_null:
        return f"{col} IS NOT NULL"
    raise QueryPlanningError(f"Unsupported filter operator '{op}'.")


class Executor:
    """Compile and execute validated single-fact visual query specifications."""

    def __init__(
        self,
        registry_root: Optional[str | Path] = None,
        loader: Optional[BlockLoader] = None,
        semantic_model_path: Optional[str | Path] = None,
        registry: Optional[BlockRegistryProtocol] = None,
        extra_contracts: Optional[dict[str, "DataBlockContract"]] = None,
        parameters: Optional[dict[str, float]] = None,
        identity: Optional[dict[str, Any]] = None,
        extra_relationships: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self._registry_root = Path(registry_root) if registry_root else _DEFAULT_REGISTRY
        self._loader = loader or BlockLoader()
        self._registry = registry  # optional BlockRegistryProtocol for versioned resolution
        self._extra_contracts: dict[str, DataBlockContract] = extra_contracts or {}
        self._parameters: dict[str, float] = parameters or {}  # Round 060 what-if params
        self._identity: dict[str, Any] = identity or {}  # Round 103 row-level security
        # Round 032: cache Arrow tables so InlineDataSource records are not
        # re-serialised on every query within the same Executor instance
        self._arrow_cache: dict[str, Any] = {}
        inferred_model = self._registry_root.parent / "semantic_model.json"
        configured_model = Path(semantic_model_path) if semantic_model_path else inferred_model
        self._semantic_model = (
            json.loads(configured_model.read_text(encoding="utf-8"))
            if configured_model.exists()
            else None
        )
        # Round 183: merge user-defined relationships (built in the 🔗 關聯 UI) so
        # the CHART path — not only NL2 — can resolve joins on uploaded data. Skip
        # any (from,to) pair already certified in the file model: SafeJoinPlanner
        # requires EXACTLY ONE match, so a duplicate would break the demo's own join.
        if extra_relationships:
            base = dict(self._semantic_model) if self._semantic_model else {
                "relationships": [], "blocks": [], "metrics": [], "prohibited_paths": []}
            base_rels = list(base.get("relationships", []))
            certified_pairs = {
                (r.get("from_block"), r.get("to_block"))
                for r in base_rels if r.get("status") == "certified"}
            seen_ids = {r.get("relationship_id") for r in base_rels}
            for rel in extra_relationships:
                pair = (rel.get("from_block"), rel.get("to_block"))
                if pair in certified_pairs or rel.get("relationship_id") in seen_ids:
                    continue
                base_rels.append(rel)
            base["relationships"] = base_rels
            self._semantic_model = base
        self._planner = SafeJoinPlanner(self._semantic_model)

    def _resolve_block_path(self, ref: BlockRef) -> Path:
        """
        Resolve a BlockRef to a filesystem Path.

        Backward-compatible: if no BlockRegistry was provided at construction
        time, falls back to the original filesystem-convention logic.
        """
        if ref.pinned_version:
            versioned = self._registry_root / ref.block_id / f"{ref.pinned_version}.json"
            if versioned.exists():
                return versioned
            logger.warning(
                "[executor] Pinned version %s for '%s' was not found; using current contract.",
                ref.pinned_version,
                ref.block_id,
            )
        return self._registry_root / f"{ref.block_id}.json"

    def _resolve_block_contract(
        self,
        ref: BlockRef,
        version_snapshot: Optional[dict[str, str]] = None,
    ) -> DataBlockContract:
        """
        Resolve a BlockRef to a DataBlockContract.

        Checks extra_contracts (user-uploaded blocks) first, then the
        BlockRegistryProtocol (if configured), then the filesystem.
        """
        if ref.block_id in self._extra_contracts:
            return self._extra_contracts[ref.block_id]
        if self._registry is not None:
            return self._registry.resolve(
                ref.block_id,
                ref.pinned_version or None,
                version_snapshot=version_snapshot,
            )
        return self._loader.load_json(str(self._resolve_block_path(ref)))

    @staticmethod
    def _apply_active_filters(
        spec: VisualQuerySpec,
        active_filters: dict[str, Any],
    ) -> VisualQuerySpec:
        if not active_filters:
            return spec
        filters: list[FilterSpec] = []
        for filter_spec in spec.filters:
            key = f"{filter_spec.block_id}.{filter_spec.column_name}"
            if filter_spec.inherit_global_filter and key in active_filters:
                filters.append(replace(filter_spec, value=active_filters[key]))
            else:
                filters.append(filter_spec)
        return replace(spec, filters=filters)

    @staticmethod
    def _build_metric_expr(
        metric: MetricRef,
        contracts: dict[str, DataBlockContract],
        primary_block_id: str,
        parameters: dict[str, float] | None = None,
    ) -> str:
        if metric.block_id != primary_block_id:
            raise QueryPlanningError("Metrics must come from the primary fact block.")
        contract = contracts[metric.block_id]
        definition = next(
            (candidate for candidate in contract.metrics if candidate.name == metric.metric_name),
            None,
        )
        if definition is None:
            raise QueryPlanningError(
                f"Metric '{metric.metric_name}' is not declared by '{metric.block_id}'."
            )
        approved = _APPROVED_AGGREGATIONS.get(definition.disaggregation_method)
        if approved is None:
            # Round 045: derived metric — disaggregation_method == none means the
            # metric is a composite aggregate expression (e.g. AOV, margin, YoY).
            # Build it from the validated formula instead of a single column.
            if definition.disaggregation_method == DisaggregationMethod.none:
                alias = _quote(metric.alias or metric.metric_name)
                expr = _build_derived_formula_expr(
                    definition.formula, primary_block_id, _column_names(contract),
                    parameters=parameters,
                )
                return f"{expr} AS {alias}"
            raise QueryPlanningError(
                f"Metric '{metric.metric_name}' requires a derived-expression planner."
            )
        _require_column(contracts, metric.block_id, metric.metric_name)
        if metric.agg_override is not None and metric.agg_override is not approved:
            raise QueryPlanningError(
                f"Aggregation '{metric.agg_override.value}' is not approved for "
                f"metric '{metric.metric_name}'; use '{approved.value}'."
            )
        alias = _quote(metric.alias or metric.metric_name)
        col = _qualified(metric.block_id, metric.metric_name)
        if approved is AggFunction.count_distinct:  # Round 099
            return f"COUNT(DISTINCT {col}) AS {alias}"
        return f"{approved.value}({col}) AS {alias}"

    # Comparison operators valid on an aggregated measure (Round 079).
    _HAVING_SIMPLE_OPS = {
        FilterOperator.eq: "=",
        FilterOperator.neq: "!=",
        FilterOperator.gt: ">",
        FilterOperator.gte: ">=",
        FilterOperator.lt: "<",
        FilterOperator.lte: "<=",
    }

    def _build_having_clause(
        self,
        having: "HavingSpec",
        contracts: dict[str, DataBlockContract],
        spec: VisualQuerySpec,
        params: list[Any],
    ) -> str:
        """Build one HAVING predicate against a projected metric's aggregate.

        The metric must already be in ``spec.metrics`` (a visual-level measure
        filter), so we reuse its validated aggregate expression rather than
        accepting an arbitrary expression — keeping the governed contract intact.
        """
        ref = next(
            (m for m in spec.metrics
             if m.metric_name == having.metric_name and m.block_id == having.block_id),
            None,
        )
        if ref is None:
            raise QueryPlanningError(
                f"HAVING references metric '{having.metric_name}' which is not projected "
                f"by this visual; add it as a metric first."
            )
        # Reuse the exact aggregate expression from SELECT, minus its alias suffix.
        expr_with_alias = self._build_metric_expr(
            ref, contracts, spec.primary_block_id, self._parameters
        )
        alias_suffix = f" AS {_quote(ref.alias or ref.metric_name)}"
        expr = (
            expr_with_alias[: -len(alias_suffix)]
            if expr_with_alias.endswith(alias_suffix)
            else expr_with_alias
        )

        op = having.operator
        if op in self._HAVING_SIMPLE_OPS:
            params.append(having.value)
            return f"({expr}) {self._HAVING_SIMPLE_OPS[op]} ?"
        if op == FilterOperator.between:
            params.extend([having.value[0], having.value[1]])
            return f"({expr}) BETWEEN ? AND ?"
        raise QueryPlanningError(
            f"Operator '{op}' is not supported in HAVING; use a numeric comparison."
        )

    @staticmethod
    def _build_dimension_expr(
        dimension: DimensionRef,
        contracts: dict[str, DataBlockContract],
    ) -> str:
        _require_column(contracts, dimension.block_id, dimension.column_name)
        col = _qualified(dimension.block_id, dimension.column_name)
        alias = _quote(dimension.alias or dimension.column_name)
        trunc = (dimension.truncate_date_to or "").lower()
        if trunc:
            # Round 096: seasonality buckets — weekday / hour — beyond DATE_TRUNC.
            if trunc in ("dow", "weekday", "dayofweek"):
                return f"DAYNAME({col}::DATE) AS {alias}"
            if trunc == "hour":
                return f"EXTRACT(hour FROM {col}::TIMESTAMP) AS {alias}"
            return f"DATE_TRUNC('{trunc}', {col}::DATE) AS {alias}"
        return f"{col} AS {alias}"

    def _build_sql(
        self,
        spec: VisualQuerySpec,
        contracts: dict[str, DataBlockContract],
        joins: list[ResolvedJoin],
        params: list[Any],
    ) -> str:
        for filter_spec in spec.filters:
            _require_column(contracts, filter_spec.block_id, filter_spec.column_name)

        aliases = [
            *(dimension.alias or dimension.column_name for dimension in spec.dimensions),
            *(metric.alias or metric.metric_name for metric in spec.metrics),
        ]
        if len(aliases) != len(set(aliases)):
            raise QueryPlanningError("Visual output aliases must be unique.")
        # Round 163: self-heal a stale sort. After a UI edit changes the measure or
        # dimension, a sort that referenced the now-removed column would otherwise
        # crash the whole visual ("Sort column X is not a projected output"). A
        # sort on a non-projected column is a no-op in SQL terms, so drop it
        # rather than failing the query.
        _valid_sort = [s for s in spec.sort if s.column_name in aliases]

        select_parts = [
            *(self._build_dimension_expr(dimension, contracts) for dimension in spec.dimensions),
            *(
                self._build_metric_expr(metric, contracts, spec.primary_block_id, self._parameters)
                for metric in spec.metrics
            ),
        ]
        select_clause = ",\n    ".join(select_parts) if select_parts else f"{_quote(spec.primary_block_id)}.*"
        sql_parts = [f"SELECT\n    {select_clause}", f"FROM {_quote(spec.primary_block_id)}"]

        for join in joins:
            predicates = " AND ".join(
                f"{_qualified(join.from_block, source)} = {_qualified(join.to_block, target)}"
                for source, target in join.key_pairs
            )
            sql_parts.append(f"LEFT JOIN {_quote(join.to_block)} ON {predicates}")

        where_parts = [
            _build_filter_clause(filter_spec, params)
            for filter_spec in spec.filters
            if filter_spec.value is not None
            or filter_spec.operator in (FilterOperator.is_null, FilterOperator.is_not_null)
        ]
        # Round 103: row-level security — inject each participating block's policy
        # row filter as a parameterized predicate bound to the identity context.
        where_parts.extend(self._rls_predicates(spec, contracts, params))
        if where_parts:
            sql_parts.append("WHERE\n    " + "\n    AND ".join(where_parts))
        if spec.dimensions and spec.metrics:
            # Use positional GROUP BY to avoid ambiguous column references when
            # the same column name exists in both the fact table and a joined dim table.
            dim_positions = ", ".join(str(i + 1) for i in range(len(spec.dimensions)))
            sql_parts.append(f"GROUP BY {dim_positions}")
        # Round 079: HAVING — post-aggregate predicates on projected metrics.
        if spec.having:
            having_parts = [
                self._build_having_clause(h, contracts, spec, params)
                for h in spec.having
                if h.value is not None
            ]
            if having_parts:
                sql_parts.append("HAVING\n    " + "\n    AND ".join(having_parts))
        if _valid_sort:
            sql_parts.append(
                "ORDER BY " + ", ".join(
                    f"{_quote(sort.column_name)} {sort.direction.value.upper()}"
                    for sort in _valid_sort
                )
            )
        if spec.limit:
            sql_parts.append(f"LIMIT {spec.limit}")
        return "\n".join(sql_parts)

    def _rls_predicates(
        self,
        spec: VisualQuerySpec,
        contracts: dict[str, DataBlockContract],
        params: list[Any],
    ) -> list[str]:
        """Round 103: build parameterized row-level-security predicates.

        For each block in the query whose policy declares a row_filter_column +
        identity key, and where the identity context supplies that key, emit
        ``<block>.<col> = ?`` bound to the identity value. Empty identity (e.g. an
        admin/unscoped session) applies no restriction. Always parameterized and
        column-validated, so it is injection-safe.
        """
        if not self._identity:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for ref in spec.block_refs:
            if ref.block_id in seen:
                continue
            seen.add(ref.block_id)
            contract = contracts.get(ref.block_id)
            policy = getattr(contract, "policy", None)
            col = getattr(policy, "row_filter_column", None)
            key = getattr(policy, "row_filter_identity_key", None)
            if not col or not key or key not in self._identity:
                continue
            _require_column(contracts, ref.block_id, col)
            params.append(self._identity[key])
            out.append(f"{_qualified(ref.block_id, col)} = ?")
        return out

    def run(
        self,
        spec: VisualQuerySpec,
        active_filters: Optional[dict[str, Any]] = None,
        version_snapshot: Optional[dict[str, str]] = None,
    ) -> pd.DataFrame:
        df, _ = self.run_with_metadata(
            spec, active_filters=active_filters, version_snapshot=version_snapshot
        )
        return df

    def run_with_metadata(
        self,
        spec: VisualQuerySpec,
        active_filters: Optional[dict[str, Any]] = None,
        version_snapshot: Optional[dict[str, str]] = None,
        component_id: Optional[str] = None,
    ) -> tuple[pd.DataFrame, ResultMetadata]:
        """Execute and return (DataFrame, ResultMetadata).

        ResultMetadata contains the full execution lineage required by spec 7.4
        and displayed in the per-visual Explanation Panel (spec 8.1).
        """
        if active_filters is not None:
            spec = self._apply_active_filters(spec, active_filters)

        conn = duckdb.connect(database=":memory:")
        contracts: dict[str, DataBlockContract] = {}
        executed_at = datetime.now(timezone.utc).isoformat()
        try:
            for ref in spec.block_refs:
                contract = self._resolve_block_contract(ref, version_snapshot=version_snapshot)
                contracts[ref.block_id] = contract
                # Round 032/051: reuse cached Arrow table for in-process sources
                from ai4bi.blocks.contracts import CachedDataSource as _Cached
                from ai4bi.blocks.contracts import InlineDataSource as _Inline
                _materializable = (_Inline, _Cached)
                if isinstance(contract.data_source, _materializable) and ref.block_id in self._arrow_cache:
                    conn.register(ref.block_id, self._arrow_cache[ref.block_id])
                else:
                    self._loader.register_to_duckdb(contract, ref.block_id, conn)
                    if isinstance(contract.data_source, _materializable):
                        # Cache the Arrow table for subsequent queries in this session
                        self._arrow_cache[ref.block_id] = self._loader.to_arrow(contract)

            joins = self._planner.resolve(spec, contracts)
            params: list[Any] = []
            sql = self._build_sql(spec, contracts, joins, params)
            logger.debug("[executor] SQL:\n%s\nparams=%s", sql, params)
            df = conn.execute(sql, params).df()

            # Build metadata
            blocks_used = [ref.block_id for ref in spec.block_refs]
            relationships_used = [
                f"{j.from_block} → {j.to_block} "
                f"({getattr(j, 'cardinality', 'many_to_one')}) "
                f"[{getattr(j, 'certification_status', 'certified')}]"
                for j in joins
            ]
            metrics_used = []
            for m in spec.metrics:
                contract = contracts.get(m.block_id)
                defn = next(
                    (md for md in (contract.metrics if contract else []) if md.name == m.metric_name),
                    None,
                )
                metrics_used.append({
                    "name": m.alias or m.metric_name,
                    "metric_id": m.metric_name,
                    "formula": getattr(defn, "formula", None) or m.metric_name,
                    "agg": getattr(defn, "disaggregation_method", None) or "unknown",
                    "block_id": m.block_id,
                })
            dimensions_used = [
                f"{d.alias or d.column_name}"
                + (f" (DATE_TRUNC {d.truncate_date_to})" if d.truncate_date_to else "")
                for d in spec.dimensions
            ]
            filters_applied = [
                f"{f.block_id}.{f.column_name} {f.operator.value} {f.value!r}"
                for f in spec.filters
                if f.value is not None
            ]
            quality_warnings: list[str] = []
            if df.empty:
                quality_warnings.append("Query returned 0 rows — check active filters.")
            data_freshness: dict[str, str] = {}
            for ref in spec.block_refs:
                block_path = self._resolve_block_path(ref)
                if block_path.exists():
                    mtime = datetime.fromtimestamp(
                        block_path.stat().st_mtime, tz=timezone.utc
                    ).isoformat()
                    data_freshness[ref.block_id] = mtime

            metadata = ResultMetadata(
                component_id=component_id or spec.spec_id,
                row_count=len(df),
                executed_at=executed_at,
                blocks_used=blocks_used,
                relationships_used=relationships_used,
                metrics_used=metrics_used,
                dimensions_used=dimensions_used,
                filters_applied=filters_applied,
                quality_warnings=quality_warnings,
                data_freshness=data_freshness,
                sql_preview=sql[:400],
            )
            logger.debug(
                "[executor] run_with_metadata spec=%s rows=%d blocks=%s",
                spec.spec_id, len(df), blocks_used,
            )
            return df, metadata
        finally:
            conn.close()
