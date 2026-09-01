"""Figures for the paper.

    python src/figures.py

Writes PDF (vector, for the manuscript) and PNG (for viewing) to out/.

Colours are the dataviz reference palette, slots 1 and 2 in documented adjacent
order, so the CVD and contrast validation is inherited rather than re-derived.
Single-series figures carry no legend — the title names the series.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attack
import gate
import profiles
from gate import Outcome

OUT = Path(__file__).resolve().parent.parent / "out"
OUT.mkdir(exist_ok=True)

# reference palette, light mode
BLUE = "#2a78d6"     # slot 1
ORANGE = "#eb6834"   # slot 2
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#d9d8d3"
SURFACE = "#ffffff"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
    "font.size": 9,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK2,
    "axes.titlecolor": INK,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


def _save(fig, stem: str) -> None:
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{stem}.{ext}", bbox_inches="tight",
                    dpi=200 if ext == "png" else None)
    plt.close(fig)
    print(f"  wrote out/{stem}.pdf and .png")


# --------------------------------------------------------------------------- #
#  Figure 1 — the instrumentation ladder
# --------------------------------------------------------------------------- #

def fig_ladder(ics) -> None:
    labels, fracs, counts = [], [], []
    for _key, label, cov in profiles.cumulative():
        v = gate.evaluate_corpus(ics, cov)
        c = Counter(x.outcome for x in v.values())
        checkable = c[Outcome.PASS] + c[Outcome.FAIL]
        labels.append(label.replace("+ ", "+ "))
        fracs.append(c[Outcome.PASS] / checkable)
        counts.append(c[Outcome.PASS])

    fig, ax = plt.subplots(figsize=(5.4, 2.6))
    y = range(len(labels))
    bars = ax.barh(list(y), fracs, height=0.62, color=BLUE,
                   edgecolor=SURFACE, linewidth=2)          # 2px surface gap
    for b in bars:
        b.set_capstyle("round")

    for i, (f, n) in enumerate(zip(fracs, counts)):
        ax.text(f + 0.015, i, f"{f:.0%}  ({n}/85)", va="center",
                ha="left", fontsize=8.5, color=INK)

    ax.set_yticks(list(y), labels, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.20)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xlabel("ICS techniques evidenceable (of 85 checkable)")
    ax.set_title("Instrumentation determines what can be proven at all",
                 fontsize=10, fontweight="600", loc="left", pad=10)
    ax.grid(axis="x", color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    _save(fig, "fig1_instrumentation_ladder")


# --------------------------------------------------------------------------- #
#  Figure 2 — alternative routes per technique
# --------------------------------------------------------------------------- #

def fig_routes(ics, ent) -> None:
    def dist(corpus):
        c = Counter(len(t.analytics) for t in corpus.techniques.values())
        total = sum(c.values())
        return {k: v / total for k, v in c.items()}

    di, de = dist(ics), dist(ent)
    ks = sorted(set(di) | set(de))

    fig, ax = plt.subplots(figsize=(5.4, 2.6))
    w = 0.38
    xi = [k - w / 2 - 0.01 for k in ks]
    xe = [k + w / 2 + 0.01 for k in ks]
    ax.bar(xi, [di.get(k, 0) for k in ks], width=w, color=BLUE,
           edgecolor=SURFACE, linewidth=2, label="ICS")
    ax.bar(xe, [de.get(k, 0) for k in ks], width=w, color=ORANGE,
           edgecolor=SURFACE, linewidth=2, label="Enterprise")

    ax.annotate("every ICS technique\nhas exactly one route",
                xy=(1 - w / 2, di.get(1, 0)), xytext=(2.6, 0.80),
                fontsize=8.5, color=INK, ha="left",
                arrowprops=dict(arrowstyle="-", color=INK2, linewidth=0.9,
                                connectionstyle="arc3,rad=-0.2"))

    ax.set_xticks(ks)
    ax.set_xlabel("alternative detection routes (analytics per technique)")
    ax.set_ylabel("share of techniques")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylim(0, 1.05)
    ax.set_title("ICS techniques have no fallback route; Enterprise usually does",
                 fontsize=10, fontweight="600", loc="left", pad=10)
    ax.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    leg = ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    for t in leg.get_texts():
        t.set_color(INK2)
    _save(fig, "fig2_routes_per_technique")


# --------------------------------------------------------------------------- #
#  Figure 3 — criticality: single points of failure
# --------------------------------------------------------------------------- #

def fig_criticality(ics, ent, top: int = 8) -> None:
    ci = [r for r in gate.criticality(ics) if r[1] > 0][:top]
    ce = {dc: n for dc, n in gate.criticality(ent)}
    n_ics, n_ent = len(ics.techniques), len(ent.techniques)

    labels = [dc for dc, _ in ci]
    share_i = [n / n_ics for _, n in ci]
    share_e = [ce.get(dc, 0) / n_ent for dc in labels]

    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    y = range(len(labels))
    h = 0.36
    ax.barh([i - h / 2 - 0.01 for i in y], share_i, height=h, color=BLUE,
            edgecolor=SURFACE, linewidth=2, label="ICS")
    ax.barh([i + h / 2 + 0.01 for i in y], share_e, height=h, color=ORANGE,
            edgecolor=SURFACE, linewidth=2, label="Enterprise")

    for i, s in enumerate(share_i):
        ax.text(s + 0.008, i - h / 2 - 0.01, f"{s:.0%}", va="center",
                fontsize=8, color=INK)

    ax.set_yticks(list(y), labels, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0, max(share_i) * 1.22)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xlabel("techniques rendered unevidenceable by the absence of this one component")
    ax.set_title("A single missing data component removes up to 45% of ICS coverage",
                 fontsize=10, fontweight="600", loc="left", pad=10)
    ax.grid(axis="x", color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    leg = ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    for t in leg.get_texts():
        t.set_color(INK2)
    _save(fig, "fig3_criticality")


def main() -> None:
    ics, ent = attack.load("ics"), attack.load("ent")
    print("rendering figures...")
    fig_ladder(ics)
    fig_routes(ics, ent)
    fig_criticality(ics, ent)


if __name__ == "__main__":
    main()
