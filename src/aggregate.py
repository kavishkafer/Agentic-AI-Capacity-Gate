"""Aggregate experiment runs across models into the paper's cross-model table.

    python src/aggregate.py

Reads every out/experiment_*.csv (one per model), prints the comparison table,
writes out/crossmodel.csv and a figure.

Slices reported, because each answers a different reviewer question:
  overall           — the headline
  correct only      — among items the model attributed correctly, does it still
                      over-claim provability? (rules out "it was just confused")
  no name leak      — on items whose narrative does NOT paraphrase the technique
                      name, so attribution was genuinely hard
  checkable only    — excluding gold techniques ATT&CK gives no requirements for
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "out"

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"   # palette slots 1-3
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#d9d8d3", "#ffffff"

TRUE = {"true", "True", "1", True}


def _b(v) -> bool:
    return v in TRUE


def load_runs() -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = defaultdict(list)
    for p in sorted(OUT.glob("experiment_*.csv")):
        if p.name.endswith("_summary.json"):
            continue
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                runs[row.get("model") or p.stem].append(row)
    return runs


def slice_rows(rows, which: str):
    if which == "overall":
        return rows
    if which == "correct":
        return [r for r in rows if _b(r["attribution_correct"])]
    if which == "noleak":
        return [r for r in rows if not _b(r["name_leak"])]
    if which == "checkable":
        return [r for r in rows if _b(r["gold_checkable"])]
    raise KeyError(which)


def frac(rows, key) -> float:
    """Fraction of rows where `key` is true. `claimed_id` is a string field —
    non-empty means the reply parsed and named a technique."""
    if not rows:
        return 0.0
    if key == "claimed_id":
        return sum(bool((r.get(key) or "").strip()) for r in rows) / len(rows)
    return sum(_b(r[key]) for r in rows) / len(rows)


def main() -> None:
    runs = load_runs()
    if not runs:
        print("no experiment_*.csv in out/ — run src/experiment.py first")
        return

    conditions = sorted({r["condition"] for rs in runs.values() for r in rs})
    slices = ["overall", "correct", "noleak", "checkable"]

    print("=" * 88)
    print("CROSS-MODEL RESULTS")
    print("=" * 88)

    out_rows = []
    for cond in conditions:
        print(f"\n--- condition: {cond} ---")
        hdr = (f"{'model':<26}{'n':>5}{'parse':>8}{'attrib':>8}"
               f"{'says prov':>11}{'arm4':>8}{'arm5':>8}{'VIOL':>8}{'MISSED':>8}")
        print(hdr)
        for model, rows in sorted(runs.items()):
            rs = [r for r in rows if r["condition"] == cond]
            if not rs:
                continue
            line = (f"{model[:25]:<26}{len(rs):>5}"
                    f"{frac(rs,'claimed_id'):>7.0%} "
                    f"{frac(rs,'attribution_correct'):>7.0%} "
                    f"{frac(rs,'model_says_provable'):>10.0%} "
                    f"{frac(rs,'arm4_grounding_pass'):>7.0%} "
                    f"{frac(rs,'arm5_capacity_pass'):>7.0%} "
                    f"{frac(rs,'capacity_violation'):>7.0%} "
                    f"{frac(rs,'missed_by_grounding'):>7.0%}")
            print(line)
            for sl in slices:
                srs = slice_rows(rs, sl)
                out_rows.append({
                    "model": model, "condition": cond, "slice": sl, "n": len(srs),
                    "parse_ok": round(frac(srs, "claimed_id"), 4),
                    "attribution_correct": round(frac(srs, "attribution_correct"), 4),
                    "model_says_provable": round(frac(srs, "model_says_provable"), 4),
                    "arm4_grounding_pass": round(frac(srs, "arm4_grounding_pass"), 4),
                    "arm5_capacity_pass": round(frac(srs, "arm5_capacity_pass"), 4),
                    "capacity_violation": round(frac(srs, "capacity_violation"), 4),
                    "missed_by_grounding": round(frac(srs, "missed_by_grounding"), 4),
                })

    # slice detail for the headline metric
    print("\n" + "=" * 88)
    print("CAPACITY VIOLATION BY SLICE  (does the finding survive stricter reading?)")
    print("=" * 88)
    print(f"{'model':<26}{'condition':<14}" + "".join(f"{s:>13}" for s in slices))
    for model, rows in sorted(runs.items()):
        for cond in conditions:
            rs = [r for r in rows if r["condition"] == cond]
            if not rs:
                continue
            line = f"{model[:25]:<26}{cond:<14}"
            for sl in slices:
                srs = slice_rows(rs, sl)
                line += f"{frac(srs,'capacity_violation'):>12.0%} "
            print(line)

    with (OUT / "crossmodel.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote out/crossmodel.csv ({len(out_rows)} rows)")

    _figure(runs, conditions)


def _figure(runs, conditions) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import PercentFormatter
    except ImportError:
        print("matplotlib not installed — skipping figure")
        return

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
        "axes.titlecolor": INK, "xtick.color": INK2, "ytick.color": INK2,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    })

    models = sorted(runs)
    colours = [BLUE, ORANGE, AQUA][:len(models)]
    fig, ax = plt.subplots(figsize=(5.6, 2.8))
    w = 0.8 / max(1, len(models))

    for mi, (model, colour) in enumerate(zip(models, colours)):
        xs, ys = [], []
        for ci, cond in enumerate(conditions):
            rs = [r for r in runs[model] if r["condition"] == cond]
            xs.append(ci + (mi - (len(models) - 1) / 2) * (w + 0.012))
            ys.append(frac(rs, "missed_by_grounding"))
        ax.bar(xs, ys, width=w, color=colour, edgecolor=SURFACE, linewidth=2,
               label=model[:22])

    ax.set_xticks(range(len(conditions)),
                  [c.replace("instrumented", "told what telemetry exists")
                    .replace("bare", "no telemetry context") for c in conditions])
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylabel("claims a grounding check would accept")
    ax.set_title("Referential grounding accepts claims the evidence cannot support",
                 fontsize=10, fontweight="600", loc="left", pad=10)
    ax.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    leg = ax.legend(frameon=False, fontsize=8, loc="upper right")
    for t in leg.get_texts():
        t.set_color(INK2)

    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"fig4_missed_by_grounding.{ext}", bbox_inches="tight",
                    dpi=200 if ext == "png" else None)
    plt.close(fig)
    print("wrote out/fig4_missed_by_grounding.pdf and .png")


if __name__ == "__main__":
    main()
