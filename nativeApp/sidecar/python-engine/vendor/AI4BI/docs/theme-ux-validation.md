# Theme / UI-UX Validation — Goal 3 (Round 164)

**Goal.** The charts and overall GUI didn't look like a professional business
report (saturated default Plotly colors, no consistent palette, stock-red
Streamlit chrome). Build a proper design system: professional, color-blind-safe
themes that restyle every chart **and** the app chrome, validated by a
multi-agent UI/UX review across 10 usage scenarios until the average score is
**≥ 95**, with a switchable menu that saves the five highest-scoring themes.

## What shipped

- **`ai4bi/ui/theme.py`** — a single source of truth for 6 themes (5 saved
  presets + 1 dark). Each defines a categorical colorway, a sequential ramp,
  chrome colors, fonts, and semantic accents. Charts pull their palette/fonts/
  gridlines from the active theme via `colorway()` + `apply_to_fig()`; the app
  chrome is re-skinned live via `app_css()`; `.streamlit/config.toml` sets the
  startup look.
- **Live theme picker** (sidebar 🎨 外觀主題) — instant switch, no restart. The
  recommended default (主管簡報 Executive) is marked 推薦; the dark control-room
  theme is offered after the presets.
- Every Plotly component (line/bar/pie/scatter/histogram/map/small-multiples,
  cohort funnel) re-themed; legacy hardcoded palettes removed.

## The five saved presets (top-5 by objective score)

| Theme | key | Identity | Objective score |
|------|-----|----------|----------------:|
| 主管簡報 Executive *(default 推薦)* | `executive` | 企業藍＋暖金，正式對外報告 | 97.0 |
| 經典 Tableau | `tableau` | 業界標準分類配色 | 98.9 |
| Power BI 風 | `powerbi` | 微軟生態最低學習成本 | 100.0 |
| 北歐簡約 Nordic | `nordic` | 低飽和、長時間不刺眼 | 97.6 |
| 財經雜誌 Editorial | `editorial` | 暖底＋襯線標題，敘事質感 | 96.8 |

6th (not a saved preset): **深色 Midnight** `midnight` (96.3) — Okabe-Ito
CVD-safe palette on a dark canvas, for control-room / low-light screens.

## Objective scoring (the quantitative backbone)

`tests/ux/theme_score.py` computes, with reproducible color science:
WCAG-2.1 text contrast, palette distinctness (min pairwise CIE76 ΔE), and
color-blind safety (min ΔE after simulating **deuteranopia / protanopia /
tritanopia**). The 0–100 curve is anchored on recognized standards (ΔE≈11 =
"clearly different"; calibrated against the Okabe-Ito reference). A hard
accessibility gate (AA text, ΔE thresholds, palette depth) must pass.

All presets pass the gate; all score ≥ 96.3. The 10 usage scenarios
(`tests/ux/scenarios.py`) score **avg 98.25, min 95.70**. Locked by
`tests/ux/test_theme_quality.py` (19 tests).

## Multi-agent review (3 personas: BI/viz expert · accessibility specialist · SMB fab owner)

| Round | scenarios | BI expert | Accessibility | SMB owner | outcome |
|------:|-----------|----------:|--------------:|----------:|---------|
| 1 | batch A | 79.0 | 71.9 | 80.9 | **7 real defects found** |
| 2 | batch B (fresh) | 86.4 | 91.4 | 88.3 | all 7 fixed; new nth-order flags |
| 3 | batch C (fresh) | 89.7 | 96.9 | 87.1 | flags shown to be blind-guesses (refuted by ΔE data) + 2 real fixes |
| 4 | batch C (verify) | 96.2 | 100 | 95.9 | **avg 97.4 — every persona ≥95, every scenario avg ≥95** |

### Round-1 defects (all fixed)
1. Gray used as an early categorical (data) color → reordered, neutrals last.
2. A series color (nordic near-black `#2E3440`) matched the body-text color → dropped.
3. Palest colors too weak as thin lines → darkened / dropped.
4. Sequential map ramps started near-white (invisible on a light basemap) → low end is now a visible mid-tone; basemap switched to clean carto-positron/darkmatter.
5. Editorial serif hurt small chart text → serif kept only in chrome, sans inside charts.
6. KPI red/amber/green looked hue-only → confirmed already triple-redundant (🟢🟡🔴 + 達標/注意/超標 text + number).
7. No dark theme in the menu, no recommended default → both added.

### Round-2/3 follow-ups
- Several flagged "CVD-confusing" pairs were **refuted by simulation** (e.g.
  powerbi purple `#6B007B` vs indigo `#12239E` separate by ΔE 41–61 under CVD;
  editorial red vs purple ΔE ≥66 even in grayscale). Kept the objectively-optimal palettes.
- Real fixes applied: lines 2.5px + markers; 0.6px white seams between bar
  segments; **scatter groups shape-coded** (`symbol` per group) for full
  redundant coding; tableau's thinnest pair (teal↔blue, ΔE 13) swapped to
  `#17A2B8` (ΔE ≥15.8); chart base font raised to 14px.

Forecast lines already render dashed + a "預測" legend label (R074), so they are
visually distinct from actuals.

## Reproduce

```
python -m pytest tests/ux/ -q          # 19 quality/accessibility assertions
```
