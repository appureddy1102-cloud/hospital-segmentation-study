"""
viz.py
======
Shared plotting style + helpers so every figure in the study has consistent
titling, axis labels, legends and an accompanying machine-readable caption
recorded in outputs/figure_index.csv.
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config as C

PALETTE = ["#1f4e79", "#2e75b6", "#5b9bd5", "#a5a5a5", "#ed7d31",
           "#c55a11", "#70ad47", "#43682b", "#7030a0", "#bf9000"]
SEQ = "Blues"
FIG_DPI = 150

plt.rcParams.update({
    "figure.dpi": FIG_DPI,
    "savefig.dpi": FIG_DPI,
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": "--",
    "legend.frameon": False,
    "figure.autolayout": False,
})

_INDEX: list[dict] = []
_FIGNO = [0]


def save(fig, name: str, title: str, observation: str, interpretation: str,
         implication: str) -> Path:
    """Save a figure and record its analytical caption in the figure index."""
    _FIGNO[0] += 1
    fig.tight_layout()
    path = C.FIG_DIR / f"{name}.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    _INDEX.append({
        "figure_no": _FIGNO[0], "file": path.name, "title": title,
        "numerical_observation": observation,
        "pattern_identified": interpretation,
        "business_implication": implication,
    })
    return path


def write_index():
    """
    Merge this run's figure captions into the cumulative figure index.

    Each pipeline stage runs in its own process, so an in-memory list cannot
    accumulate across stages. The index is therefore merged on disk by filename:
    figures produced by an earlier stage are preserved, and a figure re-produced
    by a later stage replaces its own row rather than duplicating it.
    """
    if not _INDEX:
        return pd.read_csv(C.OUT_DIR / "figure_index.csv") \
            if (C.OUT_DIR / "figure_index.csv").exists() else pd.DataFrame()

    new = pd.DataFrame(_INDEX)
    path = C.OUT_DIR / "figure_index.csv"
    if path.exists():
        old = pd.read_csv(path)
        old = old[~old["file"].isin(new["file"])]
        new = pd.concat([old, new], ignore_index=True)
    # stable, human-friendly ordering by the numeric prefix in the filename
    new["_order"] = new["file"].str.extract(r"^(\d+)").astype(float)
    new = new.sort_values("_order").drop(columns="_order").reset_index(drop=True)
    new["figure_no"] = range(1, len(new) + 1)
    new.to_csv(path, index=False)
    return new


def bar(ax, labels, values, title, xlabel, ylabel, color=PALETTE[0],
        annotate=True, fmt="{:,.0f}", rotate=0, horizontal=False):
    if horizontal:
        b = ax.barh(labels, values, color=color)
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
        if annotate:
            for r, v in zip(b, values):
                ax.text(v, r.get_y() + r.get_height() / 2, " " + fmt.format(v),
                        va="center", fontsize=8)
    else:
        b = ax.bar(labels, values, color=color)
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
        if annotate:
            for r, v in zip(b, values):
                ax.text(r.get_x() + r.get_width() / 2, v, fmt.format(v),
                        ha="center", va="bottom", fontsize=8)
        if rotate:
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=rotate, ha="right")
    ax.set_title(title)
    return b


def money(x, pos=None):
    if abs(x) >= 1e7:
        return f"{x/1e7:.1f}Cr"
    if abs(x) >= 1e5:
        return f"{x/1e5:.1f}L"
    if abs(x) >= 1e3:
        return f"{x/1e3:.0f}k"
    return f"{x:.0f}"


def pct_fmt(x, pos=None):
    return f"{x:.0f}%"
