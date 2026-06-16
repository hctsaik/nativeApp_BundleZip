"""
ai4bi.ui.theme — Central design-system / theme registry (Round 164).

Why this module exists
----------------------
Before R164 every chart hardcoded its own colors:
  * line_chart used the saturated default Plotly colorway (#636EFA / #EF553B …)
  * bar / pie / scatter used ``px.colors.qualitative.Plotly``
  * histogram used a lone ``#4C78A8``
…so the canvas looked like a demo, not a professional business report (the
exact complaint that kicked off goal 3). There was also no
``.streamlit/config.toml`` so the app chrome was Streamlit's stock red.

This module is the single source of truth for:
  * a curated set of **professional, color-blind-aware** categorical palettes,
  * the matching app-chrome colors + font + a CSS override string, and
  * helpers that stamp any Plotly figure with the active theme
    (``apply_to_fig`` + ``colorway``).

Design goals (from the multi-agent UI/UX review):
  * muted, business-report palettes (Tableau-10 / Power BI / FT-editorial …),
  * WCAG-AA text contrast on the chosen background,
  * adjacent categorical colors stay distinguishable under deuteranopia,
  * one switchable menu; the five highest-scoring themes are the presets.

The module never imports Streamlit at module load so it stays unit-testable;
session access is wrapped in a try/except for headless contexts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Theme model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """A complete look-and-feel: chart palette + chrome + typography.

    All colors are CSS hex / rgba strings so they can be handed to both Plotly
    and a ``<style>`` block unchanged.
    """

    key: str
    label: str            # human label shown in the picker (zh-TW)
    description: str      # one-line "when to use this"
    qualitative: list[str]  # categorical colorway (>= 7 colors)
    sequential: list[str]   # low→high continuous ramp (heat / density / size)
    # chart canvas
    paper_bg: str
    plot_bg: str
    grid_color: str
    axis_color: str
    text_color: str
    font_family: str
    # semantic accents (KPI deltas / RAG / baselines)
    positive: str
    negative: str
    accent: str
    # app chrome (mirrors .streamlit/config.toml [theme] keys)
    base: str             # "light" | "dark"
    primary_color: str
    bg_color: str
    secondary_bg_color: str
    chrome_text_color: str
    # Font used for chart data-furniture (ticks/legend/labels). Defaults to
    # font_family; a serif chrome theme (editorial) overrides this to a sans
    # face so small axis text stays legible.
    chart_font: str = ""

    # -- derived helpers ---------------------------------------------------
    def color_at(self, idx: int) -> str:
        """Return the categorical color for series ``idx`` (wraps around)."""
        return self.qualitative[idx % len(self.qualitative)]


# ---------------------------------------------------------------------------
# Curated theme catalog
# ---------------------------------------------------------------------------
# Palettes are drawn from established, professionally-vetted sources:
#   * Tableau 10  — perceptually balanced categorical standard
#   * Power BI    — Microsoft's default report theme
#   * Financial Times / Economist — editorial business journalism
#   * Nord        — muted Nordic UI palette
#   * Office/Excel corporate blues — boardroom decks
# All light themes keep body text at >= 4.5:1 contrast (WCAG AA).

_SANS = "Inter, 'Segoe UI', 'Microsoft JhengHei', 'PingFang TC', sans-serif"
_SERIF = "Georgia, 'Times New Roman', 'Noto Serif TC', 'Songti TC', serif"

_THEMES: dict[str, Theme] = {}


def _register(theme: Theme) -> Theme:
    _THEMES[theme.key] = theme
    return theme


# 1. Executive — boardroom blues + a warm accent. Default theme.
_register(Theme(
    key="executive",
    label="主管簡報 Executive",
    description="沉穩的企業藍與暖色點綴，最適合給主管/客戶看的正式報告。",
    # Ordered for color-blind distinctness (navy↔gold first = safe 2-series),
    # all chromatic (no gray-as-data), none colliding with the body text color.
    qualitative=["#1F4E79", "#F4B400", "#9B59B6", "#2E86AB",
                 "#C0392B", "#70AD47", "#3E8E41", "#E1A100"],
    sequential=["#AFCBE8", "#7FA9D6", "#4E8CC4", "#2E5E8C", "#1F4E79"],
    paper_bg="rgba(0,0,0,0)",
    plot_bg="rgba(0,0,0,0)",
    grid_color="rgba(31,78,121,0.10)",
    axis_color="rgba(31,78,121,0.35)",
    text_color="#1B2A38",
    font_family=_SANS,
    positive="#2E7D32",
    negative="#C0392B",
    accent="#C55A11",
    base="light",
    primary_color="#1F4E79",
    bg_color="#FFFFFF",
    secondary_bg_color="#F4F7FB",
    chrome_text_color="#1B2A38",
))

# 2. Tableau 10 — the gold-standard categorical palette.
_register(Theme(
    key="tableau",
    label="經典 Tableau",
    description="業界公認最易辨識的分類配色，多類別、色盲友善的安全選擇。",
    # Tableau hues reordered so adjacent series stay distinct under CVD
    # (the classic red↔green pairing is split to the tail).
    qualitative=["#4E79A7", "#F28E2B", "#9C755F", "#FF9DA7", "#B6992D",
                 "#B07AA1", "#17A2B8", "#59A14F"],
    sequential=["#A9C7E0", "#7FA9CC", "#5B90BE", "#356C9E", "#1F4E79"],
    paper_bg="rgba(0,0,0,0)",
    plot_bg="rgba(0,0,0,0)",
    grid_color="rgba(90,90,90,0.12)",
    axis_color="rgba(60,60,60,0.35)",
    text_color="#2B2B2B",
    font_family=_SANS,
    positive="#59A14F",
    negative="#E15759",
    accent="#F28E2B",
    base="light",
    primary_color="#4E79A7",
    bg_color="#FFFFFF",
    secondary_bg_color="#F5F6F8",
    chrome_text_color="#2B2B2B",
))

# 3. Power BI — familiar to anyone migrating from Power BI.
_register(Theme(
    key="powerbi",
    label="Power BI 風",
    description="Power BI 預設主題色，給熟悉微軟生態的使用者最低學習成本。",
    qualitative=["#118DFF", "#E66C37", "#6B007B", "#12239E", "#E044A7",
                 "#744EC2", "#0E8A6B", "#D64550"],
    sequential=["#9FCBFF", "#6BA8F4", "#4393F4", "#1F6FD6", "#12239E"],
    paper_bg="rgba(0,0,0,0)",
    plot_bg="rgba(0,0,0,0)",
    grid_color="rgba(33,37,41,0.10)",
    axis_color="rgba(33,37,41,0.35)",
    text_color="#252423",
    font_family=_SANS,
    positive="#0E8A6B",
    negative="#D64550",
    accent="#E66C37",
    base="light",
    primary_color="#118DFF",
    bg_color="#FFFFFF",
    secondary_bg_color="#F3F2F1",
    chrome_text_color="#252423",
))

# 4. Editorial — Financial Times / Economist warm-paper journalism look.
_register(Theme(
    key="editorial",
    label="財經雜誌 Editorial",
    description="暖色報紙底 + 沉穩藍紅，帶質感的編輯風，適合敘事型報告與簡報截圖。",
    # FT/Economist hues; claret (#990F3D) kept as a later slot because it
    # collides with FT-blue under protanopia — a brighter red leads instead.
    qualitative=["#0F5499", "#C0392B", "#8C6BB1", "#D9B36A", "#593380",
                 "#A88E5A", "#990F3D", "#B8860B"],
    sequential=["#F2BC8E", "#E89C6B", "#CE6A3C", "#A6431F", "#7A2A0F"],
    paper_bg="rgba(0,0,0,0)",
    plot_bg="rgba(0,0,0,0)",
    grid_color="rgba(120,90,60,0.14)",
    axis_color="rgba(90,60,40,0.40)",
    text_color="#33291E",
    font_family=_SERIF,
    positive="#1C7C54",
    negative="#990F3D",
    accent="#990F3D",
    base="light",
    primary_color="#0F5499",
    bg_color="#FFF1E5",
    secondary_bg_color="#FBEAD9",
    chrome_text_color="#33291E",
    chart_font=_SANS,  # serif chrome, but sans inside charts for tick legibility
))

# 5. Nordic — muted, desaturated, lots of whitespace; calm analyst workspace.
_register(Theme(
    key="nordic",
    label="北歐簡約 Nordic",
    description="低飽和的冷色系，長時間盯著也不刺眼，適合日常探索與分析。",
    # Nord aurora+frost; dropped the polar-night near-black (it read as the
    # text color) and spread across the full hue wheel for distinctness.
    qualitative=["#5E81AC", "#88C0D0", "#7FA650", "#EBCB8B", "#D08770",
                 "#B48EAD", "#BF616A", "#81A1C1"],
    sequential=["#B8C9DE", "#9FB8D4", "#7393BC", "#516E96", "#3B5273"],
    paper_bg="rgba(0,0,0,0)",
    plot_bg="rgba(0,0,0,0)",
    grid_color="rgba(76,86,106,0.12)",
    axis_color="rgba(76,86,106,0.40)",
    text_color="#2E3440",
    font_family=_SANS,
    positive="#A3BE8C",
    negative="#BF616A",
    accent="#5E81AC",
    base="light",
    primary_color="#5E81AC",
    bg_color="#FFFFFF",
    secondary_bg_color="#ECEFF4",
    chrome_text_color="#2E3440",
))

# 6. Midnight — dark dashboard for control rooms / fab floor monitors.
_register(Theme(
    key="midnight",
    label="深色 Midnight",
    description="深色儀表板，適合大螢幕監控與低光環境（如產線/機房）。",
    # Okabe-Ito — the published color-blind-safe categorical reference,
    # ordered for maximum distinctness in the first six series.
    qualitative=["#56B4E9", "#D55E00", "#CC79A7", "#009E73", "#F0E442",
                 "#E69F00", "#999999", "#0072B2"],
    sequential=["#10243E", "#163A5F", "#1F5A8C", "#2E7CB8", "#4C9AFF", "#8FC0FF"],
    paper_bg="rgba(0,0,0,0)",
    plot_bg="rgba(0,0,0,0)",
    grid_color="rgba(255,255,255,0.08)",
    axis_color="rgba(255,255,255,0.25)",
    text_color="#E6EAF0",
    font_family=_SANS,
    positive="#36B37E",
    negative="#FF5630",
    accent="#4C9AFF",
    base="dark",
    primary_color="#4C9AFF",
    bg_color="#0E1117",
    secondary_bg_color="#1A1F2B",
    chrome_text_color="#E6EAF0",
))


# ---------------------------------------------------------------------------
# Presets: the five highest-scoring themes from the multi-agent UI/UX review.
# Objective scores (accessibility + CVD-safety + distinctness, see
# tests/ux/theme_score.py): tableau 100 · powerbi 100 · executive 100 ·
# nordic 99.7 · editorial 99.4 · midnight 96.3 (6th → not a saved preset).
# We lead the picker with executive (the corporate default) for a professional
# first impression, then the rest. See docs/theme-ux-validation.md.
# ---------------------------------------------------------------------------
PRESET_ORDER: list[str] = ["executive", "tableau", "powerbi", "nordic", "editorial"]
DEFAULT_THEME_KEY: str = "executive"

_SESSION_KEY = "_active_theme_key"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def all_themes() -> dict[str, Theme]:
    """Return the full theme catalog (insertion order)."""
    return dict(_THEMES)


def preset_themes() -> list[Theme]:
    """Return the curated top-5 presets, best-first, for the picker."""
    return [_THEMES[k] for k in PRESET_ORDER if k in _THEMES]


def get_theme(key: Optional[str]) -> Theme:
    """Resolve a theme by key, falling back to the default."""
    if key and key in _THEMES:
        return _THEMES[key]
    return _THEMES[DEFAULT_THEME_KEY]


def get_active_theme() -> Theme:
    """Return the theme selected in this session (default when headless)."""
    try:
        import streamlit as st
        return get_theme(st.session_state.get(_SESSION_KEY))
    except Exception:  # noqa: BLE001 — no script-run context (tests / import)
        return _THEMES[DEFAULT_THEME_KEY]


def set_active_theme(key: str) -> None:
    """Persist the chosen theme into session state."""
    try:
        import streamlit as st
        st.session_state[_SESSION_KEY] = key
    except Exception:  # noqa: BLE001
        pass


def colorway(theme: Optional[Theme] = None) -> list[str]:
    """Categorical color sequence for ``color_discrete_sequence=`` in px calls."""
    return list((theme or get_active_theme()).qualitative)


def _relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of an sRGB hex color (0=black … 1=white)."""
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except (ValueError, IndexError):
        return 1.0

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


_INK = "#16202B"   # near-black ink for light surfaces


def on_color(background_hex: str) -> str:
    """Return the most legible text color for the given background.

    The rule the user asked us to always honor: text must contrast with its
    surface (a dark background needs white text). Rather than a fixed luminance
    cut-off, we pick whichever of white / dark-ink gives the higher WCAG
    contrast ratio — so a deep navy gets white, while a bright accent like
    #118DFF correctly gets dark ink (which reads better there).
    """
    bg = _relative_luminance(background_hex)
    white_contrast = (1.0 + 0.05) / (bg + 0.05)
    dark_contrast = (bg + 0.05) / (_relative_luminance(_INK) + 0.05)
    return "#FFFFFF" if white_contrast >= dark_contrast else _INK


def on_accent(background_hex: str) -> str:
    """Text color for a *filled accent* (e.g. a primary button).

    The user's convention: a colored/dark accent should get **white** text.
    We honor that whenever white clears WCAG-AA for large/UI text (>= 3:1),
    and only fall back to dark ink for an accent too light for white (so the
    label never drops below AA-large). All our theme primaries are dark enough
    for white except a very bright one like midnight's #4C9AFF.
    """
    bg = _relative_luminance(background_hex)
    white_contrast = (1.0 + 0.05) / (bg + 0.05)
    return "#FFFFFF" if white_contrast >= 3.0 else _INK


def apply_to_fig(fig, theme: Optional[Theme] = None):
    """Stamp a Plotly figure with the active theme.

    Safe to call on any go.Figure or px figure AFTER it is built. It overrides
    backgrounds, fonts, gridlines, axis lines and the colorway so every chart
    type looks consistent. It does NOT recolor traces that already carry an
    explicit per-trace color (px sets those at build time) — callers should pass
    ``color_discrete_sequence=colorway(theme)`` to px to get the palette there.
    """
    th = theme or get_active_theme()
    chart_font = th.chart_font or th.font_family
    fig.update_layout(
        paper_bgcolor=th.paper_bg,
        plot_bgcolor=th.plot_bg,
        colorway=list(th.qualitative),
        font=dict(family=chart_font, color=th.text_color, size=14),
        title_font=dict(family=chart_font, color=th.text_color, size=16),
        legend=dict(font=dict(family=chart_font, color=th.text_color)),
    )
    fig.update_xaxes(
        gridcolor=th.grid_color,
        linecolor=th.axis_color,
        zerolinecolor=th.grid_color,
        tickfont=dict(family=chart_font, color=th.text_color),
        title_font=dict(family=chart_font, color=th.text_color),
    )
    fig.update_yaxes(
        gridcolor=th.grid_color,
        linecolor=th.axis_color,
        zerolinecolor=th.grid_color,
        tickfont=dict(family=chart_font, color=th.text_color),
        title_font=dict(family=chart_font, color=th.text_color),
    )
    return fig


def app_css(theme: Optional[Theme] = None) -> str:
    """Return a ``<style>`` block that re-skins the Streamlit chrome at runtime.

    ``.streamlit/config.toml`` sets the base theme at startup, but it can't be
    changed without a restart. Injecting this CSS lets the user switch themes
    live: it recolors the primary accent, app/sidebar background, text and the
    bordered containers that wrap each visual.
    """
    th = theme or get_active_theme()
    on_primary = on_accent(th.primary_color)  # prefer white on the accent (AA-large)
    on_secondary = on_color(th.bg_color)  # readable on the (white) button surface
    return f"""
<style>
:root {{
  --ai4bi-primary: {th.primary_color};
  --ai4bi-bg: {th.bg_color};
  --ai4bi-bg2: {th.secondary_bg_color};
  --ai4bi-text: {th.chrome_text_color};
  --ai4bi-on-primary: {on_primary};
}}
.stApp {{ background-color: {th.bg_color}; }}
section[data-testid="stSidebar"] {{ background-color: {th.secondary_bg_color}; }}
/* Body/content text (markdown, headings, widget labels) — scoped to content
   containers, NOT raw span/p, so it never bleeds into BaseWeb widget internals
   (e.g. multiselect tag pills) and wash out their own text color. Buttons below
   re-assert their label color with !important. */
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stMarkdownContainer"] li,
.stApp [data-testid="stMarkdownContainer"] h1,
.stApp [data-testid="stMarkdownContainer"] h2,
.stApp [data-testid="stMarkdownContainer"] h3,
.stApp [data-testid="stMarkdownContainer"] h4,
.stApp [data-testid="stHeading"],
.stApp [data-testid="stWidgetLabel"] p,
.stApp [data-testid="stWidgetLabel"] label {{ color: {th.chrome_text_color}; }}
body, .stApp {{ font-family: {th.font_family}; }}
/* Buttons: colored background → contrast-checked text. Streamlit 1.5x marks the
   button kind with data-testid="stBaseButton-<kind>" (NOT kind="..."), so we
   target the testid prefix (primary matches primary+primaryFormSubmit; secondary
   matches secondary+secondaryFormSubmit; download's inner button is
   stBaseButton-secondary). Legacy kind="..." kept as a fallback. !important +
   the descendant rule beat the body-text color rule above. */
button[data-testid^="stBaseButton-primary"],
.stButton > button[kind="primary"],
.stButton > button[kind="primaryFormSubmit"] {{
  background-color: {th.primary_color} !important;
  border-color: {th.primary_color} !important;
  color: {on_primary} !important;
}}
button[data-testid^="stBaseButton-primary"] *,
.stButton > button[kind="primary"] *,
.stButton > button[kind="primaryFormSubmit"] * {{ color: {on_primary} !important; }}
button[data-testid^="stBaseButton-primary"]:hover,
button[data-testid^="stBaseButton-primary"]:focus,
button[data-testid^="stBaseButton-primary"]:active {{
  color: {on_primary} !important;
  filter: brightness(1.08);
}}
/* Secondary / tertiary / download buttons → white (page) surface, outlined,
   with readable text. (White-bg outline button — the look the user asked for.) */
button[data-testid^="stBaseButton-secondary"],
button[data-testid^="stBaseButton-tertiary"],
.stButton > button[kind="secondary"],
.stButton > button[kind="tertiary"] {{
  background-color: {th.bg_color} !important;
  border-color: {th.axis_color} !important;
  color: {on_secondary} !important;
}}
button[data-testid^="stBaseButton-secondary"] *,
button[data-testid^="stBaseButton-tertiary"] *,
.stButton > button[kind="secondary"] *,
.stButton > button[kind="tertiary"] * {{ color: {on_secondary} !important; }}
/* bordered visual cards inherit a subtle themed surface */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  border-color: {th.grid_color};
}}
/* tabs + radio active state */
.stTabs [aria-selected="true"] {{ color: {th.primary_color}; }}
</style>
"""


def config_toml(theme: Optional[Theme] = None) -> str:
    """Render a ``[theme]`` block for ``.streamlit/config.toml`` (startup chrome)."""
    th = theme or _THEMES[DEFAULT_THEME_KEY]
    font = "sans serif" if th.base == "light" else "sans serif"
    return (
        "[theme]\n"
        f'base = "{th.base}"\n'
        f'primaryColor = "{th.primary_color}"\n'
        f'backgroundColor = "{th.bg_color}"\n'
        f'secondaryBackgroundColor = "{th.secondary_bg_color}"\n'
        f'textColor = "{th.chrome_text_color}"\n'
        f'font = "{font}"\n'
    )
