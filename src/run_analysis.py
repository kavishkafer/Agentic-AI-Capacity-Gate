"""Produce the paper's measurement results.

    python src/run_analysis.py

Writes CSVs to out/ and prints the summary tables.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attack
import gate
import profiles
from gate import Outcome

OUT = Path(__file__).resolve().parent.parent / "out"
OUT.mkdir(exist_ok=True)


def counts(verdicts) -> Counter:
    return Counter(v.outcome for v in verdicts.values())


def main() -> None:
    ics = attack.load("ics")
    ent = attack.load("ent")

    # ------------------------------------------------------------------ #
    print("=" * 70)
    print("TABLE 1 — Detection-chain structure (ATT&CK v19.2, non-deprecated)")
    print("=" * 70)
    print(f"{'':<26}{'ICS':>10}{'Enterprise':>14}")
    rows = [
        ("techniques", len(ics.techniques), len(ent.techniques)),
        ("data components", len(ics.all_data_component_names),
         len(ent.all_data_component_names)),
        ("analytics per technique",
         f"{sum(len(t.analytics) for t in ics.techniques.values())/len(ics.techniques):.2f}",
         f"{sum(len(t.analytics) for t in ent.techniques.values())/len(ent.techniques):.2f}"),
        ("max analytics (routes)",
         max(len(t.analytics) for t in ics.techniques.values()),
         max(len(t.analytics) for t in ent.techniques.values())),
    ]
    for label, a, b in rows:
        print(f"{label:<26}{str(a):>10}{str(b):>14}")

    for name, c in (("ICS", ics), ("Enterprise", ent)):
        cnt = counts(gate.evaluate_corpus(c, c.all_data_component_names))
        print(f"{name+' UNDEFINED':<26}{cnt[Outcome.UNDEFINED]:>10}"
              f"  ({cnt[Outcome.UNDEFINED]/len(c.techniques):.1%} of techniques)")

    # ------------------------------------------------------------------ #
    print()
    print("=" * 70)
    print("TABLE 2 — Evidenceable ICS techniques by instrumentation profile")
    print("=" * 70)
    print(f"{'profile':<34}{'PASS':>7}{'FAIL':>7}{'UNDEF':>7}{'% of checkable':>16}")

    prof_rows = []
    for key, label, cov in profiles.cumulative():
        v = gate.evaluate_corpus(ics, cov)
        c = counts(v)
        checkable = c[Outcome.PASS] + c[Outcome.FAIL]
        pct = c[Outcome.PASS] / checkable if checkable else 0.0
        print(f"{label:<34}{c[Outcome.PASS]:>7}{c[Outcome.FAIL]:>7}"
              f"{c[Outcome.UNDEFINED]:>7}{pct:>15.1%}")
        prof_rows.append({
            "profile": key, "label": label, "n_components": len(cov),
            "pass": c[Outcome.PASS], "fail": c[Outcome.FAIL],
            "undefined": c[Outcome.UNDEFINED], "pct_of_checkable": round(pct, 4),
        })

    with (OUT / "profiles_ics.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(prof_rows[0]))
        w.writeheader()
        w.writerows(prof_rows)

    # ------------------------------------------------------------------ #
    print()
    print("=" * 70)
    print("TABLE 3 — Criticality: techniques lost if a single component is absent")
    print("=" * 70)
    for domain_name, corpus in (("ICS", ics), ("Enterprise", ent)):
        crit = [r for r in gate.criticality(corpus) if r[1] > 0]
        print(f"\n{domain_name} — top 10 of {len(crit)} load-bearing components")
        for dc, lost in crit[:10]:
            share = lost / len(corpus.techniques)
            print(f"   {lost:5}  ({share:5.1%})  {dc}")
        with (OUT / f"criticality_{domain_name.lower()}.csv").open(
                "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["data_component", "techniques_lost", "share_of_domain"])
            for dc, lost in gate.criticality(corpus):
                w.writerow([dc, lost, round(lost / len(corpus.techniques), 4)])

    # ------------------------------------------------------------------ #
    print()
    print("=" * 70)
    print("TABLE 4 — Per-technique detail (ICS, typical deployment)")
    print("=" * 70)
    site = profiles.named("p3_historian")
    v = gate.evaluate_corpus(ics, site)
    with (OUT / "techniques_ics.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["technique", "name", "outcome", "n_routes",
                    "required", "missing", "reason"])
        for tid in sorted(v):
            t, ver = ics.techniques[tid], v[tid]
            req = sorted(t.analytics[0].data_components) if t.analytics else []
            w.writerow([tid, t.name, ver.outcome.value, ver.n_routes,
                        "; ".join(req), "; ".join(sorted(ver.missing)),
                        ver.rejection_reason])
    c = counts(v)
    print(f"   profile: network + DPI + historian ({len(site)} components)")
    print(f"   PASS {c[Outcome.PASS]} · FAIL {c[Outcome.FAIL]} · UNDEFINED {c[Outcome.UNDEFINED]}")

    print(f"\nCSVs written to {OUT}")


if __name__ == "__main__":
    main()
