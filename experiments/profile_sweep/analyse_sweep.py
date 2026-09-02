"""Analyse the profile sweep — does the gate track instrumentation?

    python experiments/profile_sweep/analyse_sweep.py

Reads out/experiment_sweep_<model>_<profile>.csv, tests the pre-registered
hypotheses in HYPOTHESIS.md, and writes a figure plus a tidy CSV.

Also re-scores the ORIGINAL bare-condition answers against every profile without
re-running the models: the bare prompt contains no telemetry list, so the model's
answer is profile-independent — only the scoring changes. That gives the bare
arm of the sweep for free.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import attack          # noqa: E402
import gate            # noqa: E402
import profiles as prof_mod  # noqa: E402
from gate import Outcome     # noqa: E402

OUT = ROOT / "out"
HERE = Path(__file__).resolve().parent

# TIERS are cumulative and ordered; STRICT is a VARIANT of the last tier, not a
# sixth tier. Monotonicity is therefore tested over TIERS only — p5b has less
# coverage than p5, so a rise from p5 to p5b is expected, not a failure.
TIERS = ["p1_flow", "p2_dpi", "p3_historian", "p4_host", "p5_controller"]
STRICT = "p5b_controller_strict"
ORDER = TIERS + [STRICT]
SHORT = {"p1_flow": "flow", "p2_dpi": "+DPI", "p3_historian": "+historian",
         "p4_host": "+host", "p5_controller": "+controller",
         STRICT: "+ctrl strict"}

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#d9d8d3", "#ffffff"
TRUE = {"true", "True", "1"}


def b(v) -> bool:
    return v in TRUE


def ceiling(ics, profile: str) -> float:
    """Fraction of ALL techniques evidenceable at this profile — the ontology's
    own limit, independent of any model. Denominator per gate.DENOMINATOR: the
    12 UNDEFINED techniques count against every profile, so this tops out at
    85/97 = 87.6%, not 100%."""
    return gate.evidenceable_fraction(
        gate.evaluate_corpus(ics, prof_mod.named(profile)))


def load_sweep() -> dict[tuple[str, str], list[dict]]:
    """(model, profile) -> rows, from the instrumented sweep runs."""
    data: dict[tuple[str, str], list[dict]] = {}
    for p in sorted(OUT.glob("experiment_sweep_*.csv")):
        stem = p.stem.replace("experiment_sweep_", "")
        for prof in ORDER:
            if stem.endswith("_" + prof):
                model = stem[: -(len(prof) + 1)]
                with p.open(encoding="utf-8") as f:
                    data[(model, prof)] = list(csv.DictReader(f))
                break
    return data


def rescore_bare(ics) -> dict[tuple[str, str], list[dict]]:
    """Re-score the original bare answers at every profile. No model calls:
    the bare prompt has no telemetry list, so the answer does not depend on the
    profile — only arm4/arm5 scoring does."""
    out: dict[tuple[str, str], list[dict]] = {}
    for src in sorted((ROOT / "results").glob("experiment_*.csv")):
        if "sweep" in src.name or "summary" in src.name:
            continue
        model = src.stem.replace("experiment_", "")
        with src.open(encoding="utf-8") as f:
            bare = [r for r in csv.DictReader(f) if r["condition"] == "bare"]
        if not bare:
            continue
        for profile in ORDER:
            cov = prof_mod.named(profile)
            rows = []
            for r in bare:
                t = ics.techniques.get(r["claimed_id"].strip().upper())
                if t is None:
                    a5_pass, outcome = False, "unknown-technique"
                else:
                    v = gate.capacity(t, cov)
                    a5_pass, outcome = v.outcome is Outcome.PASS, v.outcome.value
                says = b(r["model_says_provable"])
                rows.append({**r,
                             "arm5_capacity_pass": str(a5_pass),
                             "arm5_outcome": outcome,
                             "capacity_violation": str(says and not a5_pass)})
            out[(model, profile)] = rows
    return out


def rates(rows: list[dict]) -> dict[str, float]:
    n = len(rows)
    if not n:
        return {}
    f = lambda k: sum(b(r[k]) for r in rows) / n
    resolved = [r for r in rows if r["arm5_outcome"] != "unknown-technique"]
    return {
        "n": n,
        "says_provable": f("model_says_provable"),
        "arm5_pass": f("arm5_capacity_pass"),
        "violation": f("capacity_violation"),
        "violation_resolved": (
            sum(b(r["capacity_violation"]) for r in resolved) / len(resolved)
            if resolved else 0.0),
        "unknown_id": 1 - len(resolved) / n,
    }


def main() -> None:
    ics = attack.load("ics")
    sweep = load_sweep()
    if not sweep:
        print("no out/experiment_sweep_*.csv found — run run_sweep.py first")
        return

    models = sorted({m for m, _ in sweep})
    ceil = {p: ceiling(ics, p) for p in ORDER}

    print("=" * 84)
    print("PROFILE SWEEP — instrumented condition")
    print("=" * 84)
    print("\nOntology ceiling (fraction of checkable techniques evidenceable):")
    print("   " + "  ".join(f"{SHORT[p]}={ceil[p]:.0%}" for p in ORDER))

    tidy = []
    for model in models:
        print(f"\n--- {model} ---")
        print(f"{'profile':<14}{'n':>5}{'ceiling':>9}{'says prov':>11}"
              f"{'arm5':>8}{'VIOL':>8}{'VIOL(res)':>11}{'calib gap':>11}")
        for p in ORDER:
            rows = sweep.get((model, p))
            if not rows:
                continue
            r = rates(rows)
            gapv = r["says_provable"] - r["arm5_pass"]
            print(f"{SHORT[p]:<14}{r['n']:>5}{ceil[p]:>8.0%}"
                  f"{r['says_provable']:>10.0%}{r['arm5_pass']:>8.0%}"
                  f"{r['violation']:>8.0%}{r['violation_resolved']:>10.0%}"
                  f"{gapv:>+10.0%}")
            tidy.append({"model": model, "profile": p, "condition": "instrumented",
                         "ceiling": round(ceil[p], 4), **{k: round(v, 4)
                         for k, v in r.items()},
                         "calibration_gap": round(gapv, 4)})

    # --- hypothesis checks -------------------------------------------------
    print("\n" + "=" * 84)
    print("PRE-REGISTERED HYPOTHESES")
    print("=" * 84)
    for model in models:
        vs = [(p, rates(sweep[(model, p)])["violation_resolved"])
              for p in TIERS if (model, p) in sweep]
        if len(vs) < 2:
            continue
        seq = [v for _, v in vs]
        mono = all(a >= b_ - 1e-9 for a, b_ in zip(seq, seq[1:]))
        drop = seq[0] - seq[-1]
        print(f"\n{model}")
        print(f"  H1 violation falls with instrumentation : "
              f"{'HOLDS' if mono else 'FAILS — not monotone'}"
              f"   ({seq[0]:.0%} -> {seq[-1]:.0%}, drop {drop:+.0%})")

        # The registered floor is p5b, not p5: p5's 100% ceiling rests entirely
        # on one generic catch-all component (see experiments/profile_robustness).
        floor_key = STRICT if (model, STRICT) in sweep else vs[-1][0]
        floor = rates(sweep[(model, floor_key)])["violation_resolved"]
        print(f"  H1 approaches zero at {SHORT[floor_key]:<12}: "
              f"{'yes' if floor < 0.10 else 'NO — still ' + format(floor, '.0%')}"
              + ("" if floor_key == STRICT else "   [p5b not run — weaker test]"))
        gaps = [rates(sweep[(model, p)])["says_provable"] - ceil[p]
                for p in ORDER if (model, p) in sweep]
        tracks = max(abs(g) for g in gaps) < 0.15
        print(f"  H3 says_provable tracks the ceiling     : "
              f"{'model IS calibrated (H3 fails)' if tracks else 'model does NOT track (H3 holds)'}"
              f"   max deviation {max(gaps, key=abs):+.0%}")

    # --- bare arm, free ----------------------------------------------------
    bare = rescore_bare(ics)
    if bare:
        print("\n" + "=" * 84)
        print("BARE CONDITION, RE-SCORED AT EACH PROFILE (no new model calls)")
        print("=" * 84)
        print("The bare prompt has no telemetry list, so answers are identical")
        print("across profiles — only the scoring changes.\n")
        print("Two rows per model: all answers, then resolved IDs only.")
        print("The resolved row excludes the namespace / stale-ID confound,")
        print("which does not shrink as telemetry improves.")
        print()
        print(f"{'model':<20}" + "".join(f"{SHORT[p]:>13}" for p in ORDER))
        for model in sorted({m for m, _ in bare}):
            for key, lbl in (("violation", "all"), ("violation_resolved", "resolved")):
                line = f"{model + ' (' + lbl + ')':<20}"
                for p in ORDER:
                    rr = bare.get((model, p))
                    line += f"{rates(rr)[key]:>12.0%} " if rr else f"{'-':>13}"
                print(line)
            for p in ORDER:
                rr = bare.get((model, p))
                if rr:
                    r = rates(rr)
                    tidy.append({"model": model, "profile": p, "condition": "bare",
                                 "ceiling": round(ceil[p], 4),
                                 **{k: round(v, 4) for k, v in r.items()},
                                 "calibration_gap": round(
                                     r["says_provable"] - r["arm5_pass"], 4)})

    with (HERE / "sweep_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(tidy[0]))
        w.writeheader()
        w.writerows(tidy)
    print(f"\nwrote {HERE.name}/sweep_results.csv ({len(tidy)} rows)")
    _figure(sweep, models, ceil)


def _figure(sweep, models, ceil) -> None:
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
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    xs = range(len(ORDER))
    sx = len(TIERS)          # x position of the p5b variant, drawn detached

    ax.plot(list(range(len(TIERS))), [ceil[p] for p in TIERS], color=INK2,
            linewidth=1.4, linestyle=(0, (4, 3)), marker="o", markersize=4,
            label="evidenceable (ontology limit, of 97)")
    ax.plot([sx], [ceil[STRICT]], color=INK2, marker="o", markersize=4,
            markerfacecolor=SURFACE, linestyle="none")

    for model, colour in zip(models, [BLUE, ORANGE, AQUA]):
        ys, xx = [], []
        for i, p in enumerate(TIERS):
            if (model, p) in sweep:
                xx.append(i)
                ys.append(rates(sweep[(model, p)])["violation_resolved"])
        if ys:
            ax.plot(xx, ys, color=colour, linewidth=2, marker="o", markersize=5,
                    label=model)
        if (model, STRICT) in sweep:
            ax.plot([sx], [rates(sweep[(model, STRICT)])["violation_resolved"]],
                    color=colour, marker="o", markersize=5,
                    markerfacecolor=SURFACE, linestyle="none")

    ax.axvline(sx - 0.5, color=GRID, linewidth=1)
    ax.text(sx, 1.0, "variant", ha="center", va="top", fontsize=7, color=INK2)
    ax.set_xticks(list(xs), [SHORT[p] for p in ORDER], fontsize=8)
    ax.set_ylim(0, 1.02)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xlabel("instrumentation (cumulative)")
    ax.set_ylabel("capacity violation rate")
    ax.set_title("Does the gate track instrumentation, or reject reflexively?",
                 fontsize=10, fontweight="600", loc="left", pad=10)
    ax.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    leg = ax.legend(frameon=False, fontsize=8, loc="upper right")
    for t in leg.get_texts():
        t.set_color(INK2)

    for ext in ("pdf", "png"):
        fig.savefig(HERE / f"fig_profile_sweep.{ext}", bbox_inches="tight",
                    dpi=200 if ext == "png" else None)
    plt.close(fig)
    print(f"wrote {HERE.name}/fig_profile_sweep.pdf and .png")


if __name__ == "__main__":
    main()
