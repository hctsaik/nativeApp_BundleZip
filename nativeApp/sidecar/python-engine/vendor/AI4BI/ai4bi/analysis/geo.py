"""Geo coordinate lookup for map visuals — Round 083.

The executor returns location *names* (city / 縣市 / region); a map needs
lat/lon. This module resolves common Taiwan administrative names (plus a few
global cities) to coordinates so a bubble map can be drawn. Names that can't be
resolved are dropped (the caller surfaces how many), so an unknown location set
degrades gracefully rather than crashing the render.

Matching is tolerant: it strips the 縣/市/區 suffix and accepts both the bare
name ("台北") and the formal one ("臺北市"), and is case-insensitive for EN.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

# Canonical name → (lat, lon). Taiwan cities/counties first, then a few globals.
_COORDS: dict[str, tuple[float, float]] = {
    "台北": (25.0330, 121.5654), "新北": (25.0169, 121.4628),
    "桃園": (24.9936, 121.3010), "台中": (24.1477, 120.6736),
    "台南": (22.9999, 120.2270), "高雄": (22.6273, 120.3014),
    "基隆": (25.1276, 121.7392), "新竹": (24.8138, 120.9675),
    "嘉義": (23.4801, 120.4491), "苗栗": (24.5602, 120.8214),
    "彰化": (24.0518, 120.5161), "南投": (23.9609, 120.9719),
    "雲林": (23.7092, 120.4313), "屏東": (22.5519, 120.5487),
    "宜蘭": (24.7021, 121.7378), "花蓮": (23.9871, 121.6015),
    "台東": (22.7583, 121.1444), "澎湖": (23.5712, 119.5793),
    "金門": (24.4321, 118.3171), "連江": (26.1608, 119.9499),
    # A few global cities for non-Taiwan datasets.
    "tokyo": (35.6762, 139.6503), "singapore": (1.3521, 103.8198),
    "hong kong": (22.3193, 114.1694), "shanghai": (31.2304, 121.4737),
    "new york": (40.7128, -74.0060), "london": (51.5074, -0.1278),
}

# Common EN ↔ canonical-ZH aliases.
_ALIASES: dict[str, str] = {
    "taipei": "台北", "new taipei": "新北", "taoyuan": "桃園",
    "taichung": "台中", "tainan": "台南", "kaohsiung": "高雄",
    "keelung": "基隆", "hsinchu": "新竹", "chiayi": "嘉義",
    "miaoli": "苗栗", "changhua": "彰化", "nantou": "南投",
    "yunlin": "雲林", "pingtung": "屏東", "yilan": "宜蘭",
    "hualien": "花蓮", "taitung": "台東", "penghu": "澎湖",
    "kinmen": "金門", "臺北": "台北", "臺中": "台中", "臺南": "台南",
    "臺東": "台東",
}

_SUFFIXES = ("縣", "市", "區")


def resolve_coords(name: str) -> Optional[tuple[float, float]]:
    """Return (lat, lon) for a location name, or None if unknown."""
    if name is None:
        return None
    key = str(name).strip()
    if not key:
        return None
    lower = key.lower()
    if lower in _COORDS:
        return _COORDS[lower]
    if lower in _ALIASES:
        return _COORDS[_ALIASES[lower]]
    if key in _COORDS:
        return _COORDS[key]
    if key in _ALIASES:
        return _COORDS[_ALIASES[key]]
    # Strip trailing 縣/市/區 and retry ("臺北市" → "臺北" → alias "台北").
    stripped = re.sub(rf"[{''.join(_SUFFIXES)}]+$", "", key)
    if stripped != key:
        return resolve_coords(stripped)
    return None


def attach_coords(df: pd.DataFrame, location_col: str) -> pd.DataFrame:
    """Return df with added ``_lat`` / ``_lon`` columns, dropping unmappable rows.

    Empty DataFrame when the column is missing or no rows resolve.
    """
    if df is None or df.empty or location_col not in df.columns:
        return pd.DataFrame()
    coords = df[location_col].map(resolve_coords)
    mask = coords.notna()
    if not mask.any():
        return pd.DataFrame()
    out = df[mask].copy()
    out["_lat"] = [c[0] for c in coords[mask]]
    out["_lon"] = [c[1] for c in coords[mask]]
    return out.reset_index(drop=True)
