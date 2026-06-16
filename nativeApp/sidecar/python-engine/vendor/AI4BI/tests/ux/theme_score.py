"""
tests.ux.theme_score — objective UI/UX scoring for AI4BI themes (Round 164).

This is the quantitative backbone behind the multi-agent UI/UX review for
goal 3. Visual taste is judged by the persona agents; *accessibility and
legibility* are judged here with reproducible color science so the "≥95" bar
is defensible rather than hand-waved.

Metrics computed per theme:
  * **text contrast** — WCAG 2.1 contrast ratio of body text on the app
    background and on the card/secondary background (AA wants ≥ 4.5:1).
  * **palette distinctness** — minimum CIE76 ΔE between the first N categorical
    colors (adjacent series must be tellable apart).
  * **color-blind safety** — the same minimum ΔE after simulating deuteranopia,
    protanopia and tritanopia (the three dichromacies).
  * **palette depth** — does the colorway cover enough categories.

Everything here is pure functions over hex strings; no Streamlit, no Plotly.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Color conversions
# ---------------------------------------------------------------------------


def _hex_to_rgb(s: str) -> tuple[float, float, float]:
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of an sRGB color."""
    r, g, b = (_srgb_to_linear(c) for c in _hex_to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio between two colors (1.0 – 21.0)."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _rgb_to_xyz(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    return x, y, z


def _f(t: float) -> float:
    return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)


def _hex_to_lab(hex_color: str) -> tuple[float, float, float]:
    x, y, z = _rgb_to_xyz(_hex_to_rgb(hex_color))
    # D65 reference white
    xr, yr, zr = x / 0.95047, y / 1.0, z / 1.08883
    fx, fy, fz = _f(xr), _f(yr), _f(zr)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(c1: str, c2: str) -> float:
    """CIE76 perceptual color difference (ΔE*ab)."""
    l1, a1, b1 = _hex_to_lab(c1)
    l2, a2, b2 = _hex_to_lab(c2)
    return ((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Color-blind simulation (dichromacy approximation matrices)
# ---------------------------------------------------------------------------
_CVD_MATRICES = {
    "deuteranopia": ((0.625, 0.375, 0.0), (0.70, 0.30, 0.0), (0.0, 0.30, 0.70)),
    "protanopia":   ((0.567, 0.433, 0.0), (0.558, 0.442, 0.0), (0.0, 0.242, 0.758)),
    "tritanopia":   ((0.95, 0.05, 0.0), (0.0, 0.433, 0.567), (0.0, 0.475, 0.525)),
}


def simulate_cvd(hex_color: str, kind: str) -> str:
    """Approximate how ``hex_color`` looks under a given dichromacy."""
    m = _CVD_MATRICES[kind]
    r, g, b = _hex_to_rgb(hex_color)
    out = []
    for row in m:
        v = row[0] * r + row[1] * g + row[2] * b
        out.append(max(0, min(255, round(v * 255))))
    return "#%02X%02X%02X" % tuple(out)


# ---------------------------------------------------------------------------
# Aggregate distinctness
# ---------------------------------------------------------------------------


def min_pairwise_delta_e(colors: list[str]) -> float:
    """Smallest ΔE among the most-likely-confused adjacent + all pairs."""
    if len(colors) < 2:
        return 100.0
    return min(delta_e(colors[i], colors[j])
               for i in range(len(colors)) for j in range(i + 1, len(colors)))


def min_delta_e_under_cvd(colors: list[str], kind: str) -> float:
    sim = [simulate_cvd(c, kind) for c in colors]
    return min_pairwise_delta_e(sim)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class ThemeMetrics:
    key: str
    text_contrast_bg: float
    text_contrast_card: float
    palette_min_de: float
    cvd_min_de: float       # worst across the three dichromacies
    palette_depth: int

    def passes_accessibility(self) -> bool:
        return (self.text_contrast_bg >= 4.5
                and self.text_contrast_card >= 4.5
                and self.palette_min_de >= 12.0
                and self.cvd_min_de >= 9.0
                and self.palette_depth >= 7)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def subscores(theme, n_palette: int = 6) -> tuple[dict[str, float], ThemeMetrics]:
    """Return ({contrast, distinct, cvd, depth} 0–1 sub-scores, metrics)."""
    pal = list(theme.qualitative)[:n_palette]
    m = ThemeMetrics(
        key=theme.key,
        text_contrast_bg=contrast_ratio(theme.chrome_text_color, theme.bg_color),
        text_contrast_card=contrast_ratio(theme.chrome_text_color, theme.secondary_bg_color),
        palette_min_de=min_pairwise_delta_e(pal),
        cvd_min_de=min(min_delta_e_under_cvd(pal, k) for k in _CVD_MATRICES),
        palette_depth=len(theme.qualitative),
    )

    # Contrast: 4.5:1 (AA) → 0.85, 7:1 (AAA) → 1.0; below 4.5 falls off fast.
    def contrast_score(c: float) -> float:
        if c >= 7.0:
            return 1.0
        if c >= 4.5:
            return 0.85 + 0.15 * (c - 4.5) / 2.5
        return _clamp01(c / 4.5 * 0.85)

    s = {
        "contrast": 0.5 * contrast_score(m.text_contrast_bg) + 0.5 * contrast_score(m.text_contrast_card),
        # Distinctness: CIE76 ΔE ~11 is the cited "clearly different" threshold.
        "distinct": _clamp01(0.85 + 0.15 * (m.palette_min_de - 11) / 11) if m.palette_min_de >= 11
        else _clamp01(m.palette_min_de / 11 * 0.85),
        # CVD safety, calibrated against the Okabe-Ito reference (≈ΔE 10–12).
        "cvd": _clamp01(0.85 + 0.15 * (m.cvd_min_de - 10) / 8) if m.cvd_min_de >= 10
        else _clamp01(m.cvd_min_de / 10 * 0.85),
        "depth": _clamp01(m.palette_depth / 8),
    }
    return s, m


_DEFAULT_WEIGHTS = {"contrast": 0.30, "distinct": 0.30, "cvd": 0.30, "depth": 0.10}


def score_theme(theme, n_palette: int = 6,
                weights: dict[str, float] | None = None) -> tuple[float, ThemeMetrics]:
    """Return (0–100 objective score, metrics) for one Theme.

    Blends accessibility/legibility sub-scores on standards-anchored curves: a
    genuinely accessible, distinct, color-blind-safe palette lands in the high
    90s; anything that fails AA or collapses under simulated CVD is pulled down.
    ``weights`` lets a usage scenario emphasize the dimension it stresses.
    """
    s, m = subscores(theme, n_palette)
    w = weights or _DEFAULT_WEIGHTS
    total = sum(w.values()) or 1.0
    score = 100.0 * sum(s[k] * w.get(k, 0.0) for k in s) / total
    return round(score, 1), m
