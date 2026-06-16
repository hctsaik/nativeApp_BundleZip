"""
spec_models.py — P1 ReportSpec data model layer.

Defines the complete spec hierarchy:
    BlockRef → VisualQuerySpec → PageSpec → ReportSpec

Plus the patch / path-resolver layer:
    PatchOperation, PatchProposal, ApplyResult
    apply_proposal()        — lenient (best-effort)
    apply_proposal_strict() — atomic (all-or-nothing)

Design-council decisions (Round 006-007):
  • ReportSpec carries an integer `version` that increments on every apply.
  • PageSpec stores visuals as dict[visual_id → VisualQuerySpec] + visual_order list.
  • PathResolver supports:
      /pages/{page_id}/visuals/{visual_id}/**   (add / replace / remove individual fields)
      /pages/{page_id}/visual_order            (reorder list)
      /global_filters/{key}                    (add / replace / remove global filter entry)
  • One PatchProposal = one undo step.
  • requires_confirmation=True → proposal goes to staging, not applied directly.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Leaf data structures
# ---------------------------------------------------------------------------

@dataclass
class BlockRef:
    """Reference to a DataBlock, with optional version pinning."""

    block_id: str
    pinned_version: str | None = None
    pin_reason: str | None = None

    # ------------------------------------------------------------------ #
    # Serialisation helpers                                                #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "pinned_version": self.pinned_version,
            "pin_reason": self.pin_reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BlockRef":
        return cls(
            block_id=d["block_id"],
            pinned_version=d.get("pinned_version"),
            pin_reason=d.get("pin_reason"),
        )

    def deep_copy(self) -> "BlockRef":
        return BlockRef(
            block_id=self.block_id,
            pinned_version=self.pinned_version,
            pin_reason=self.pin_reason,
        )


@dataclass
class VisualQuerySpec:
    """Query specification for a single visual element on a page."""

    visual_id: str
    component_type: str                 # kpi | bar | line | table
    block_refs: list[BlockRef]
    metrics: list[str]
    dimensions: list[str]
    filters: list[dict]
    chart_type: str
    inherit_global_filter: bool = True

    # ------------------------------------------------------------------ #
    # Serialisation helpers                                                #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "visual_id": self.visual_id,
            "component_type": self.component_type,
            "block_refs": [br.to_dict() for br in self.block_refs],
            "metrics": list(self.metrics),
            "dimensions": list(self.dimensions),
            "filters": copy.deepcopy(self.filters),
            "chart_type": self.chart_type,
            "inherit_global_filter": self.inherit_global_filter,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VisualQuerySpec":
        return cls(
            visual_id=d["visual_id"],
            component_type=d["component_type"],
            block_refs=[BlockRef.from_dict(br) for br in d.get("block_refs", [])],
            metrics=list(d.get("metrics", [])),
            dimensions=list(d.get("dimensions", [])),
            filters=copy.deepcopy(d.get("filters", [])),
            chart_type=d.get("chart_type", ""),
            inherit_global_filter=d.get("inherit_global_filter", True),
        )

    def deep_copy(self) -> "VisualQuerySpec":
        return VisualQuerySpec.from_dict(self.to_dict())


# ---------------------------------------------------------------------------
# PageSpec
# ---------------------------------------------------------------------------

@dataclass
class PageSpec:
    """A single page in a report, containing an ordered set of visuals."""

    page_id: str
    title: str
    visuals: dict[str, VisualQuerySpec]
    visual_order: list[str]

    def __post_init__(self) -> None:
        self._validate_visual_order()

    def _validate_visual_order(self) -> None:
        """visual_order must be a permutation of visuals.keys()."""
        order_set = set(self.visual_order)
        visuals_set = set(self.visuals.keys())
        if order_set != visuals_set:
            extra_in_order = order_set - visuals_set
            missing_from_order = visuals_set - order_set
            parts: list[str] = []
            if extra_in_order:
                parts.append(f"visual_order references unknown visual IDs: {sorted(extra_in_order)}")
            if missing_from_order:
                parts.append(f"visual_order is missing visual IDs: {sorted(missing_from_order)}")
            raise ValueError(
                f"[PageSpec '{self.page_id}'] visual_order inconsistency — " + "; ".join(parts)
            )

    # ------------------------------------------------------------------ #
    # Serialisation helpers                                                #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "visuals": {vid: v.to_dict() for vid, v in self.visuals.items()},
            "visual_order": list(self.visual_order),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PageSpec":
        visuals = {
            vid: VisualQuerySpec.from_dict(vd)
            for vid, vd in d.get("visuals", {}).items()
        }
        return cls(
            page_id=d["page_id"],
            title=d["title"],
            visuals=visuals,
            visual_order=list(d.get("visual_order", list(visuals.keys()))),
        )

    def deep_copy(self) -> "PageSpec":
        return PageSpec.from_dict(self.to_dict())


# ---------------------------------------------------------------------------
# ReportSpec
# ---------------------------------------------------------------------------

@dataclass
class ReportSpec:
    """Top-level report specification."""

    report_id: str
    pages: dict[str, PageSpec]
    global_filters: dict[str, Any]
    version: int = 0

    # ------------------------------------------------------------------ #
    # Serialisation helpers                                                #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "pages": {pid: p.to_dict() for pid, p in self.pages.items()},
            "global_filters": copy.deepcopy(self.global_filters),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReportSpec":
        pages = {
            pid: PageSpec.from_dict(pd)
            for pid, pd in d.get("pages", {}).items()
        }
        return cls(
            report_id=d["report_id"],
            pages=pages,
            global_filters=copy.deepcopy(d.get("global_filters", {})),
            version=d.get("version", 0),
        )

    def deep_copy(self) -> "ReportSpec":
        return ReportSpec.from_dict(self.to_dict())


# ---------------------------------------------------------------------------
# Patch layer — operations, proposals, results
# ---------------------------------------------------------------------------

PatchOpType = Literal["add", "replace", "remove"]


@dataclass
class PatchOperation:
    """A single RFC-6902-inspired patch operation on a ReportSpec path."""

    op: PatchOpType          # "add" | "replace" | "remove"
    path: str                # e.g. "/pages/p1/visuals/v1/metrics"
    value: Any = None        # required for "add" / "replace"; ignored for "remove"

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "path": self.path, "value": copy.deepcopy(self.value)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PatchOperation":
        return cls(op=d["op"], path=d["path"], value=copy.deepcopy(d.get("value")))


@dataclass
class PatchProposal:
    """
    One unit of change — maps to exactly one undo step.

    Attributes
    ----------
    operations:
        Ordered list of PatchOperation to apply atomically.
    description:
        Human-readable summary (for UI / audit log).
    requires_confirmation:
        If True, the proposal must pass through staging before being applied
        to the live spec.  The StateManager enforces this.
    ambiguity_options:
        If the agent is unsure about the intent, it may populate this list with
        alternative PatchProposal objects.  The user selects one, and
        apply_ambiguity_choice() dispatches it.
    """

    operations: list[PatchOperation]
    description: str = ""
    requires_confirmation: bool = False
    ambiguity_options: list["PatchProposal"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operations": [op.to_dict() for op in self.operations],
            "description": self.description,
            "requires_confirmation": self.requires_confirmation,
            "ambiguity_options": [o.to_dict() for o in self.ambiguity_options],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PatchProposal":
        return cls(
            operations=[PatchOperation.from_dict(op) for op in d.get("operations", [])],
            description=d.get("description", ""),
            requires_confirmation=d.get("requires_confirmation", False),
            ambiguity_options=[
                PatchProposal.from_dict(o) for o in d.get("ambiguity_options", [])
            ],
        )


@dataclass
class ApplyResult:
    """Outcome of an apply_proposal call."""

    spec: ReportSpec
    success: bool
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.success


# ---------------------------------------------------------------------------
# PathResolver — internal helper
# ---------------------------------------------------------------------------

class _PathResolver:
    """
    Resolve and mutate a ReportSpec in-place given a PatchOperation.

    Supported path patterns:
        /pages/{page_id}/visuals/{visual_id}/{field}
        /pages/{page_id}/visuals/{visual_id}           (add/remove whole visual)
        /pages/{page_id}/visual_order
        /global_filters/{key}

    All mutations are performed on a *copy* supplied by the caller; the caller
    decides whether to commit or discard the copy.
    """

    @staticmethod
    def apply(spec: ReportSpec, op: PatchOperation) -> list[str]:
        """
        Apply *op* to *spec* in-place.

        Returns
        -------
        list[str]
            Empty list on success; one or more error messages on failure.
        """
        parts = [p for p in op.path.split("/") if p]

        # ------------------------------------------------------------------ #
        # /global_filters/{key}                                               #
        # ------------------------------------------------------------------ #
        if parts and parts[0] == "global_filters":
            return _PathResolver._apply_global_filter(spec, op, parts)

        # ------------------------------------------------------------------ #
        # /pages/{page_id}/...                                                #
        # ------------------------------------------------------------------ #
        if parts and parts[0] == "pages":
            return _PathResolver._apply_pages(spec, op, parts)

        return [f"Unsupported path: '{op.path}'"]

    # ------------------------------------------------------------------ #
    # /global_filters/{key}                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _apply_global_filter(
        spec: ReportSpec, op: PatchOperation, parts: list[str]
    ) -> list[str]:
        if len(parts) < 2:
            return ["Path '/global_filters' requires a key segment, e.g. '/global_filters/date_range'"]
        key = parts[1]

        if op.op in ("add", "replace"):
            spec.global_filters[key] = copy.deepcopy(op.value)
            return []
        if op.op == "remove":
            if key not in spec.global_filters:
                return [f"global_filters key '{key}' does not exist — cannot remove"]
            del spec.global_filters[key]
            return []
        return [f"Unknown op '{op.op}'"]

    # ------------------------------------------------------------------ #
    # /pages/{page_id}/...                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _apply_pages(
        spec: ReportSpec, op: PatchOperation, parts: list[str]
    ) -> list[str]:
        if len(parts) < 2:
            return ["Path '/pages' requires a page_id segment"]
        page_id = parts[1]

        # /pages/{page_id}  — add or remove a whole page
        if len(parts) == 2:
            if op.op == "add":
                if page_id in spec.pages:
                    return [f"Page '{page_id}' already exists; use 'replace' or remove first"]
                try:
                    spec.pages[page_id] = PageSpec.from_dict(copy.deepcopy(op.value))
                except Exception as exc:
                    return [f"Cannot create PageSpec from value: {exc}"]
                return []
            if op.op == "replace":
                try:
                    spec.pages[page_id] = PageSpec.from_dict(copy.deepcopy(op.value))
                except Exception as exc:
                    return [f"Cannot create PageSpec from value: {exc}"]
                return []
            if op.op == "remove":
                if page_id not in spec.pages:
                    return [f"Page '{page_id}' does not exist — cannot remove"]
                del spec.pages[page_id]
                return []
            return [f"Unknown op '{op.op}'"]

        if page_id not in spec.pages:
            return [f"Page '{page_id}' does not exist"]
        page = spec.pages[page_id]

        sub = parts[2]

        # ------------------------------------------------------------------ #
        # /pages/{page_id}/visual_order                                       #
        # ------------------------------------------------------------------ #
        if sub == "visual_order":
            if op.op not in ("replace",):
                return [f"visual_order only supports op='replace'; got '{op.op}'"]
            new_order = list(op.value)
            # Validate consistency
            if set(new_order) != set(page.visuals.keys()):
                return [
                    f"visual_order value {new_order!r} is not a permutation "
                    f"of existing visual IDs {sorted(page.visuals.keys())!r}"
                ]
            page.visual_order = new_order
            return []

        # ------------------------------------------------------------------ #
        # /pages/{page_id}/visuals/{visual_id}[/{field}]                      #
        # ------------------------------------------------------------------ #
        if sub == "visuals":
            if len(parts) < 4:
                return ["Path '/pages/{page_id}/visuals' requires a visual_id segment"]
            visual_id = parts[3]

            # /pages/{page_id}/visuals/{visual_id}  — add/replace/remove whole visual
            if len(parts) == 4:
                return _PathResolver._apply_whole_visual(page, op, visual_id)

            # /pages/{page_id}/visuals/{visual_id}/{field}
            field_name = parts[4]
            if visual_id not in page.visuals:
                return [f"Visual '{visual_id}' does not exist in page '{page.page_id}'"]
            return _PathResolver._apply_visual_field(page.visuals[visual_id], op, field_name)

        return [f"Unsupported sub-path '{sub}' under page '{page_id}'"]

    # ------------------------------------------------------------------ #
    # Whole-visual helpers                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _apply_whole_visual(
        page: PageSpec, op: PatchOperation, visual_id: str
    ) -> list[str]:
        if op.op == "add":
            if visual_id in page.visuals:
                return [f"Visual '{visual_id}' already exists; use 'replace'"]
            try:
                vqs = VisualQuerySpec.from_dict(copy.deepcopy(op.value))
            except Exception as exc:
                return [f"Cannot create VisualQuerySpec from value: {exc}"]
            page.visuals[visual_id] = vqs
            # Append to visual_order so the page stays consistent
            page.visual_order.append(visual_id)
            return []

        if op.op == "replace":
            existed = visual_id in page.visuals
            try:
                vqs = VisualQuerySpec.from_dict(copy.deepcopy(op.value))
            except Exception as exc:
                return [f"Cannot create VisualQuerySpec from value: {exc}"]
            page.visuals[visual_id] = vqs
            if not existed:
                page.visual_order.append(visual_id)
            return []

        if op.op == "remove":
            if visual_id not in page.visuals:
                return [f"Visual '{visual_id}' does not exist — cannot remove"]
            del page.visuals[visual_id]
            page.visual_order = [vid for vid in page.visual_order if vid != visual_id]
            return []

        return [f"Unknown op '{op.op}'"]

    # ------------------------------------------------------------------ #
    # Individual visual field helpers                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _apply_visual_field(
        visual: VisualQuerySpec, op: PatchOperation, field_name: str
    ) -> list[str]:
        """Set / remove a single field on an existing VisualQuerySpec."""

        _SCALAR_FIELDS = {
            "component_type", "chart_type", "inherit_global_filter", "visual_id"
        }
        _LIST_FIELDS = {"metrics", "dimensions", "filters"}
        _BLOCK_REFS_FIELD = "block_refs"

        if op.op == "remove":
            # Only list fields support element removal; scalar fields use replace
            if field_name in _LIST_FIELDS:
                current: list = getattr(visual, field_name)
                remove_val = op.value  # value to remove (by equality)
                try:
                    current.remove(remove_val)
                except ValueError:
                    return [f"Value {remove_val!r} not found in visual.{field_name}"]
                return []
            if field_name == _BLOCK_REFS_FIELD:
                block_id_to_remove = op.value if isinstance(op.value, str) else (op.value or {}).get("block_id")
                if block_id_to_remove is None:
                    return ["To remove a block_ref, provide the block_id as value (string or dict with 'block_id')"]
                before = len(visual.block_refs)
                visual.block_refs = [br for br in visual.block_refs if br.block_id != block_id_to_remove]
                if len(visual.block_refs) == before:
                    return [f"block_ref with block_id='{block_id_to_remove}' not found"]
                return []
            return [f"op='remove' is not supported on field '{field_name}'; use 'replace' to clear it"]

        if op.op in ("add", "replace"):
            if field_name in _SCALAR_FIELDS:
                setattr(visual, field_name, copy.deepcopy(op.value))
                return []

            if field_name in _LIST_FIELDS:
                if op.op == "replace":
                    setattr(visual, field_name, copy.deepcopy(op.value))
                else:  # add — append element(s)
                    current_list: list = getattr(visual, field_name)
                    val = copy.deepcopy(op.value)
                    if isinstance(val, list):
                        current_list.extend(val)
                    else:
                        current_list.append(val)
                return []

            if field_name == _BLOCK_REFS_FIELD:
                if op.op == "replace":
                    visual.block_refs = [BlockRef.from_dict(d) for d in copy.deepcopy(op.value)]
                else:  # add
                    val = copy.deepcopy(op.value)
                    if isinstance(val, list):
                        visual.block_refs.extend([BlockRef.from_dict(d) for d in val])
                    else:
                        visual.block_refs.append(BlockRef.from_dict(val))
                return []

            return [f"Unknown visual field '{field_name}'"]

        return [f"Unknown op '{op.op}'"]


# ---------------------------------------------------------------------------
# Public apply functions
# ---------------------------------------------------------------------------

def apply_proposal(spec: ReportSpec, proposal: PatchProposal) -> ApplyResult:
    """
    Lenient (best-effort) apply.

    Each operation is attempted independently.  Failing operations are
    recorded in ApplyResult.errors but do not prevent subsequent operations
    from running.  The returned spec reflects all operations that *succeeded*.

    The returned spec is a deep copy — the original is not modified.
    Returns ApplyResult(spec=..., success=True) even when some ops failed,
    as long as at least one op succeeded.  If *all* ops fail, success=False.
    """
    working = spec.deep_copy()
    errors: list[str] = []
    applied = 0

    for op in proposal.operations:
        op_errors = _PathResolver.apply(working, op)
        if op_errors:
            errors.extend(op_errors)
        else:
            applied += 1

    success = len(errors) == 0 or applied > 0
    if proposal.operations and applied == 0:
        success = False

    # Increment version on any successful change
    if applied > 0:
        working.version += 1

    return ApplyResult(spec=working, success=success, errors=errors)


def apply_proposal_strict(spec: ReportSpec, proposal: PatchProposal) -> ApplyResult:
    """
    Atomic (strict) apply.

    All operations are pre-validated against a scratch copy.  If *any*
    operation fails, the original spec is returned unchanged and
    ApplyResult.success=False.

    On full success, a fresh deep copy of the spec is returned with
    version incremented by 1.
    """
    scratch = spec.deep_copy()
    all_errors: list[str] = []

    for op in proposal.operations:
        op_errors = _PathResolver.apply(scratch, op)
        if op_errors:
            all_errors.extend(op_errors)

    if all_errors:
        # Return the *original* spec unchanged
        return ApplyResult(spec=spec.deep_copy(), success=False, errors=all_errors)

    scratch.version += 1
    return ApplyResult(spec=scratch, success=True, errors=[])
