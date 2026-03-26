"""
tools/charter.py — Chart renderer.

Takes structured data from Claude and produces a Matplotlib figure,
returned as a base64-encoded PNG string ready for an HTML <img> tag:

    <img src="data:image/png;base64,{chart_b64}" />

Supported chart types: bar, line, pie, scatter
"""

import io
import base64
from typing import Any

import matplotlib
matplotlib.use("Agg")           # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

PALETTE = [
    "#4F8EF7",   # blue
    "#F7934F",   # orange
    "#4FC48E",   # green
    "#F74F6A",   # red
    "#A44FF7",   # purple
    "#F7D34F",   # yellow
    "#4FF7F0",   # cyan
    "#F74FC4",   # pink
]

plt.rcParams.update({
    "figure.facecolor":  "#ffffff",
    "axes.facecolor":    "#f8f9fa",
    "axes.edgecolor":    "#dee2e6",
    "axes.labelcolor":   "#343a40",
    "axes.titlesize":    14,
    "axes.titleweight":  "semibold",
    "axes.titlepad":     12,
    "axes.labelsize":    11,
    "axes.grid":         True,
    "grid.color":        "#e9ecef",
    "grid.linewidth":    0.7,
    "xtick.color":       "#495057",
    "ytick.color":       "#495057",
    "xtick.labelsize":   9,
    "ytick.labelsize":   9,
    "legend.fontsize":   9,
    "legend.framealpha": 0.9,
    "figure.dpi":        130,
    "font.family":       "sans-serif",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _abbreviate(labels: list, max_len: int = 14) -> list[str]:
    """Truncate long tick labels so they don't crowd the axis."""
    return [str(l)[:max_len] + ("…" if len(str(l)) > max_len else "") for l in labels]


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Chart renderers
# ---------------------------------------------------------------------------

def _bar_chart(ax, x_values, series: dict, x_label: str, y_label: str):
    import numpy as np

    series_names = [k for k in series if k != "x_values"]
    n_series = len(series_names)
    x = np.arange(len(x_values))
    width = min(0.7 / max(n_series, 1), 0.35)

    for i, name in enumerate(series_names):
        offset = (i - (n_series - 1) / 2) * width
        values = [float(v) if v is not None else 0 for v in series[name]]
        bars = ax.bar(x + offset, values, width, label=name, color=PALETTE[i % len(PALETTE)],
                      edgecolor="white", linewidth=0.5, zorder=3)

        # Value labels on top of bars
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    h * 1.01,
                    f"{h:,.0f}",
                    ha="center", va="bottom", fontsize=7.5, color="#495057",
                )

    ax.set_xticks(x)
    ax.set_xticklabels(_abbreviate(x_values), rotation=30, ha="right")
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    if n_series > 1:
        ax.legend()


def _line_chart(ax, x_values, series: dict, x_label: str, y_label: str):
    series_names = [k for k in series if k != "x_values"]
    for i, name in enumerate(series_names):
        values = [float(v) if v is not None else 0 for v in series[name]]
        ax.plot(x_values, values, marker="o", markersize=4, linewidth=2,
                label=name, color=PALETTE[i % len(PALETTE)], zorder=3)

    ax.set_xticklabels(_abbreviate(x_values), rotation=30, ha="right")
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    if len(series_names) > 1:
        ax.legend()


def _pie_chart(ax, x_values, series: dict, x_label: str):
    # For pie, use the first non-x_values series as the values
    series_names = [k for k in series if k != "x_values"]
    if not series_names:
        ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center")
        return

    values = [float(v) if v is not None else 0 for v in series[series_names[0]]]
    labels = _abbreviate(x_values)

    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        colors=PALETTE[: len(values)],
        startangle=140,
        wedgeprops={"edgecolor": "white", "linewidth": 1.2},
        pctdistance=0.82,
    )
    for at in autotexts:
        at.set_fontsize(8)
        at.set_color("white")
    ax.set_xlabel("")    # no x-label for pie


def _scatter_chart(ax, x_values, series: dict, x_label: str, y_label: str):
    series_names = [k for k in series if k != "x_values"]
    x_numeric = list(range(len(x_values)))

    for i, name in enumerate(series_names):
        values = [float(v) if v is not None else 0 for v in series[name]]
        ax.scatter(x_numeric, values, label=name, color=PALETTE[i % len(PALETTE)],
                   s=60, edgecolors="white", linewidths=0.5, zorder=3)

    ax.set_xticks(x_numeric)
    ax.set_xticklabels(_abbreviate(x_values), rotation=30, ha="right")
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    if len(series_names) > 1:
        ax.legend()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def render_chart(
    chart_type: str,
    title: str,
    x_label: str,
    y_label: str,
    data: dict[str, Any],
) -> dict[str, str]:
    """
    Render a chart and return its base64 PNG.

    Args:
        chart_type: "bar" | "line" | "pie" | "scatter"
        title:      Chart title.
        x_label:    X-axis label (also used as slice label header for pie).
        y_label:    Y-axis label (ignored for pie).
        data:       Must contain "x_values" key plus one or more series keys,
                    each mapping to a list of numeric values of the same length.

    Returns:
        {"chart_b64": "<base64 string>"}   on success
        {"error": "..."}                   on failure
    """
    x_values = data.get("x_values", [])
    if not x_values:
        return {"error": "data.x_values is required and cannot be empty."}

    series = {k: v for k, v in data.items() if k != "x_values"}
    if not series:
        return {"error": "data must contain at least one series besides x_values."}

    # Validate series lengths match x_values
    for name, values in series.items():
        if len(values) != len(x_values):
            return {
                "error": (
                    f"Series '{name}' has {len(values)} values "
                    f"but x_values has {len(x_values)}."
                )
            }

    try:
        fig_width = max(7, min(len(x_values) * 0.7 + 3, 14))
        fig, ax = plt.subplots(figsize=(fig_width, 5))
        ax.set_title(title)

        if chart_type == "bar":
            _bar_chart(ax, x_values, data, x_label, y_label)
        elif chart_type == "line":
            _line_chart(ax, x_values, data, x_label, y_label)
        elif chart_type == "pie":
            _pie_chart(ax, x_values, data, x_label)
        elif chart_type == "scatter":
            _scatter_chart(ax, x_values, data, x_label, y_label)
        else:
            plt.close(fig)
            return {"error": f"Unsupported chart_type: '{chart_type}'."}

        return {"chart_b64": _fig_to_b64(fig)}

    except Exception as exc:
        return {"error": f"Chart rendering failed: {exc}"}
