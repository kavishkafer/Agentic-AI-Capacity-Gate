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

    # Instrumented only. In the bare condition the model is not told what
    # telemetry exists, so arm 4 ("cited only components in coverage") is not
    # testing the same thing, and any metric conditioned on arm 4 passing is
    # deflated for reasons unrelated to capacity. Plotting both side by side
    # invited exactly that misreading.
    cond = "instrumented" if "instrumented" in conditions else conditions[-1]
    models = sorted(runs)
    fig, ax = plt.subplots(figsize=(5.6, 3.0))
    xs = list(range(len(models)))

    supported, violating = [], []
    for model in models:
        rs = [r for r in runs[model] if r["condition"] == cond]
        v = frac(rs, "capacity_violation")
        violating.append(v)
        supported.append(max(0.0, frac(rs, "model_says_provable") - v))

    ax.bar(xs, supported, width=0.55, color=BLUE, edgecolor=SURFACE,
           linewidth=1.5, label="asserted and supportable")
    ax.bar(xs, violating, width=0.55, bottom=supported, color=ORANGE,
           edgecolor=SURFACE, linewidth=1.5, label="asserted but unsupportable")

    right = len(models) - 1 + 0.85
    ax.set_xlim(-0.55, right)
    ceil = _item_ceiling()
    if ceil is not None:
        # Stop the rule short of the margin label rather than striking through it.
        ax.plot([-0.55, len(models) - 1 + 0.28], [ceil, ceil], color=INK2,
                linewidth=1.2, linestyle=(0, (4, 3)))
        # In the right margin: every position over the plot collides with a bar.
        ax.text(len(models) - 1 + 0.34, ceil, f"{ceil:.0%}\nontology\npermits",
                ha="left", va="center", fontsize=7.5, color=INK2,
                linespacing=1.35)

    for x, (s, v) in enumerate(zip(supported, violating)):
        ax.text(x, s + v + 0.012, f"{v:.0%} unsupportable", ha="center",
                fontsize=8, color=INK2)

    ax.set_xticks(xs, [m[:22] for m in models], fontsize=8)
    ax.set_ylim(0, max(s + v for s, v in zip(supported, violating)) + 0.14)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylabel("share of incident items")
    ax.set_title("Models assert provability far beyond what the evidence permits",
                 fontsize=10, fontweight="600", loc="left", pad=10)
    ax.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    leg = ax.legend(frameon=False, fontsize=8, loc="upper right")
    for t in leg.get_texts():
        t.set_color(INK2)

    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"fig4_capacity_violation.{ext}", bbox_inches="tight",
                    dpi=200 if ext == "png" else None)
    plt.close(fig)
    print("wrote out/fig4_capacity_violation.pdf and .png")


def _item_ceiling(profile: str = "p3_historian") -> float | None:
    """Share of items whose GOLD technique is evidenceable at this profile.

    The honest reference for the assertion rate: a model that attributed every
    item correctly and asserted provability only when the ontology permits it
    would land here. It is an item-level figure and so differs from the
    technique-level ceiling (8.1% vs 11.8% at p3_historian) — the corpus is not
    uniform over techniques."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import attack, gate, packets, profiles          # noqa: E402
        from gate import Outcome                        # noqa: E402
        ics = attack.load("ics")
        cov = profiles.named(profile)
        items = packets.load_items(ics)
        ok = sum(gate.capacity(ics.techniques[i.gold_id], cov).outcome
                 is Outcome.PASS for i in items)
        return ok / len(items)
    except Exception:
        return None


if __name__ == "__main__":
    main()
