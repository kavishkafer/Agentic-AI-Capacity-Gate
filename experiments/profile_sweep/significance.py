"""Statistical rigor pass on the profile sweep — does H1's failure survive
significance testing, or is the non-monotonicity noise?

    python experiments/profile_sweep/significance.py

`analyse_sweep.py`'s H1 check is a strict pointwise-monotonicity test on raw
percentages: it fails the whole hypothesis if violation rises at even one
step, and it treats each tier as an independent sample even though the same
271 items are reused at every tier. Both choices throw away information this
script recovers, without any new model calls:

  1. Wilson confidence intervals on every tier's violation rate (raw and
     id-resolved), so a percentage point difference can be read against its
     margin of error instead of taken at face value.
  2. McNemar's exact test between adjacent tiers (and p3->p5b, the headline
     comparison) — a PAIRED test, since it's the same items scored twice, not
     two independent samples. Answers "did violation significantly change
     step to step" rather than "did the percentage go up or down".
  3. An exact permutation test for the rank correlation between profile order
     and violation rate across p1..p5 — a trend test, which is what H1 is
     actually claiming ("falls as instrumentation improves"), rather than
     the brittle "never rises even once" pointwise criterion.
  4. Item-level attribution: which specific items flip status at the
     comparisons that matter, grouped by claimed technique, so a bump in the
     aggregate rate can be traced to a mechanism instead of shrugged at.

Standard library only, matching the rest of this project.
"""

from __future__ import annotations

import csv
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))

from analyse_sweep import ORDER, SHORT, STRICT, TIERS, b, load_sweep  # noqa: E402

Z95 = 1.959963985  # two-sided 95% normal quantile

# Comparisons the paper actually needs settled, beyond every adjacent step:
# the headline "does the honest floor differ from the p3 baseline" claim.
HEADLINE_PAIR = ("p3_historian", STRICT)


# --------------------------------------------------------------------------- #
#  pure-Python statistics — no scipy/numpy/pandas in this project on purpose
# --------------------------------------------------------------------------- #

def wilson_ci(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. Better-behaved than the
    normal approximation at small n or p near 0/1, both of which happen here
    (several tiers have violation rates under 5% on n=271)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def binom_two_sided_p(k: int, n: int, p: float = 0.5) -> float:
    """Exact two-sided binomial test p-value for k successes in n trials under
    H0: p=0.5. Used for McNemar's exact form on the discordant-pair count,
    which is preferred over the chi-square approximation when n (here, the
    number of discordant items) is small."""
    if n == 0:
        return 1.0
    pmf = [math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(n + 1)]
    p_k = pmf[k]
    # sum every outcome no more likely than the observed one — the standard
    # exact two-sided definition, avoids the asymmetry of doubling one tail.
    return min(1.0, sum(pk for pk in pmf if pk <= p_k + 1e-12))


def mcnemar_exact(rows_a: dict[str, bool], rows_b: dict[str, bool]
                   ) -> tuple[int, int, int, float]:
    """Paired exact McNemar test on capacity_violation status between two
    tiers for the same items. rows_a/rows_b: item_id -> violation bool.
    Returns (b_count, c_count, n_discordant, two_sided_p) where b = violation
    in A only, c = violation in B only (standard McNemar notation)."""
    items = sorted(set(rows_a) & set(rows_b))
    b_count = sum(1 for i in items if rows_a[i] and not rows_b[i])
    c_count = sum(1 for i in items if not rows_a[i] and rows_b[i])
    n_disc = b_count + c_count
    if n_disc == 0:
        return b_count, c_count, 0, 1.0
    p = binom_two_sided_p(min(b_count, c_count), n_disc)
    return b_count, c_count, n_disc, p


def spearman_exact(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Spearman rank correlation with an EXACT permutation p-value (all n!
    orderings of the tie-free rank vector), appropriate here since n=5 tiers
    is far too small for the usual asymptotic t-approximation to be trusted."""
    n = len(xs)

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mean_r = (n + 1) / 2
    num = sum((a - mean_r) * (bb - mean_r) for a, bb in zip(rx, ry))
    den = math.sqrt(sum((a - mean_r) ** 2 for a in rx)
                     * sum((bb - mean_r) ** 2 for bb in ry))
    rho = num / den if den else 0.0

    if n > 8:
        return rho, float("nan")  # not used here; sweep has n=5 tiers

    from itertools import permutations
    base_ranks = list(range(1, n + 1))
    obs = abs(rho)
    at_least_as_extreme = 0
    total = 0
    for perm in permutations(base_ranks):
        total += 1
        num_p = sum((a - mean_r) * (bb - mean_r) for a, bb in zip(rx, perm))
        den_p = math.sqrt(sum((a - mean_r) ** 2 for a in rx)
                           * sum((bb - mean_r) ** 2 for bb in perm))
        rho_p = num_p / den_p if den_p else 0.0
        if abs(rho_p) >= obs - 1e-12:
            at_least_as_extreme += 1
    return rho, at_least_as_extreme / total


# --------------------------------------------------------------------------- #
#  per-item violation maps
# --------------------------------------------------------------------------- #

def item_violations(rows: list[dict], resolved_only: bool = False
                     ) -> dict[str, bool]:
    """item_id -> capacity_violation bool. If resolved_only, drop items whose
    claimed id never resolved (matches analyse_sweep.py's violation_resolved
    denominator)."""
    out = {}
    for r in rows:
        if resolved_only and r["arm5_outcome"] == "unknown-technique":
            continue
        out[r["item"]] = b(r["capacity_violation"])
    return out


# --------------------------------------------------------------------------- #
#  report
# --------------------------------------------------------------------------- #

def main() -> None:
    sweep = load_sweep()
    if not sweep:
        print("no out/experiment_sweep_*.csv found — run run_sweep.py first")
        return
    models = sorted({m for m, _ in sweep})

    print("=" * 88)
    print("1. WILSON 95% CONFIDENCE INTERVALS ON VIOLATION RATE, PER TIER")
    print("=" * 88)
    print("(n=271 per tier; 'raw' = capacity_violation over all items, "
          "'res' = id-resolved subset only)\n")
    for model in models:
        print(f"--- {model} ---")
        print(f"{'profile':<14}{'k/n':>10}{'raw rate':>10}{'95% CI':>18}"
              f"{'res k/n':>10}{'res rate':>10}{'95% CI':>18}")
        for p in ORDER:
            rows = sweep.get((model, p))
            if not rows:
                continue
            n = len(rows)
            k = sum(b(r["capacity_violation"]) for r in rows)
            lo, hi = wilson_ci(k, n)
            resolved = [r for r in rows if r["arm5_outcome"] != "unknown-technique"]
            nr = len(resolved)
            kr = sum(b(r["capacity_violation"]) for r in resolved)
            lor, hir = wilson_ci(kr, nr) if nr else (0.0, 0.0)
            print(f"{SHORT[p]:<14}{k:>3}/{n:<6}{k/n:>9.1%} "
                  f"[{lo:>5.1%},{hi:>5.1%}] "
                  f"{kr:>3}/{nr:<6}{(kr/nr if nr else 0):>9.1%} "
                  f"[{lor:>5.1%},{hir:>5.1%}]")
        print()

    print("=" * 88)
    print("2. McNEMAR'S EXACT TEST — PAIRED, ADJACENT TIERS (id-resolved items)")
    print("=" * 88)
    print("H0: the violation rate does not change between the two tiers.")
    print("b = violation only at the earlier tier, c = violation only at the later tier.")
    print("A significant p with c > b is real evidence of decline; c < b is a real rise.\n")
    for model in models:
        print(f"--- {model} ---")
        print(f"{'comparison':<24}{'b':>5}{'c':>5}{'n_disc':>8}{'p (2-sided)':>14}"
              f"{'verdict':>28}")
        seq = [p for p in TIERS if (model, p) in sweep]
        pairs = list(zip(seq, seq[1:]))
        if (model, "p3_historian") in sweep and (model, STRICT) in sweep:
            pairs.append(HEADLINE_PAIR)
        for pa, pb_ in pairs:
            va = item_violations(sweep[(model, pa)], resolved_only=True)
            vb = item_violations(sweep[(model, pb_)], resolved_only=True)
            bc, cc, nd, p = mcnemar_exact(va, vb)
            if p >= 0.05 or nd == 0:
                verdict = "no significant change"
            elif cc < bc:
                verdict = "SIGNIFICANT DECLINE"
            else:
                verdict = "SIGNIFICANT RISE"
            label = f"{SHORT.get(pa, pa)}->{SHORT.get(pb_, pb_)}"
            print(f"{label:<24}{bc:>5}{cc:>5}{nd:>8}{p:>14.4f}{verdict:>28}")
        print()

    print("=" * 88)
    print("3. TREND TEST — SPEARMAN RANK CORRELATION, VIOLATION vs. INSTRUMENTATION")
    print("=" * 88)
    print("Tests the actual H1 claim (violation trends down with instrumentation)")
    print("rather than the pointwise 'never rises once' criterion. Exact")
    print(f"permutation p-value over all {math.factorial(len(TIERS))} tier orderings "
          f"(n={len(TIERS)} tiers, too few for the usual asymptotic test).\n")
    print(f"{'model':<20}{'rho':>8}{'exact p':>10}{'reading':>34}")
    for model in models:
        xs, ys = [], []
        for i, p in enumerate(TIERS):
            rows = sweep.get((model, p))
            if not rows:
                continue
            resolved = [r for r in rows if r["arm5_outcome"] != "unknown-technique"]
            rate = (sum(b(r["capacity_violation"]) for r in resolved) / len(resolved)
                    if resolved else 0.0)
            xs.append(float(i))
            ys.append(rate)
        if len(xs) < 3:
            continue
        rho, p_exact = spearman_exact(xs, ys)
        if p_exact < 0.05 and rho < 0:
            reading = "significant downward trend"
        elif p_exact < 0.05 and rho > 0:
            reading = "significant UPWARD trend"
        else:
            reading = "no significant trend"
        print(f"{model:<20}{rho:>+8.3f}{p_exact:>10.4f}{reading:>34}")
    print()

    print("=" * 88)
    print("4. ITEM-LEVEL ATTRIBUTION — what's driving the p3->p5b headline move")
    print("=" * 88)
    print("Items whose id-resolved capacity_violation status flips between p3_historian")
    print("and the strict floor, grouped by the technique the model claimed.\n")
    for model in models:
        if (model, "p3_historian") not in sweep or (model, STRICT) not in sweep:
            continue
        v3 = item_violations(sweep[(model, "p3_historian")], resolved_only=True)
        v5b = item_violations(sweep[(model, STRICT)], resolved_only=True)
        claimed_at = {r["item"]: r["claimed_id"] for r in sweep[(model, STRICT)]}
        cleared, newly_violated = [], []
        for item in sorted(set(v3) & set(v5b)):
            if v3[item] and not v5b[item]:
                cleared.append(item)
            elif not v3[item] and v5b[item]:
                newly_violated.append(item)
        print(f"--- {model} ---  "
              f"{len(cleared)} cleared (violation -> pass), "
              f"{len(newly_violated)} newly violated (pass -> violation)")

        def by_technique(items: list[str]) -> Counter:
            return Counter(claimed_at.get(i, "?") for i in items)

        if cleared:
            top = by_technique(cleared).most_common(5)
            print(f"  cleared, top claimed techniques : "
                  + ", ".join(f"{t}x{n}" for t, n in top))
        if newly_violated:
            top = by_technique(newly_violated).most_common(5)
            print(f"  newly violated, top techniques  : "
                  + ", ".join(f"{t}x{n}" for t, n in top))
        net = len(cleared) - len(newly_violated)
        print(f"  net change: {net:+d} items "
              f"({'net improvement' if net > 0 else 'net regression' if net < 0 else 'no net change'})")
        print()


if __name__ == "__main__":
    main()
