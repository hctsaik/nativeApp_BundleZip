"""
tests.ux.test_theme_quality — regression guard for the goal-3 theme system.

Locks in the UI/UX quality bar reached by the multi-agent review (Round 164):
  * every saved preset passes the hard accessibility gate (WCAG-AA text,
    distinctness, color-blind safety, palette depth),
  * every preset's objective score is >= 95,
  * all five presets exist and the default is among them,
  * every chart-usage scenario scores >= 95 with its recommended theme.

These assertions fail loudly if a future palette tweak regresses contrast or
color-blind separation.
"""

from __future__ import annotations

import pytest

from ai4bi.ui import theme
from tests.ux.theme_score import score_theme
from tests.ux.scenarios import SCENARIOS, score_scenario


def test_presets_exist_and_default_is_preset():
    assert len(theme.PRESET_ORDER) == 5
    assert theme.DEFAULT_THEME_KEY in theme.PRESET_ORDER
    for key in theme.PRESET_ORDER:
        assert key in theme.all_themes()


@pytest.mark.parametrize("key", theme.PRESET_ORDER)
def test_preset_passes_accessibility(key):
    score, metrics = score_theme(theme.get_theme(key))
    assert metrics.passes_accessibility(), (
        f"{key} fails accessibility: txt_bg={metrics.text_contrast_bg:.2f} "
        f"txt_card={metrics.text_contrast_card:.2f} palΔE={metrics.palette_min_de:.1f} "
        f"cvdΔE={metrics.cvd_min_de:.1f} depth={metrics.palette_depth}"
    )
    assert score >= 95.0, f"{key} objective score {score} < 95"


def test_all_themes_pass_accessibility():
    # even the non-preset dark theme must clear the accessibility gate.
    for key, th in theme.all_themes().items():
        _, m = score_theme(th)
        assert m.passes_accessibility(), f"{key} fails accessibility gate"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.sid)
def test_scenario_scores_at_least_95(scenario):
    score, used = score_scenario(scenario)
    assert score >= 95.0, f"scenario {scenario.sid} ({used}) scored {score} < 95"


def test_scenario_average_above_95():
    scores = [score_scenario(s)[0] for s in SCENARIOS]
    assert sum(scores) / len(scores) >= 95.0


def test_on_color_picks_readable_text_for_any_background():
    """on_color must pick the higher-contrast text for any surface, and the
    primary-button label must clear WCAG-AA for large/UI text (>= 3:1)."""
    from ai4bi.ui.theme import on_color, _INK
    from tests.ux.theme_score import contrast_ratio
    assert on_color("#000000") == "#FFFFFF"
    assert on_color("#FFFFFF") == _INK  # light bg → dark ink
    for key, th in theme.all_themes().items():
        ink = on_color(th.primary_color)
        chosen = contrast_ratio(ink, th.primary_color)
        other = contrast_ratio("#FFFFFF" if ink == _INK else _INK, th.primary_color)
        # it really is the better of the two options…
        assert chosen >= other, f"{key}: on_color picked the lower-contrast text"
        # …and clears AA for large/bold button text.
        assert chosen >= 3.0, (
            f"{key}: primary button text {ink} on {th.primary_color} = {chosen:.2f} < 3:1"
        )


def test_on_accent_prefers_white_and_clears_aa_large():
    """Filled accents (primary buttons): white when it clears AA-large (3:1),
    dark ink only when white can't — and the chosen text always >= 3:1."""
    from ai4bi.ui.theme import on_accent
    from tests.ux.theme_score import contrast_ratio
    for key, th in theme.all_themes().items():
        ink = on_accent(th.primary_color)
        cr = contrast_ratio(ink, th.primary_color)
        assert cr >= 3.0, f"{key}: button text {ink} on {th.primary_color} = {cr:.2f} < 3:1"
        # white must be used unless it would fail AA-large
        if contrast_ratio("#FFFFFF", th.primary_color) >= 3.0:
            assert ink == "#FFFFFF", f"{key}: should use white on {th.primary_color}"


def test_app_css_targets_streamlit_1_5x_button_testids():
    """Streamlit 1.5x marks buttons with data-testid='stBaseButton-<kind>', not
    kind='...'. The injected CSS must target those testids or the contrast-checked
    label color never applies (the bug where a primary button kept dark text)."""
    css = theme.app_css(theme.get_theme("executive"))
    assert 'stBaseButton-primary' in css
    assert 'stBaseButton-secondary' in css
    # and the primary label is white on the (dark) executive accent
    assert "#FFFFFF !important" in css


def test_secondary_surface_text_is_legible():
    """Secondary/download buttons use the (white) page surface — its text must
    clear WCAG-AA (4.5:1)."""
    from ai4bi.ui.theme import on_color
    from tests.ux.theme_score import contrast_ratio
    for key, th in theme.all_themes().items():
        assert contrast_ratio(on_color(th.bg_color), th.bg_color) >= 4.5, key


def test_no_palette_color_equals_text_color():
    # a categorical color must not masquerade as the body text color.
    from tests.ux.theme_score import delta_e
    for key, th in theme.all_themes().items():
        for c in th.qualitative[:6]:
            assert delta_e(c, th.text_color) >= 12, (
                f"{key}: series color {c} too close to text {th.text_color}"
            )
