"""Experiment 3 - profile robustness. No model calls; runs on a laptop.

    python experiments/profile_robustness/robustness.py

profiles.py is the only authored input in the whole analysis. Every capacity
number depends on it, and a reviewer is entitled to ask whether the tiers were
chosen to produce the result. This script answers that from the ontology alone.

Five parts:

  1. tier summary        what each tier buys, per component
  2. criticality         leave-one-out over every component in every tier
  3. catch-all           every tier recomputed without 'Application Log Content'
  4. null profiles       authored tiers vs random coverage sets of equal size
  5. acquisition         greedy order - what a site should instrument first

Writes robustness_*.csv and fig_robustness.pdf/.png into this folder.
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import attack          # noqa: E402
import gate            # noqa: E402
import profiles as prof_mod  # noqa: E402
from gate import Outcome     # noqa: E402

HERE = Path(__file__).resolve().parent
TIERS = [k for k, _, _ in prof_mod.cumulative()]
STRICT = "p5b_controller_strict"
ALL = TIERS + [STRICT]
SHORT = {"p1_flow": "flow", "p2_dpi": "+DPI", "p3_historian": "+historian",
         "p4_host": "+host", "p5_controller": "+controller",
         STRICT: "+controller\n(strict)"}

N_NULL = 2000
SEED = 20260902

BLUE, ORANGE, INK, INK2, GRID, SURFACE = (
    "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#d9d8d3", "#ffffff")


# --------------------------------------------------------------------------- #

def checkable(ics) -> list:
    """Techniques the ontology actually states requirements for. UNDEFINED
    techniques are excluded everywhere: no instrumentation makes them
    evidenceable, so including them would flatter every profile equally."""
    return [t for t in ics.techniques.values()
            if t.analytics and any(a.data_components for a in t.analytics)]


def n_pass(techs, cov: frozenset[str]) -> int:
    return sum(gate.capacity(t, cov).outcome is Outcome.PASS for t in techs)


# --------------------------------------------------------------------------- #

def part1_tiers(techs, rows: list) -> dict[str, int]:
    print("=" * 78)
    print("1. TIER SUMMARY - what each tier buys")
    print("=" * 78)
    print(f"{'tier':<16}{'n_dc':>6}{'added':>7}{'pass':>7}{'of check':>10}"
          f"{'marginal':>10}{'per dc':>9}")
    got: dict[str, int] = {}
    prev = 0
    for key, _label, cov in prof_mod.cumulative():
        p = n_pass(techs, cov)
        added = len([t for t in prof_mod.TIERS if t.key == key][0].adds)
        got[key] = p
        print(f"{SHORT[key]:<16}{len(cov):>6}{added:>7}{p:>7}{p/len(techs):>9.1%}"
              f"{p - prev:>+10}{(p - prev) / added:>9.2f}")
        rows.append({"part": "tier", "profile": key, "n_components": len(cov),
                     "components_added": added, "n_pass": p,
                     "frac_pass": round(p / len(techs), 4),
                     "marginal": p - prev,
                     "per_component": round((p - prev) / added, 3)})
        prev = p
    cov = prof_mod.named(STRICT)
    p = n_pass(techs, cov)
    got[STRICT] = p
    print(f"{'+ctrl strict':<16}{len(cov):>6}{'-1':>7}{p:>7}{p/len(techs):>9.1%}"
          f"{'':>10}{'':>9}   variant of p5")
    rows.append({"part": "tier", "profile": STRICT, "n_components": len(cov),
                 "components_added": -1, "n_pass": p,
                 "frac_pass": round(p / len(techs), 4),
                 "marginal": "", "per_component": ""})
    print(f"\n{len(techs)} checkable techniques (UNDEFINED excluded).")
    return got


def part2_criticality(techs, rows: list) -> None:
    print("\n" + "=" * 78)
    print("2. CRITICALITY - leave one component out")
    print("=" * 78)
    print("How many techniques stop being evidenceable if this component is")
    print("removed from the tier. A tier resting on one component is fragile.\n")
    for key in ALL:
        cov = prof_mod.named(key)
        base = n_pass(techs, cov)
        losses = sorted(((base - n_pass(techs, cov - {dc}), dc) for dc in cov),
                        reverse=True)
        redundant = sum(1 for loss, _ in losses if loss == 0)
        top = [f"{dc} (-{loss})" for loss, dc in losses[:3] if loss]
        print(f"{SHORT[key].replace(chr(10), ' '):<24} base {base:>3}   "
              f"load-bearing: {', '.join(top) if top else 'none'}")
        print(f"{'':<24} {redundant} of {len(cov)} components individually redundant")
        for loss, dc in losses:
            rows.append({"part": "criticality", "profile": key,
                         "data_component": dc, "base_pass": base,
                         "loss_if_removed": loss})


def part3_catchall(techs, rows: list) -> None:
    print("\n" + "=" * 78)
    print(f"3. CATCH-ALL - quarantining '{prof_mod.CATCH_ALL}'")
    print("=" * 78)
    involved = solo = 0
    for t in techs:
        for a in t.analytics:
            dcs = set(a.data_components)
            if prof_mod.CATCH_ALL in dcs:
                involved += 1
                solo += len(dcs) == 1
    print(f"analytics citing it: {involved}; sole requirement in only {solo}.")
    print("In the rest it completes an analytic whose other requirements are")
    print("already met - so it lands all at once at whichever tier holds it.\n")
    print(f"{'tier':<16}{'with':>12}{'without':>12}{'delta':>9}")
    for key, _label, cov in prof_mod.cumulative():
        a = n_pass(techs, cov)
        b = n_pass(techs, cov - {prof_mod.CATCH_ALL})
        print(f"{SHORT[key]:<16}{a/len(techs):>11.1%}{b/len(techs):>12.1%}"
              f"{b - a:>+9}")
        rows.append({"part": "catch_all", "profile": key, "n_pass_with": a,
                     "n_pass_without": b, "delta": b - a})


def part4_null(techs, tier_pass: dict[str, int], rows: list) -> dict[str, float]:
    print("\n" + "=" * 78)
    print(f"4. NULL PROFILES - authored tiers vs {N_NULL} random sets of equal size")
    print("=" * 78)
    print("Answers 'you cherry-picked the tiers'. A tier near the median of its")
    print("size class is unremarkable; an extreme percentile needs explaining.\n")
    pool = sorted(set().union(*(set(a.data_components) for t in techs
                                for a in t.analytics)))
    print(f"sampling from {len(pool)} data components that ICS analytics "
          f"actually reference.")
    print("A profile's EFFECTIVE size is how many of its components fall in")
    print("that pool. The rest are inert - no analytic can ever ask for them -")
    print("so counting them would inflate the size and make the null unfair.\n")
    rng = random.Random(SEED)
    pct: dict[str, float] = {}
    print(f"{'tier':<22}{'size':>6}{'eff':>5}{'authored':>10}{'null med':>10}"
          f"{'null p05':>10}{'null p95':>10}{'pctile':>9}")
    for key in ALL:
        cov = prof_mod.named(key)
        eff = len(cov & frozenset(pool))
        obs = tier_pass[key]
        name = SHORT[key].replace(chr(10), " ")
        if eff >= len(pool):
            print(f"{name:<22}{len(cov):>6}{eff:>5}{obs:>10}"
                  f"{'  (is the whole pool - no null exists)':>39}")
            rows.append({"part": "null", "profile": key, "size": len(cov),
                         "effective_size": eff, "authored_pass": obs,
                         "null_median": "", "null_p05": "", "null_p95": "",
                         "percentile": "", "note": "degenerate"})
            continue
        draws = sorted(n_pass(techs, frozenset(rng.sample(pool, eff)))
                       for _ in range(N_NULL))
        q = lambda f: draws[min(int(f * N_NULL), N_NULL - 1)]
        # mid-p: counting ties as half avoids inflating percentiles on the
        # small discrete counts the low tiers produce.
        p = (sum(d < obs for d in draws)
             + 0.5 * sum(d == obs for d in draws)) / N_NULL
        pct[key] = p
        print(f"{name:<22}{len(cov):>6}{eff:>5}{obs:>10}"
              f"{q(.50):>10}{q(.05):>10}{q(.95):>10}{p:>8.0%}")
        rows.append({"part": "null", "profile": key, "size": len(cov),
                     "effective_size": eff, "authored_pass": obs,
                     "null_median": q(.50), "null_p05": q(.05),
                     "null_p95": q(.95), "percentile": round(p, 4), "note": ""})
    return pct


def part5_acquisition(ics, rows: list) -> None:
    print("\n" + "=" * 78)
    print("5. ACQUISITION ORDER - what to instrument first")
    print("=" * 78)
    print("Greedy: at each step the component making the most techniques")
    print("evidenceable. Not optimal set cover; the ordering is the point.\n")
    print(f"{'#':>3}  {'data component':<42}{'cumulative':>11}{'gain':>7}")
    for i, (dc, cum, marg) in enumerate(gate.acquisition_order(ics, limit=15), 1):
        print(f"{i:>3}. {dc:<42}{cum:>11}{marg:>+7}")
        rows.append({"part": "acquisition", "rank": i, "data_component": dc,
                     "cumulative_pass": cum, "marginal_gain": marg})


# --------------------------------------------------------------------------- #

def write(rows: list, part: str) -> None:
    sel = [r for r in rows if r["part"] == part]
    if not sel:
        return
    keys = list(dict.fromkeys(k for r in sel for k in r))
    path = HERE / f"robustness_{part}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in keys} for r in sel)
    print(f"  {path.name} ({len(sel)} rows)")


def figure(techs, ics) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import PercentFormatter
    except ImportError:
        print("matplotlib not installed - skipping figure")
        return

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
        "axes.titlecolor": INK, "xtick.color": INK2, "ytick.color": INK2,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    })
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(9.2, 3.2))

    n = len(techs)
    with_ca, without = [], []
    for _k, _l, cov in prof_mod.cumulative():
        with_ca.append(n_pass(techs, cov) / n)
        without.append(n_pass(techs, cov - {prof_mod.CATCH_ALL}) / n)
    xs = range(len(TIERS))
    ax.plot(list(xs), with_ca, color=BLUE, lw=2, marker="o", ms=5,
            label="as authored")
    ax.plot(list(xs), without, color=ORANGE, lw=2, marker="o", ms=5,
            linestyle=(0, (4, 3)), label="catch-all excluded")
    # Vertical span at the last tier rather than a leader from the left: the gap
    # sits at the right edge and any leader would cross the rising blue line.
    last = len(TIERS) - 1
    ax.annotate("", xy=(last, with_ca[-1]), xytext=(last, without[-1]),
                arrowprops=dict(arrowstyle="<->", color=INK2, lw=1.1))
    ax.text(last - 0.12, (with_ca[-1] + without[-1]) / 2,
            f"one component\ncarries {with_ca[-1] - without[-1]:.0%}",
            ha="right", va="center", fontsize=8, color=INK2)
    ax.set_xlim(-0.3, last + 0.3)
    ax.set_xticks(list(xs), [SHORT[k].replace("\n", " ") for k in TIERS],
                  fontsize=7.5)
    ax.set_ylim(0, 1.04)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylabel("checkable techniques evidenceable")
    ax.set_title("The ceiling depends on one data component",
                 fontsize=10, fontweight="600", loc="left", pad=10)
    ax.legend(frameon=False, fontsize=8, loc="upper left")

    acq = gate.acquisition_order(ics, limit=20)
    bx.plot(range(1, len(acq) + 1), [c / n for _, c, _ in acq],
            color=BLUE, lw=2, marker="o", ms=4)
    bx.set_xlabel("data components instrumented (greedy order)")
    bx.set_ylabel("checkable techniques evidenceable")
    bx.set_ylim(0, 1.04)
    bx.yaxis.set_major_formatter(PercentFormatter(1.0))
    bx.set_title("What to instrument first",
                 fontsize=10, fontweight="600", loc="left", pad=10)

    for a in (ax, bx):
        a.grid(axis="y", color=GRID, lw=0.6, alpha=0.7)
        a.set_axisbelow(True)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)

    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(HERE / f"fig_robustness.{ext}", bbox_inches="tight",
                    dpi=200 if ext == "png" else None)
    plt.close(fig)
    print("  fig_robustness.pdf and .png")


def main() -> None:
    ics = attack.load("ics")
    techs = checkable(ics)
    rows: list[dict] = []

    tier_pass = part1_tiers(techs, rows)
    part2_criticality(techs, rows)
    part3_catchall(techs, rows)
    pct = part4_null(techs, tier_pass, rows)
    part5_acquisition(ics, rows)

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    full = tier_pass["p5_controller"] / len(techs)
    strict = tier_pass[STRICT] / len(techs)
    print(f"p5 ceiling {full:.0%} as authored, {strict:.0%} with the catch-all")
    print(f"excluded. The strict tier is the conservative number and both are")
    print("reported. H1's 'approaches zero at p5' is registered against p5b.")
    hi = [k for k, p in pct.items() if p > 0.95]
    lo = [k for k, p in pct.items() if p <= 0.15]
    nm = lambda ks: ", ".join(SHORT[k].replace(chr(10), " ") for k in ks)
    print("\nNull check, against random component sets of the same effective size:")
    if hi:
        print(f"  ABOVE the 95th percentile: {nm(hi)}")
        print("  The small tiers are MORE productive than random sets of their")
        print("  size, so they were not chosen to look restrictive. The low")
        print("  ceilings at p1-p3 are a property of the ontology, not of us.")
    if lo:
        print(f"  BOTTOM 15% of their size class: {nm(lo)}")
        print("  The large tiers are LESS productive than random sets of their")
        print("  size. The reason is the finding, not a flaw: the components")
        print("  ICS analytics lean on hardest are the controller-side ones a")
        print("  real plant is least likely to have, so a broad host profile")
        print("  can hold most of the pool and still miss what matters.")

    print("\nwrote:")
    for part in ("tier", "criticality", "catch_all", "null", "acquisition"):
        write(rows, part)
    figure(techs, ics)


if __name__ == "__main__":
    main()
