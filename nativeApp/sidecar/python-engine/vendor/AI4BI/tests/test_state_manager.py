"""
tests/test_state_manager.py — P1 StateManager + spec_models tests.

All tests run without a real Streamlit installation.
st.session_state is monkey-patched to a plain dict via a pytest fixture.
st.rerun() is patched to a no-op.

Test IDs follow the STATE-XXX naming convention from the design council spec.

Run with:
    pytest tests/test_state_manager.py -v
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Streamlit mock — must be installed before importing state_manager
# ---------------------------------------------------------------------------


class _FakeSessionState(dict):
    """A dict that also supports attribute-style access (mirrors st.session_state)."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value

    def __delattr__(self, key: str) -> None:
        try:
            del self[key]
        except KeyError:
            raise AttributeError(key)


def _make_streamlit_mock(session_state: _FakeSessionState) -> types.ModuleType:
    st = types.ModuleType("streamlit")
    st.session_state = session_state  # type: ignore[attr-defined]
    st.rerun = MagicMock()            # type: ignore[attr-defined]
    return st


@pytest.fixture(autouse=True)
def fresh_session_state(monkeypatch):
    """
    Replace st.session_state with a fresh empty dict for each test and
    ensure the streamlit mock is installed in sys.modules.
    """
    ss = _FakeSessionState()
    st_mock = _make_streamlit_mock(ss)

    # Install mock so that `import streamlit as st` returns our mock
    monkeypatch.setitem(sys.modules, "streamlit", st_mock)

    # If state_manager is already imported, patch its lazy _st() reference too
    if "ai4bi.ui.state_manager" in sys.modules:
        sm = sys.modules["ai4bi.ui.state_manager"]
        # _st() does `import streamlit` dynamically — the sys.modules patch covers it
        _ = sm  # keep reference

    yield ss


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

from ai4bi.spec_models import (
    BlockRef,
    PageSpec,
    PatchOperation,
    PatchProposal,
    ReportSpec,
    VisualQuerySpec,
    apply_proposal,
    apply_proposal_strict,
)
import ai4bi.ui.state_manager as sm


def _make_visual(visual_id: str = "v1") -> VisualQuerySpec:
    return VisualQuerySpec(
        visual_id=visual_id,
        component_type="kpi",
        block_refs=[BlockRef(block_id="sales_fact")],
        metrics=["revenue"],
        dimensions=["region"],
        filters=[],
        chart_type="kpi",
        inherit_global_filter=True,
    )


def _make_page(page_id: str = "p1", visual_ids: list[str] | None = None) -> PageSpec:
    visual_ids = visual_ids or ["v1"]
    visuals = {vid: _make_visual(vid) for vid in visual_ids}
    return PageSpec(
        page_id=page_id,
        title="Test Page",
        visuals=visuals,
        visual_order=list(visual_ids),
    )


def _make_spec(
    report_id: str = "r1",
    version: int = 0,
    global_filters: dict | None = None,
) -> ReportSpec:
    return ReportSpec(
        report_id=report_id,
        pages={"p1": _make_page("p1", ["v1", "v2"])},
        global_filters=global_filters or {},
        version=version,
    )


def _replace_metrics(visual_id: str, page_id: str, new_metrics: list[str]) -> PatchProposal:
    return PatchProposal(
        operations=[
            PatchOperation(
                op="replace",
                path=f"/pages/{page_id}/visuals/{visual_id}/metrics",
                value=new_metrics,
            )
        ],
        description=f"Replace metrics on {visual_id}",
    )


# ---------------------------------------------------------------------------
# STATE-001: init_state is idempotent
# ---------------------------------------------------------------------------


class TestInitState:
    def test_init_state_idempotent(self):
        """STATE-001: calling init_state twice must NOT overwrite existing state."""
        spec1 = _make_spec(report_id="first")
        spec2 = _make_spec(report_id="second")

        sm.init_state(spec1)
        assert sm.get_current_spec().report_id == "first"

        # Second call with a different spec must be a no-op
        sm.init_state(spec2)
        assert sm.get_current_spec().report_id == "first"  # unchanged

    def test_init_state_stores_deep_copy(self):
        """Mutating the original spec after init_state must not affect the stored spec."""
        spec = _make_spec()
        sm.init_state(spec)

        # Mutate the original
        spec.report_id = "mutated"
        assert sm.get_current_spec().report_id == "r1"

    def test_init_state_initialises_empty_history(self, fresh_session_state):
        """History starts with exactly one entry (the initial spec)."""
        sm.init_state(_make_spec())
        history = fresh_session_state["_SM_history"]
        assert len(history) == 1
        assert fresh_session_state["_SM_history_ptr"] == 0

    def test_init_state_staging_is_none(self, fresh_session_state):
        """Staging slot must start as None."""
        sm.init_state(_make_spec())
        assert fresh_session_state["_SM_staging"] is None


# ---------------------------------------------------------------------------
# STATE-002: apply_proposal_to_state — basic update
# ---------------------------------------------------------------------------


class TestApplyProposal:
    def test_apply_proposal_basic(self):
        """STATE-002: applying a metrics patch must update the live spec correctly."""
        spec = _make_spec()
        sm.init_state(spec)

        proposal = _replace_metrics("v1", "p1", ["gross_profit"])
        ok = sm.apply_proposal_to_state(proposal)

        assert ok is True
        live = sm.get_current_spec()
        assert live.pages["p1"].visuals["v1"].metrics == ["gross_profit"]

    def test_apply_proposal_invalid_path_returns_false(self):
        """Patching a non-existent page must return False in lenient mode (no ops applied)."""
        sm.init_state(_make_spec())

        proposal = PatchProposal(
            operations=[
                PatchOperation(
                    op="replace",
                    path="/pages/NONEXISTENT/visuals/v1/metrics",
                    value=["x"],
                )
            ]
        )
        ok = sm.apply_proposal_to_state(proposal)
        assert ok is False

    def test_apply_proposal_strict_returns_false_on_partial_error(self):
        """Strict mode: one bad op among many must leave spec unchanged."""
        sm.init_state(_make_spec())
        original_version = sm.get_current_spec().version

        proposal = PatchProposal(
            operations=[
                PatchOperation(op="replace", path="/pages/p1/visuals/v1/metrics", value=["ok"]),
                PatchOperation(op="replace", path="/pages/MISSING/visuals/v1/metrics", value=["bad"]),
            ]
        )
        ok = sm.apply_proposal_to_state(proposal, strict=True)

        assert ok is False
        # Version must not have changed
        assert sm.get_current_spec().version == original_version


# ---------------------------------------------------------------------------
# STATE-003: version increments on each apply
# ---------------------------------------------------------------------------


class TestVersionIncrement:
    def test_apply_proposal_increments_version(self):
        """STATE-003: every successful apply must increment spec.version by exactly 1."""
        sm.init_state(_make_spec(version=0))

        for expected_version in range(1, 4):
            proposal = _replace_metrics("v1", "p1", [f"metric_{expected_version}"])
            sm.apply_proposal_to_state(proposal)
            assert sm.get_current_spec().version == expected_version

    def test_failed_apply_does_not_increment_version(self):
        """A failed apply must NOT change the version."""
        sm.init_state(_make_spec(version=5))

        bad_proposal = PatchProposal(
            operations=[PatchOperation(op="replace", path="/pages/BAD/visuals/v1/metrics", value=[])]
        )
        sm.apply_proposal_to_state(bad_proposal)
        assert sm.get_current_spec().version == 5


# ---------------------------------------------------------------------------
# STATE-004 / STATE-005: undo / redo
# ---------------------------------------------------------------------------


class TestUndoRedo:
    def _setup_with_two_changes(self):
        """Helper: init + apply two proposals; returns (spec_after_1, spec_after_2)."""
        sm.init_state(_make_spec())

        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["revenue"]))
        spec_after_1 = sm.get_current_spec().deep_copy()

        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["gross_profit"]))
        spec_after_2 = sm.get_current_spec().deep_copy()

        return spec_after_1, spec_after_2

    def test_undo_restores_previous(self):
        """STATE-004: undo() must restore the spec to the state before the last apply."""
        spec_after_1, _ = self._setup_with_two_changes()

        result = sm.undo()

        assert result is True
        live = sm.get_current_spec()
        assert live.pages["p1"].visuals["v1"].metrics == spec_after_1.pages["p1"].visuals["v1"].metrics

    def test_redo_after_undo(self):
        """STATE-005: undo then redo must restore the latest spec."""
        _, spec_after_2 = self._setup_with_two_changes()

        sm.undo()
        result = sm.redo()

        assert result is True
        live = sm.get_current_spec()
        assert live.pages["p1"].visuals["v1"].metrics == spec_after_2.pages["p1"].visuals["v1"].metrics

    def test_undo_empty_stack_returns_false(self):
        """STATE-006: undo() on an empty undo stack must return False (not raise)."""
        sm.init_state(_make_spec())

        # No changes applied yet
        result = sm.undo()
        assert result is False

        # Spec must be untouched
        assert sm.get_current_spec().report_id == "r1"

    def test_redo_at_tip_returns_false(self):
        """redo() when already at the tip of history must return False."""
        sm.init_state(_make_spec())
        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["x"]))

        result = sm.redo()
        assert result is False

    def test_can_undo_reflects_history(self):
        """can_undo() must return False before any change and True after."""
        sm.init_state(_make_spec())
        assert sm.can_undo() is False

        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["x"]))
        assert sm.can_undo() is True

    def test_can_redo_reflects_history(self):
        """can_redo() must return False at tip and True after undo."""
        sm.init_state(_make_spec())
        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["x"]))
        assert sm.can_redo() is False

        sm.undo()
        assert sm.can_redo() is True

    def test_new_apply_truncates_redo(self):
        """STATE-007: after undo, a new apply must truncate the redo branch."""
        sm.init_state(_make_spec())

        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["a"]))
        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["b"]))

        # Undo once — we can now redo to ["b"]
        sm.undo()
        assert sm.can_redo() is True

        # Apply a *new* proposal — redo branch must be truncated
        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["c"]))
        assert sm.can_redo() is False

        # Current spec must reflect the new apply, not the old redo target
        live = sm.get_current_spec()
        assert live.pages["p1"].visuals["v1"].metrics == ["c"]

    def test_multiple_undos_traverse_full_history(self):
        """Sequential undos must traverse through the full history chain."""
        sm.init_state(_make_spec())
        initial_metrics = sm.get_current_spec().pages["p1"].visuals["v1"].metrics[:]

        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["step1"]))
        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["step2"]))
        sm.apply_proposal_to_state(_replace_metrics("v1", "p1", ["step3"]))

        sm.undo()
        sm.undo()
        sm.undo()

        live = sm.get_current_spec()
        assert live.pages["p1"].visuals["v1"].metrics == initial_metrics
        assert sm.can_undo() is False


# ---------------------------------------------------------------------------
# STATE-008 / STATE-009: staging
# ---------------------------------------------------------------------------


class TestStaging:
    def test_staging_apply_confirmation(self):
        """STATE-008: requires_confirmation=True must go to staging, not be applied."""
        sm.init_state(_make_spec())
        original_version = sm.get_current_spec().version

        proposal = PatchProposal(
            operations=[
                PatchOperation(op="replace", path="/pages/p1/visuals/v1/metrics", value=["staged"])
            ],
            requires_confirmation=True,
        )
        ok = sm.apply_proposal_to_state(proposal)

        # apply_proposal_to_state returns True (accepted into staging)
        assert ok is True
        # But the live spec must NOT have changed yet
        assert sm.get_current_spec().version == original_version
        assert sm.get_current_spec().pages["p1"].visuals["v1"].metrics != ["staged"]

        # Staging slot must be populated
        assert sm.get_staging() is proposal

        # Now confirm
        confirmed = sm.confirm_staging()
        assert confirmed is True
        assert sm.get_current_spec().pages["p1"].visuals["v1"].metrics == ["staged"]
        assert sm.get_staging() is None

    def test_staging_confirm_pushes_to_undo_stack(self):
        """Confirming a staged proposal must push to undo history."""
        sm.init_state(_make_spec())

        proposal = PatchProposal(
            operations=[PatchOperation(op="replace", path="/pages/p1/visuals/v1/metrics", value=["staged"])],
            requires_confirmation=True,
        )
        sm.apply_proposal_to_state(proposal)
        sm.confirm_staging()

        # We should now be able to undo the confirmed change
        assert sm.can_undo() is True
        sm.undo()
        assert sm.get_current_spec().pages["p1"].visuals["v1"].metrics != ["staged"]

    def test_staging_reject_clears(self):
        """STATE-009: reject_staging() must clear staging without modifying the spec."""
        sm.init_state(_make_spec())
        original_metrics = sm.get_current_spec().pages["p1"].visuals["v1"].metrics[:]

        proposal = PatchProposal(
            operations=[PatchOperation(op="replace", path="/pages/p1/visuals/v1/metrics", value=["rejected"])],
            requires_confirmation=True,
        )
        sm.apply_proposal_to_state(proposal)
        sm.reject_staging()

        assert sm.get_staging() is None
        assert sm.get_current_spec().pages["p1"].visuals["v1"].metrics == original_metrics

    def test_confirm_staging_when_empty_returns_false(self):
        """confirm_staging() with nothing in staging must return False."""
        sm.init_state(_make_spec())
        result = sm.confirm_staging()
        assert result is False


# ---------------------------------------------------------------------------
# STATE-010: undo/redo over global_filters
# ---------------------------------------------------------------------------


class TestUndoRedoGlobalFilter:
    def test_undo_redo_global_filter(self):
        """STATE-010: global_filter changes must participate in undo/redo stack."""
        sm.init_state(_make_spec(global_filters={"date_range": "2024-Q1"}))

        # Change global filter
        proposal = PatchProposal(
            operations=[PatchOperation(op="replace", path="/global_filters/date_range", value="2024-Q2")]
        )
        sm.apply_proposal_to_state(proposal)
        assert sm.get_current_spec().global_filters["date_range"] == "2024-Q2"

        # Undo
        sm.undo()
        assert sm.get_current_spec().global_filters["date_range"] == "2024-Q1"

        # Redo
        sm.redo()
        assert sm.get_current_spec().global_filters["date_range"] == "2024-Q2"

    def test_add_global_filter(self):
        """Adding a new global filter key must work and be undoable."""
        sm.init_state(_make_spec())

        proposal = PatchProposal(
            operations=[PatchOperation(op="add", path="/global_filters/region", value="North")]
        )
        sm.apply_proposal_to_state(proposal)
        assert sm.get_current_spec().global_filters.get("region") == "North"

        sm.undo()
        assert "region" not in sm.get_current_spec().global_filters

    def test_remove_global_filter(self):
        """Removing an existing global filter key must work and be undoable."""
        sm.init_state(_make_spec(global_filters={"remove_me": True}))

        proposal = PatchProposal(
            operations=[PatchOperation(op="remove", path="/global_filters/remove_me", value=None)]
        )
        sm.apply_proposal_to_state(proposal)
        assert "remove_me" not in sm.get_current_spec().global_filters

        sm.undo()
        assert sm.get_current_spec().global_filters.get("remove_me") is True


# ---------------------------------------------------------------------------
# apply_ambiguity_choice
# ---------------------------------------------------------------------------


class TestAmbiguityChoice:
    def test_apply_ambiguity_choice_applies_chosen_option(self):
        """apply_ambiguity_choice must apply the selected sub-proposal."""
        sm.init_state(_make_spec())

        opt_a = PatchProposal(
            operations=[PatchOperation(op="replace", path="/pages/p1/visuals/v1/metrics", value=["option_a"])]
        )
        opt_b = PatchProposal(
            operations=[PatchOperation(op="replace", path="/pages/p1/visuals/v1/metrics", value=["option_b"])]
        )
        main_proposal = PatchProposal(
            operations=[],
            ambiguity_options=[opt_a, opt_b],
        )

        ok = sm.apply_ambiguity_choice(main_proposal, chosen_option=opt_b)

        assert ok is True
        assert sm.get_current_spec().pages["p1"].visuals["v1"].metrics == ["option_b"]


# ---------------------------------------------------------------------------
# spec_models unit tests (no StateManager)
# ---------------------------------------------------------------------------


class TestSpecModels:
    # ------------------------------------------------------------------ #
    # BlockRef                                                             #
    # ------------------------------------------------------------------ #

    def test_block_ref_round_trip(self):
        br = BlockRef(block_id="sales_fact", pinned_version="1.2.0", pin_reason="stable")
        assert BlockRef.from_dict(br.to_dict()) == br

    def test_block_ref_deep_copy_is_independent(self):
        br = BlockRef(block_id="a")
        br2 = br.deep_copy()
        br2.block_id = "b"
        assert br.block_id == "a"

    # ------------------------------------------------------------------ #
    # VisualQuerySpec                                                      #
    # ------------------------------------------------------------------ #

    def test_visual_query_spec_round_trip(self):
        v = _make_visual()
        v2 = VisualQuerySpec.from_dict(v.to_dict())
        assert v2.visual_id == v.visual_id
        assert v2.metrics == v.metrics
        assert v2.block_refs[0].block_id == v.block_refs[0].block_id

    def test_visual_query_spec_deep_copy_is_independent(self):
        v = _make_visual()
        v2 = v.deep_copy()
        v2.metrics.append("extra")
        assert "extra" not in v.metrics

    # ------------------------------------------------------------------ #
    # PageSpec                                                             #
    # ------------------------------------------------------------------ #

    def test_page_spec_post_init_validates_visual_order_consistency(self):
        """PageSpec.__post_init__ must raise ValueError on inconsistent visual_order."""
        with pytest.raises(ValueError, match="visual_order"):
            PageSpec(
                page_id="p1",
                title="T",
                visuals={"v1": _make_visual("v1")},
                visual_order=["v1", "v2"],  # v2 not in visuals
            )

    def test_page_spec_empty_visuals_and_order(self):
        """An empty page (no visuals) must be valid."""
        page = PageSpec(page_id="empty", title="Empty", visuals={}, visual_order=[])
        assert page.visuals == {}

    def test_page_spec_round_trip(self):
        page = _make_page("p1", ["v1", "v2"])
        page2 = PageSpec.from_dict(page.to_dict())
        assert page2.page_id == "p1"
        assert list(page2.visual_order) == ["v1", "v2"]

    def test_page_spec_deep_copy_is_independent(self):
        page = _make_page()
        page2 = page.deep_copy()
        page2.title = "Changed"
        assert page.title == "Test Page"

    # ------------------------------------------------------------------ #
    # ReportSpec                                                           #
    # ------------------------------------------------------------------ #

    def test_report_spec_round_trip(self):
        spec = _make_spec(report_id="rr", version=7)
        spec2 = ReportSpec.from_dict(spec.to_dict())
        assert spec2.report_id == "rr"
        assert spec2.version == 7

    def test_report_spec_deep_copy_is_independent(self):
        spec = _make_spec()
        spec2 = spec.deep_copy()
        spec2.pages["p1"].title = "Different"
        assert spec.pages["p1"].title == "Test Page"

    # ------------------------------------------------------------------ #
    # apply_proposal (module-level, no StateManager)                      #
    # ------------------------------------------------------------------ #

    def test_apply_proposal_replace_metrics_success(self):
        spec = _make_spec()
        proposal = _replace_metrics("v1", "p1", ["net_revenue"])
        result = apply_proposal(spec, proposal)

        assert result.success is True
        assert result.spec.pages["p1"].visuals["v1"].metrics == ["net_revenue"]
        assert result.spec.version == 1  # original was 0

    def test_apply_proposal_does_not_mutate_original(self):
        spec = _make_spec()
        original_metrics = spec.pages["p1"].visuals["v1"].metrics[:]
        apply_proposal(spec, _replace_metrics("v1", "p1", ["changed"]))
        assert spec.pages["p1"].visuals["v1"].metrics == original_metrics

    def test_apply_proposal_lenient_partial_success(self):
        """Lenient mode: valid op succeeds even alongside a bad op."""
        spec = _make_spec()
        proposal = PatchProposal(
            operations=[
                PatchOperation(op="replace", path="/pages/p1/visuals/v1/metrics", value=["ok"]),
                PatchOperation(op="replace", path="/pages/MISSING/visuals/v1/metrics", value=["fail"]),
            ]
        )
        result = apply_proposal(spec, proposal)

        # One succeeded — result.success reflects at least one success
        assert result.success is True
        assert result.spec.pages["p1"].visuals["v1"].metrics == ["ok"]
        assert len(result.errors) > 0  # the bad op recorded an error

    def test_apply_proposal_strict_fails_atomically(self):
        """Strict mode: one bad op must reject the entire proposal."""
        spec = _make_spec()
        proposal = PatchProposal(
            operations=[
                PatchOperation(op="replace", path="/pages/p1/visuals/v1/metrics", value=["ok"]),
                PatchOperation(op="replace", path="/pages/MISSING/visuals/v1/metrics", value=["fail"]),
            ]
        )
        result = apply_proposal_strict(spec, proposal)

        assert result.success is False
        assert result.spec.pages["p1"].visuals["v1"].metrics != ["ok"]  # unchanged
        assert len(result.errors) > 0

    def test_apply_proposal_add_global_filter(self):
        spec = _make_spec()
        proposal = PatchProposal(
            operations=[PatchOperation(op="add", path="/global_filters/period", value="2024-Q1")]
        )
        result = apply_proposal(spec, proposal)

        assert result.success is True
        assert result.spec.global_filters["period"] == "2024-Q1"

    def test_apply_proposal_remove_global_filter(self):
        spec = _make_spec(global_filters={"to_remove": "yes"})
        proposal = PatchProposal(
            operations=[PatchOperation(op="remove", path="/global_filters/to_remove", value=None)]
        )
        result = apply_proposal(spec, proposal)

        assert result.success is True
        assert "to_remove" not in result.spec.global_filters

    def test_apply_proposal_visual_order_replace(self):
        spec = _make_spec()
        # p1 has ["v1", "v2"] — swap order
        proposal = PatchProposal(
            operations=[
                PatchOperation(op="replace", path="/pages/p1/visual_order", value=["v2", "v1"])
            ]
        )
        result = apply_proposal(spec, proposal)

        assert result.success is True
        assert result.spec.pages["p1"].visual_order == ["v2", "v1"]

    def test_apply_proposal_add_visual(self):
        spec = _make_spec()
        new_visual_dict = _make_visual("v_new").to_dict()
        proposal = PatchProposal(
            operations=[
                PatchOperation(
                    op="add",
                    path="/pages/p1/visuals/v_new",
                    value=new_visual_dict,
                )
            ]
        )
        result = apply_proposal(spec, proposal)

        assert result.success is True
        assert "v_new" in result.spec.pages["p1"].visuals
        assert "v_new" in result.spec.pages["p1"].visual_order

    def test_apply_proposal_remove_visual(self):
        spec = _make_spec()  # has v1, v2
        proposal = PatchProposal(
            operations=[PatchOperation(op="remove", path="/pages/p1/visuals/v1", value=None)]
        )
        result = apply_proposal(spec, proposal)

        assert result.success is True
        assert "v1" not in result.spec.pages["p1"].visuals
        assert "v1" not in result.spec.pages["p1"].visual_order
        assert "v2" in result.spec.pages["p1"].visuals

    def test_apply_proposal_replace_chart_type(self):
        spec = _make_spec()
        proposal = PatchProposal(
            operations=[
                PatchOperation(
                    op="replace",
                    path="/pages/p1/visuals/v1/chart_type",
                    value="bar",
                )
            ]
        )
        result = apply_proposal(spec, proposal)
        assert result.success is True
        assert result.spec.pages["p1"].visuals["v1"].chart_type == "bar"

    def test_apply_proposal_replace_block_refs(self):
        spec = _make_spec()
        new_refs = [BlockRef(block_id="new_block", pinned_version="2.0.0").to_dict()]
        proposal = PatchProposal(
            operations=[
                PatchOperation(
                    op="replace",
                    path="/pages/p1/visuals/v1/block_refs",
                    value=new_refs,
                )
            ]
        )
        result = apply_proposal(spec, proposal)
        assert result.success is True
        assert result.spec.pages["p1"].visuals["v1"].block_refs[0].block_id == "new_block"

    def test_apply_proposal_unsupported_path_returns_error(self):
        spec = _make_spec()
        proposal = PatchProposal(
            operations=[PatchOperation(op="replace", path="/unknown_root/key", value="x")]
        )
        result = apply_proposal(spec, proposal)
        assert result.success is False
        assert len(result.errors) > 0

    def test_empty_proposal_increments_nothing(self):
        """A proposal with zero operations must not change version."""
        spec = _make_spec(version=3)
        result = apply_proposal(spec, PatchProposal(operations=[]))
        # No ops applied → version unchanged
        assert result.spec.version == 3
