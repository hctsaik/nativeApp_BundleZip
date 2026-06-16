"""
DataBlockContract — core Pydantic v2 schema for AI-for-BI semantic blocks.

Design-council consensus: 10 block types, discriminated-union data sources,
semver lifecycle, fanout-risk annotations.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BlockType(str, Enum):
    fact            = "fact"
    snapshot_fact   = "snapshot_fact"
    target_fact     = "target_fact"
    dimension       = "dimension"
    date_dimension  = "date_dimension"
    metric_set      = "metric_set"
    derived_block   = "derived_block"
    relationship    = "relationship"
    policy          = "policy"
    analysis        = "analysis"


class LifecycleStatus(str, Enum):
    draft      = "draft"
    validated  = "validated"
    certified  = "certified"
    deprecated = "deprecated"
    suspended  = "suspended"


class PiiLevel(str, Enum):
    none        = "none"
    low         = "low"
    medium      = "medium"
    high        = "high"
    restricted  = "restricted"


class DataClassification(str, Enum):
    public       = "public"
    internal     = "internal"
    confidential = "confidential"
    restricted   = "restricted"


class JoinType(str, Enum):
    inner       = "inner"
    left        = "left"
    right       = "right"
    full_outer  = "full_outer"


class FanoutRisk(str, Enum):
    LOW     = "LOW"
    MEDIUM  = "MEDIUM"
    HIGH    = "HIGH"
    BLOCKED = "BLOCKED"


class DisaggregationMethod(str, Enum):
    sum            = "sum"
    average        = "average"
    count          = "count"
    count_distinct = "count_distinct"  # Round 099: COUNT(DISTINCT col)
    min            = "min"
    max            = "max"
    last           = "last"
    none           = "none"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class ColumnSchema(BaseModel):
    """Schema descriptor for a single column in a block."""

    name: str = Field(..., min_length=1, description="Column name (snake_case recommended)")
    data_type: str = Field(..., description="Logical type: string, integer, float, boolean, date, timestamp, etc.")
    pii_level: PiiLevel = Field(PiiLevel.none, description="PII classification of this column")
    nullable: bool = Field(True, description="Whether the column may contain null values")
    description: Optional[str] = Field(None, description="Human-readable column description")


class MetricDefinition(BaseModel):
    """A named, formula-driven metric that can be disaggregated."""

    name: str = Field(..., min_length=1, description="Unique metric name within the block")
    formula: str = Field(..., description="SQL-compatible expression or dbt metric ref, e.g. 'SUM(revenue)'")
    disaggregation_method: DisaggregationMethod = Field(
        DisaggregationMethod.sum,
        description="How to roll up / disaggregate the metric across dimensions",
    )
    unit: Optional[str] = Field(None, description="Display unit, e.g. 'USD', '%', 'units'")
    description: Optional[str] = Field(None, description="Human-readable metric description")


class RelationshipHint(BaseModel):
    """Declares a pre-approved join path from this block to another block."""

    target_block_id: str = Field(..., description="block_id of the target block")
    allowed_join_keys: list[str] = Field(..., min_length=1, description="Column names that are valid join keys")
    join_type: JoinType = Field(JoinType.left, description="Permitted join type")
    fanout_risk: FanoutRisk = Field(FanoutRisk.LOW, description="Risk level of row multiplication")
    description: Optional[str] = Field(None, description="Notes on relationship semantics or caveats")


class PolicySpec(BaseModel):
    """Governance and access-control settings for the block."""

    data_classification: DataClassification = Field(
        DataClassification.internal,
        description="Information classification level",
    )
    row_filter_expr: Optional[str] = Field(
        None,
        description="SQL WHERE clause to restrict rows by role/attribute, e.g. 'region = current_user_region()'",
    )
    # Round 103: structured (injection-safe) row-level security. The executor
    # injects `WHERE <row_filter_column> = ?` bound to identity[row_filter_identity_key]
    # — a parameterized predicate on a validated column, never raw SQL.
    row_filter_column: Optional[str] = Field(
        None,
        description="Column to constrain for row-level security (e.g. 'city').",
    )
    row_filter_identity_key: Optional[str] = Field(
        None,
        description="Identity-context key whose value the row_filter_column must equal (e.g. 'city').",
    )
    allowed_roles: list[str] = Field(
        default_factory=list,
        description="Roles permitted to access this block; empty list means unrestricted",
    )


# ---------------------------------------------------------------------------
# Data-source discriminated union
# ---------------------------------------------------------------------------

class InlineDataSource(BaseModel):
    """Embeds rows directly in the contract JSON (suitable for < 10 K rows)."""

    source_type: Literal["inline"] = "inline"
    records: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Row data as a list of dicts; keys must match column names",
    )


class CachedDataSource(BaseModel):
    """References rows held in the process-global content-addressed store.

    Round 051: lets a contract carry only a content hash + lightweight stats
    instead of embedding 10K+ rows, so large uploads no longer bloat
    st.session_state. Resolve via ai4bi.blocks.datastore.materialize_dataframe.
    """

    source_type: Literal["cached"] = "cached"
    content_hash: str = Field(..., description="Key into the content-addressed DataFrame store")
    row_count: int = Field(0, description="Number of rows (for display / metadata)")


class ExternalDataSource(BaseModel):
    """References a production query or file-based data source."""

    source_type: Literal["execution_ref", "data_ref"]
    # execution_ref fields
    query: Optional[str] = Field(None, description="SQL / dbt ref / Spark expression")
    connection_id: Optional[str] = Field(None, description="Named connection for query execution")
    # data_ref fields
    path: Optional[str] = Field(None, description="Parquet / Delta table path or URI")
    format: Optional[str] = Field(None, description="File format: parquet, delta, csv, etc.")
    partition_cols: list[str] = Field(default_factory=list, description="Partition column names")

    @model_validator(mode="after")
    def _check_fields_by_type(self) -> "ExternalDataSource":
        if self.source_type == "execution_ref" and not self.query:
            raise ValueError("execution_ref requires a non-empty 'query'")
        if self.source_type == "data_ref" and not self.path:
            raise ValueError("data_ref requires a non-empty 'path'")
        return self


# Discriminated union — Pydantic dispatches on the literal 'source_type' field
DataSource = Annotated[
    Union[InlineDataSource, CachedDataSource, ExternalDataSource],
    Field(discriminator="source_type"),
]


# ---------------------------------------------------------------------------
# Main contract
# ---------------------------------------------------------------------------

class DataBlockContract(BaseModel):
    """
    Top-level semantic block contract.

    Represents one cohesive unit of governed data: a fact table, dimension,
    metric set, derived view, etc.  Contracts are the single source of truth
    for schema, metrics, relationships, policies, and data access.
    """

    # Identity
    block_id: str = Field(..., min_length=1, description="Globally unique block identifier (snake_case)")
    block_type: BlockType = Field(..., description="Semantic category of this block")
    grain: str = Field(..., min_length=1, description="Textual description of one row's granularity, e.g. 'order_id'")
    version: str = Field("1.0.0", description="Semantic version of this contract, e.g. '1.2.3'")
    description: Optional[str] = Field(None, description="Human-readable block description")

    # Lifecycle
    block_lifecycle: LifecycleStatus = Field(LifecycleStatus.draft, description="Current lifecycle stage")

    # Schema
    primary_keys: list[str] = Field(default_factory=list, description="Column(s) that uniquely identify a row")
    columns: list[ColumnSchema] = Field(default_factory=list, description="Column descriptors")

    # Semantics
    metrics: list[MetricDefinition] = Field(default_factory=list, description="Named metrics defined on this block")
    relationships: list[RelationshipHint] = Field(
        default_factory=list, description="Pre-approved join paths to other blocks"
    )

    # Governance
    policy: PolicySpec = Field(default_factory=PolicySpec, description="Access and classification policy")

    # Data
    data_source: DataSource = Field(
        default_factory=InlineDataSource,
        description="Where/how to obtain the actual data for this block",
    )

    # ---------------------------------------------------------------------------
    # Validators
    # ---------------------------------------------------------------------------

    @field_validator("grain")
    @classmethod
    def grain_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("'grain' must be a non-empty, non-whitespace string")
        return v

    @model_validator(mode="after")
    def no_duplicate_metric_names(self) -> "DataBlockContract":
        names = [m.name for m in self.metrics]
        seen: set[str] = set()
        duplicates: list[str] = []
        for name in names:
            if name in seen:
                duplicates.append(name)
            seen.add(name)
        if duplicates:
            raise ValueError(f"Duplicate metric name(s) in block '{self.block_id}': {duplicates}")
        return self

    @model_validator(mode="after")
    def version_is_semver(self) -> "DataBlockContract":
        parts = self.version.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"'version' must be a valid semver string (MAJOR.MINOR.PATCH), got: {self.version!r}")
        return self
