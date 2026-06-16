"""PDF report export — Round 075.

A board-ready PDF of the whole report, one visual per page, using matplotlib's
PdfPages (no extra dependencies — reportlab/kaleido are not installed). Charts
render as matplotlib figures; KPIs as big numbers; tables/pivots/histograms as
matplotlib tables. Reuses the dashboard's post-processing so numbers match.
"""

from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from ai4bi.analysis.postprocess import apply_postprocess
from ai4bi.query_spec import VisualType

# Best-effort CJK font so Chinese titles/labels aren't tofu.
for _f in ("Microsoft JhengHei", "Microsoft YaHei", "SimHei",
           "Noto Sans CJK TC", "PingFang TC", "Heiti TC"):
    try:
        if _f in {ff.name for ff in matplotlib.font_manager.fontManager.ttflist}:
            matplotlib.rcParams["font.sans-serif"] = [_f]
            matplotlib.rcParams["axes.unicode_minus"] = False
            break
    except Exception:  # noqa: BLE001
        pass


def _dims_metric(query):
    dims = [d.alias or d.column_name for d in query.dimensions]
    metric = (query.metrics[0].alias or query.metrics[0].metric_name) if query.metrics else None
    return dims, metric


def _render_visual_page(pdf: PdfPages, title: str, vtype: VisualType, df, query) -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    fig.suptitle(title, fontsize=15, fontweight="bold")
    dims, metric = _dims_metric(query)
    try:
        if vtype == VisualType.kpi_card and metric and metric in df.columns:
            ax.axis("off")
            ax.text(0.5, 0.5, f"{df[metric].iloc[0]:,.0f}", ha="center", va="center", fontsize=40)
        elif vtype in (VisualType.bar_chart,) and dims and metric and dims[0] in df and metric in df:
            ax.bar(df[dims[0]].astype(str), df[metric])
            ax.tick_params(axis="x", rotation=45)
        elif vtype == VisualType.line_chart and dims and metric and dims[0] in df and metric in df:
            ax.plot(df[dims[0]].astype(str), df[metric], marker="o")
            ax.tick_params(axis="x", rotation=45)
        elif vtype == VisualType.pie_chart and dims and metric and dims[0] in df and metric in df:
            ax.pie(df[metric], labels=df[dims[0]].astype(str), autopct="%1.0f%%")
        else:
            # table / pivot / histogram / scatter / fallback → render as a table
            ax.axis("off")
            shown = df.head(20)
            tbl = ax.table(cellText=shown.astype(str).values,
                           colLabels=list(shown.columns), loc="center")
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(8)
    except Exception:  # noqa: BLE001 — never let one visual break the PDF
        ax.axis("off")
        ax.text(0.5, 0.5, "(無法繪製此視覺)", ha="center", va="center")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf.savefig(fig)
    plt.close(fig)


def build_report_pdf(report, executor, active_filters=None) -> bytes:
    """Return a multi-page PDF (one visual per page) of the report."""
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        # cover page
        cover, ax = plt.subplots(figsize=(11, 6))
        ax.axis("off")
        ax.text(0.5, 0.6, report.title, ha="center", va="center", fontsize=24, fontweight="bold")
        ax.text(0.5, 0.45, f"報表 ID: {report.audit.report_id}", ha="center", va="center", fontsize=11)
        pdf.savefig(cover)
        plt.close(cover)

        wrote = False
        for page in report.pages.values():
            for vid in page.visual_order:
                visual = page.visuals[vid]
                try:
                    df = executor.run(visual.query, active_filters)
                    df = apply_postprocess(df, visual.query, visual.visualization)
                except Exception:  # noqa: BLE001
                    continue
                if df is None or df.empty:
                    continue
                title = visual.visualization.title or vid
                _render_visual_page(pdf, title, visual.visualization.visual_type, df, visual.query)
                wrote = True
        if not wrote:
            blank, ax = plt.subplots(figsize=(11, 6))
            ax.axis("off")
            ax.text(0.5, 0.5, "目前沒有可匯出的資料", ha="center", va="center", fontsize=14)
            pdf.savefig(blank)
            plt.close(blank)
    return buf.getvalue()
