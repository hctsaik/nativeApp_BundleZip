"""VisualBuilder — constructs a draft VisualQuerySpec + VisualizationSpec
from user selections in the Add Visual panel.

Safety rules enforced here
--------------------------
* Metrics must come from the primary (fact) block only.
* Dimension blocks must have a *certified* relationship from the primary block.
* kpi_card: zero dimensions required (dimensions are rejected if any are given).
* table: at least one dimension required.
* line_chart / bar_chart: at least one dimension required.
* At most 2 metrics and at most 2 dimensions are accepted (caller pre-filters,
  but we validate defensively).

Raises
------
ValueError
    If any safety rule is violated.  Callers (e.g. Streamlit UI) should catch
    this and display ``st.warning``.
"""

from __future__ import annotations

from typing import Literal

from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.query_spec import (
    BlockRef,
    DimensionRef,
    MetricRef,
    VisualizationSpec,
    VisualQuerySpec,
    VisualType,
)
from ai4bi.report.catalog import _certified_dim_targets, _make_display_name
from ai4bi.report.models import (
    ReportChange,
    ReportProposal,
    ReportVisualSpec,
    query_to_dict,
    visualization_to_dict,
)


# ---------------------------------------------------------------------------
# Compatibility rules
# ---------------------------------------------------------------------------

#: Visual types that may NOT have any dimensions.
_NO_DIMENSION_TYPES: frozenset[VisualType] = frozenset({VisualType.kpi_card})

#: Visual types that REQUIRE at least one dimension.
_REQUIRE_DIMENSION_TYPES: frozenset[VisualType] = frozenset(
    {VisualType.line_chart, VisualType.bar_chart, VisualType.table,
     VisualType.pie_chart, VisualType.scatter}  # Round 029/031
)

_MAX_METRICS = 2
_MAX_DIMENSIONS = 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_visual_from_selection(
    visual_id: str,
    block_id: str,
    metric_names: list[str],
    dimension_names: list[str],       # list of "block_id.column_name" compound keys
    visual_type: VisualType,
    contracts: dict[str, DataBlockContract],
    semantic_model: dict | None = None,
) -> tuple[VisualQuerySpec, VisualizationSpec]:
    """Build a draft VisualQuerySpec + VisualizationSpec from user selections.

    Parameters
    ----------
    visual_id:
        Unique identifier for the new visual (used as spec_id).
    block_id:
        The primary (fact) block from which metrics are drawn.
    metric_names:
        Names of metrics to include (must exist in ``contracts[block_id].metrics``).
        Maximum 2.
    dimension_names:
        Compound keys in the form ``"<block_id>.<column_name>"`` for dimensions.
        Pass an empty list for kpi_card visuals.  Maximum 2.
    visual_type:
        Target visual type (determines compatibility rules).
    contracts:
        Mapping of block_id → DataBlockContract for all loaded blocks.
    semantic_model:
        Optional parsed semantic_model.json; used to verify certified dimension
        relationships when dimensions come from a block other than *block_id*.
        If None, cross-block dimension validation is skipped (single-block mode).

    Returns
    -------
    tuple[VisualQuerySpec, VisualizationSpec]
        A ready-to-use query spec and visualization spec.

    Raises
    ------
    ValueError
        On any safety-rule violation.
    """
    _validate_inputs(
        visual_id=visual_id,
        block_id=block_id,
        metric_names=metric_names,
        dimension_names=dimension_names,
        visual_type=visual_type,
        contracts=contracts,
        semantic_model=semantic_model,
    )

    primary_contract = contracts[block_id]

    # Build MetricRef list.
    contract_metric_names = {m.name for m in primary_contract.metrics}
    metric_refs: list[MetricRef] = []
    for name in metric_names:
        if name not in contract_metric_names:
            raise ValueError(
                f"Metric '{name}' is not defined on block '{block_id}'."
            )
        metric_refs.append(MetricRef(block_id=block_id, metric_name=name))

    # Build DimensionRef list and collect extra block_refs.
    dim_refs: list[DimensionRef] = []
    extra_block_ids: list[str] = []  # dimension blocks beyond the primary
    for compound in dimension_names:
        dim_block_id, col_name = _parse_compound(compound)
        dim_refs.append(DimensionRef(block_id=dim_block_id, column_name=col_name))
        if dim_block_id != block_id and dim_block_id not in extra_block_ids:
            extra_block_ids.append(dim_block_id)

    # Assemble block_refs: primary first, then any dimension blocks.
    block_refs = [BlockRef(block_id=block_id)]
    for extra_id in extra_block_ids:
        block_refs.append(BlockRef(block_id=extra_id))

    query = VisualQuerySpec(
        spec_id=visual_id,
        block_refs=block_refs,
        metrics=metric_refs,
        dimensions=dim_refs,
        inherit_global_filter=False,
    )

    title = _default_title(metric_names, dimension_names, visual_type, block_id)
    viz = _default_visualization(visual_type, title)

    return query, viz


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _parse_compound(compound: str) -> tuple[str, str]:
    """Parse 'block_id.column_name' into (block_id, column_name).

    For backward compatibility, bare column names without a dot are assumed to
    belong to the primary block — callers should always supply fully-qualified keys.
    """
    if "." in compound:
        block_id, col = compound.split(".", 1)
        return block_id, col
    raise ValueError(
        f"Dimension key '{compound}' must be in the form 'block_id.column_name'."
    )


def _validate_inputs(
    *,
    visual_id: str,
    block_id: str,
    metric_names: list[str],
    dimension_names: list[str],
    visual_type: VisualType,
    contracts: dict[str, DataBlockContract],
    semantic_model: dict | None,
) -> None:
    if not visual_id or not visual_id.strip():
        raise ValueError("visual_id must be a non-empty string.")
    if not block_id or block_id not in contracts:
        raise ValueError(f"Block '{block_id}' is not present in the loaded contracts.")
    if not metric_names:
        raise ValueError("At least one metric must be selected.")
    if len(metric_names) > _MAX_METRICS:
        raise ValueError(f"At most {_MAX_METRICS} metrics are allowed; got {len(metric_names)}.")
    if len(dimension_names) > _MAX_DIMENSIONS:
        raise ValueError(f"At most {_MAX_DIMENSIONS} dimensions are allowed; got {len(dimension_names)}.")

    # Visual-type compatibility checks.
    if visual_type in _NO_DIMENSION_TYPES and dimension_names:
        raise ValueError(
            f"Visual type '{visual_type.value}' does not support dimensions. "
            "Remove all selected dimensions."
        )
    if visual_type in _REQUIRE_DIMENSION_TYPES and not dimension_names:
        raise ValueError(
            f"Visual type '{visual_type.value}' requires at least one dimension."
        )

    # Validate dimension blocks.
    certified_targets: set[str] | None = None
    if semantic_model is not None:
        certified_targets = _certified_dim_targets(block_id, semantic_model)

    for compound in dimension_names:
        dim_block_id, col_name = _parse_compound(compound)
        if dim_block_id != block_id:
            # Cross-block dimension: must be in a certified relationship.
            if certified_targets is not None and dim_block_id not in certified_targets:
                raise ValueError(
                    f"Block '{dim_block_id}' does not have a certified relationship "
                    f"from the primary block '{block_id}'."
                )
            if dim_block_id not in contracts:
                raise ValueError(
                    f"Dimension block '{dim_block_id}' is not present in the loaded contracts."
                )
            dim_contract = contracts[dim_block_id]
            col_names = {c.name for c in dim_contract.columns}
            if col_name not in col_names:
                raise ValueError(
                    f"Column '{col_name}' is not defined on block '{dim_block_id}'."
                )
        else:
            # Self-dimension: column must exist on the primary block.
            primary_contract = contracts[block_id]
            col_names = {c.name for c in primary_contract.columns}
            if col_name not in col_names:
                raise ValueError(
                    f"Column '{col_name}' is not defined on block '{block_id}'."
                )


# ---------------------------------------------------------------------------
# Default title / visualization helpers
# ---------------------------------------------------------------------------

def _default_title(
    metric_names: list[str],
    dimension_names: list[str],
    visual_type: VisualType,
    block_id: str,
) -> str:
    metric_label = " & ".join(_make_display_name(m) for m in metric_names)
    if not dimension_names:
        return metric_label
    dim_labels = " & ".join(
        _make_display_name(_parse_compound(d)[1]) for d in dimension_names
    )
    return f"{metric_label} by {dim_labels}"


def _default_visualization(visual_type: VisualType, title: str) -> VisualizationSpec:
    kwargs: dict = {"visual_type": visual_type, "title": title}
    if visual_type == VisualType.line_chart:
        kwargs["height_px"] = 340
        kwargs["extra"] = {"line_color": None}
    elif visual_type == VisualType.bar_chart:
        kwargs["height_px"] = 340
    elif visual_type == VisualType.pie_chart:
        kwargs["height_px"] = 340
        kwargs["extra"] = {"hole": 0.4, "show_percent": True}
    elif visual_type == VisualType.scatter:
        kwargs["height_px"] = 340
    elif visual_type == VisualType.table:
        kwargs["height_px"] = 250
    elif visual_type == VisualType.kpi_card:
        kwargs["extra"] = {}
    return VisualizationSpec(**kwargs)


# ---------------------------------------------------------------------------
# Proposal builder
# ---------------------------------------------------------------------------

def build_reorder_visual_proposal(
    page_id: str,
    visual_id: str,
    direction: Literal["up", "down"],
    current_order: list[str],
) -> ReportProposal:
    """Build a ReportProposal that reorders a visual on a report page.

    Parameters
    ----------
    page_id:
        The id of the page containing the visual (e.g. ``"main"``).
    visual_id:
        Unique identifier of the visual to reorder.
    direction:
        ``"up"`` to move the visual earlier, ``"down"`` to move it later.
    current_order:
        The current ``visual_order`` list for the page (used as the ``before`` snapshot).

    Returns
    -------
    ReportProposal
        A single-change proposal with ``affects_data=False`` and path
        ``"pages/{page_id}/reorder_visual"``.
    """
    change = ReportChange(
        path=f"pages/{page_id}/reorder_visual",
        label=f"Move visual '{visual_id}' {direction}",
        before=list(current_order),
        after={"visual_id": visual_id, "direction": direction},
        affects_data=False,
    )
    return ReportProposal(
        description=f"Reorder visual '{visual_id}' {direction} on page '{page_id}'",
        changes=[change],
    )


def build_add_visual_proposal(
    page_id: str,
    visual_id: str,
    query_spec: VisualQuerySpec,
    viz_spec: VisualizationSpec,
) -> ReportProposal:
    """Build a ReportProposal that adds a new visual to a report page.

    Parameters
    ----------
    page_id:
        The id of the page to add the visual to (e.g. ``"main"``).
    visual_id:
        Unique identifier for the new visual.
    query_spec:
        The VisualQuerySpec for the new visual.
    viz_spec:
        The VisualizationSpec (chart type, title, etc.) for the new visual.

    Returns
    -------
    ReportProposal
        A single-change proposal with ``affects_data=True`` and path
        ``"pages/{page_id}/add_visual"``.
    """
    visual_spec = ReportVisualSpec(
        component_id=visual_id,
        query=query_spec,
        visualization=viz_spec,
    )
    change = ReportChange(
        path=f"pages/{page_id}/add_visual",
        label=f"Add {viz_spec.visual_type.value} visual",
        before=None,
        after={"visual_id": visual_id, "visual": visual_spec.to_dict()},
        affects_data=True,
    )
    return ReportProposal(
        description=f"Add visual '{visual_id}' to page '{page_id}'",
        changes=[change],
    )

def build_global_filter_proposal(
    filter_key: str,
    before_values: list,
    after_values: list,
) -> ReportProposal:
    """Build a ReportProposal that sets a global filter.

    Parameters
    ----------
    filter_key:
        The key for the global filter, e.g. "process_move_fact.product_family".
    before_values:
        The current list of allowed values (empty list or [] means key is absent).
    after_values:
        The new list of allowed values (empty list removes the key).

    Returns
    -------
    ReportProposal
        A single-change proposal with affects_data=True and path
        "global_filters/{filter_key}".
    """
    change = ReportChange(
        path=f"global_filters/{filter_key}",
        label=f"Set global filter '{filter_key}'",
        before=before_values if before_values else None,
        after=after_values if after_values else None,
        affects_data=True,
    )
    return ReportProposal(
        description=f"Set global filter '{filter_key}' to {after_values!r}",
        changes=[change],
    )

