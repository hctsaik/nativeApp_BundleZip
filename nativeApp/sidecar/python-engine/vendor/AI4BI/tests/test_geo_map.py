"""Round 083: geo coordinate lookup + map visual registration."""

from __future__ import annotations

import pandas as pd

from ai4bi.analysis.geo import attach_coords, resolve_coords
from ai4bi.query_spec import VisualType


def test_resolve_taiwan_cities():
    assert resolve_coords("台北") is not None
    assert resolve_coords("高雄") is not None
    # formal name with 市 suffix and traditional 臺 form
    assert resolve_coords("臺北市") == resolve_coords("台北")
    # EN alias, case-insensitive
    assert resolve_coords("Taipei") == resolve_coords("台北")
    assert resolve_coords("KAOHSIUNG") == resolve_coords("高雄")


def test_resolve_unknown_returns_none():
    assert resolve_coords("Atlantis") is None
    assert resolve_coords("") is None
    assert resolve_coords(None) is None


def test_attach_coords_adds_latlon_and_drops_unknown():
    df = pd.DataFrame({
        "city": ["台北", "台中", "Atlantis", "高雄"],
        "營收": [100, 80, 50, 90],
    })
    out = attach_coords(df, "city")
    assert len(out) == 3  # Atlantis dropped
    assert "_lat" in out.columns and "_lon" in out.columns
    assert set(out["city"]) == {"台北", "台中", "高雄"}
    assert out["_lat"].notna().all()


def test_attach_coords_missing_column():
    df = pd.DataFrame({"x": [1, 2]})
    assert attach_coords(df, "city").empty


def test_attach_coords_all_unknown():
    df = pd.DataFrame({"city": ["Atlantis", "Narnia"], "v": [1, 2]})
    assert attach_coords(df, "city").empty


def test_map_visual_is_registered():
    # The previously-dead VisualType.map enum now has a renderer.
    from ai4bi.ui.render_visual import _COMPONENT_REGISTRY
    assert VisualType.map in _COMPONENT_REGISTRY
    assert _COMPONENT_REGISTRY[VisualType.map] is not None


def test_map_keyword_routes_to_map_type():
    from ai4bi.ai.nl2proposal import _ADD_VISUAL_TYPE_KEYWORDS
    assert _ADD_VISUAL_TYPE_KEYWORDS["地圖"] == VisualType.map
    assert _ADD_VISUAL_TYPE_KEYWORDS["map"] == VisualType.map
