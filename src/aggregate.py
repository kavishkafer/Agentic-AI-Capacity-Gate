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
        if p.name.startswith("experiment_sweep_"):
            continue    # profile-sweep runs have their own analyser
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


PROFILE = "p3_historian"        # the profile the first experiment ran at


def _ontology():
    """(corpus, coverage) for the derived metrics; None if the bundle is absent
    so the aggregation still runs on a machine without the data files."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import attack, profiles                       # noqa: E402
        return attack.load("ics"), profiles.named(PROFILE)
    except Exception:
        return None


def derive(rows, onto) -> list[dict]:
    """Per-row derived fields the raw CSVs do not carry.

    The as-scored `capacity_violation` conflates three classes with different
    meanings: `fail` (id resolves, ontology consulted, evidence structurally
    insufficient — the only class invisible to referential grounding by
    construction), `undefined` (ontology specifies no requirements), and
    `unknown-technique` (id does not resolve — exactly what a DeepFaith-class
    id-resolution check catches, so it must never be counted as
    grounding-invisible).

    The `remap_*` variants resolve v19-revoked ids (T0857 -> T1693.001 etc.)
    before consulting the ontology: the renumbering postdates every evaluated
    model's training data, so scoring a stale-but-correct id as a hallucination
    would measure recency, not capacity."""
    import gate                                       # noqa: E402
    from gate import Outcome                          # noqa: E402
    ics, cov = onto
    out = []
    for r in rows:
        says = _b(r["model_says_provable"])
        rid = ics.resolve(r.get("claimed_id", ""))
        t = ics.techniques.get(rid)
        rcls = "unknown-technique" if t is None else gate.capacity(t, cov).outcome.value
        out.append({
            "says": says,
            "cls": r.get("arm5_outcome", ""),
            "remap_cls": rcls,
            "viol": _b(r["capacity_violation"]),
            "viol_remap": says and rcls != "pass",
            "attrib_remap": rid == (r.get("gold_id") or "").strip().upper(),
        })
    return out


def _dfrac(ds, pred) -> float:
    return sum(pred(d) for d in ds) / len(ds) if ds else 0.0


def main() -> None:
    runs = load_runs()
    if not runs:
        print("no experiment_*.csv in out/ — run src/experiment.py first")
        return

    conditions = sorted({r["condition"] for rs in runs.values() for r in rs})
    slices = ["overall", "correct", "noleak", "checkable"]
    onto = _ontology()

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
                row = {
                    "model": model, "condition": cond, "slice": sl, "n": len(srs),
                    "parse_ok": round(frac(srs, "claimed_id"), 4),
                    "attribution_correct": round(frac(srs, "attribution_correct"), 4),
                    "model_says_provable": round(frac(srs, "model_says_provable"), 4),
                    "arm4_grounding_pass": round(frac(srs, "arm4_grounding_pass"), 4),
                    "arm5_capacity_pass": round(frac(srs, "arm5_capacity_pass"), 4),
                    "capacity_violation": round(frac(srs, "capacity_violation"), 4),
                    "missed_by_grounding": round(frac(srs, "missed_by_grounding"), 4),
                }
                if onto:
                    ds = derive(srs, onto)
                    row.update({
                        "violation_fail": round(_dfrac(ds,
                            lambda d: d["viol"] and d["cls"] == "fail"), 4),
                        "violation_undefined": round(_dfrac(ds,
                            lambda d: d["viol"] and d["cls"] == "undefined"), 4),
                        "violation_unknown_id": round(_dfrac(ds,
                            lambda d: d["viol"] and d["cls"] == "unknown-technique"), 4),
                        "violation_grounding_invisible": round(_dfrac(ds,
                            lambda d: d["viol"] and d["cls"] in ("fail", "undefined")), 4),
                        "capacity_violation_remapped": round(_dfrac(ds,
                            lambda d: d["viol_remap"]), 4),
                        "grounding_invisible_remapped": round(_dfrac(ds,
                            lambda d: d["viol_remap"]
                            and d["remap_cls"] in ("fail", "undefined")), 4),
                        "attribution_remapped": round(_dfrac(ds,
                            lambda d: d["attrib_remap"]), 4),
                    })
                out_rows.append(row)

    # slice detail for the headline metric
    print("\n" + "=" * 88)
    print("CAPACITY VIOLATION BY SLICE  (does the finding survive stricter reading?)")
    print("=" * 88)
    print(f"{'model':<26}{'condition':<14}" + "".join(f"{s:>16}" for s in slices))
    for model, rows in sorted(runs.items()):
        for cond in conditions:
            rs = [r for r in rows if r["condition"] == cond]
            if not rs:
                continue
            line = f"{model[:25]:<26}{cond:<14}"
            for sl in slices:
                srs = slice_rows(rs, sl)
                cell = f"{frac(srs,'capacity_violation'):.0%} (n={len(srs)})"
                line += f"{cell:>16}"
            print(line)
    print("\nQuote no slice without its n: the correct-attribution slice can be")
    print("a handful of items.")

    if onto:
        print("\n" + "=" * 88)
        print("VIOLATION DECOMPOSITION  (what class of failure is each violation?)")
        print("=" * 88)
        print("fail        id resolves, ontology consulted, evidence structurally")
        print("            insufficient -- the ONLY class invisible to referential")
        print("            grounding by construction")
        print("undefined   ontology specifies no requirements (visible to neither)")
        print("unknown-id  id does not resolve -- an id-resolution grounding check")
        print("            catches these; never count them as grounding-invisible")
        print("remapped    v19-revoked ids resolved to their current ids first\n")
        hdr = (f"{'model':<26}{'cond':<8}{'VIOL':>7}{'=fail':>8}{'+undef':>8}"
               f"{'+unk-id':>9}{'ground-inv':>12}{'g-inv rmap':>12}{'attr rmap':>11}")
        print(hdr)
        for model, rows in sorted(runs.items()):
            for cond in conditions:
                rs = [r for r in rows if r["condition"] == cond]
                if not rs:
                    continue
                ds = derive(rs, onto)
                f_ = lambda p: _dfrac(ds, p)
                print(f"{model[:25]:<26}{cond[:7]:<8}"
                      f"{f_(lambda d: d['viol']):>7.0%}"
                      f"{f_(lambda d: d['viol'] and d['cls']=='fail'):>8.0%}"
                      f"{f_(lambda d: d['viol'] and d['cls']=='undefined'):>8.0%}"
                      f"{f_(lambda d: d['viol'] and d['cls']=='unknown-technique'):>9.0%}"
                      f"{f_(lambda d: d['viol'] and d['cls'] in ('fail','undefined')):>12.0%}"
                      f"{f_(lambda d: d['viol_remap'] and d['remap_cls'] in ('fail','undefined')):>12.0%}"
                      f"{f_(lambda d: d['attrib_remap']):>11.0%}")

    with (OUT / "crossmodel.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote out/crossmodel.csv ({len(out_rows)} rows)")

    _figure(runs, conditions, onto)


def _figure(runs, conditions, onto=None) -> None:
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
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    xs = list(range(len(models)))

    # Stack the assertion rate by what the ontology says about each claim.
    # The violation classes are NOT interchangeable: only `fail` is invisible
    # to referential grounding by construction; an unknown id is exactly what
    # an id-resolution check catches. Painting them one colour overstated the
    # contribution, so each class gets its own segment.
    UNDEF, GREY = "#f2a06b", "#a9a8a2"
    segs = [
        ("asserted, supportable",
         lambda d: d["says"] and d["cls"] == "pass", BLUE),
        ("asserted, evidence insufficient (fail)",
         lambda d: d["viol"] and d["cls"] == "fail", ORANGE),
        ("asserted, ontology silent (undefined)",
         lambda d: d["viol"] and d["cls"] == "undefined", UNDEF),
        ("asserted, id does not resolve",
         lambda d: d["viol"] and d["cls"] == "unknown-technique", GREY),
    ]
    heights: list[list[float]] = []
    for model in models:
        rs = [r for r in runs[model] if r["condition"] == cond]
        if onto:
            ds = derive(rs, onto)
            heights.append([_dfrac(ds, pred) for _, pred, _ in segs])
        else:                      # bundle absent: two-way split only
            v = frac(rs, "capacity_violation")
            heights.append([max(0.0, frac(rs, "model_says_provable") - v),
                            v, 0.0, 0.0])

    bottoms = [0.0] * len(models)
    for si, (lbl, _pred, colour) in enumerate(segs):
        vals = [h[si] for h in heights]
        ax.bar(xs, vals, width=0.55, bottom=bottoms, color=colour,
               edgecolor=SURFACE, linewidth=1.5, label=lbl)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    supported = [h[0] for h in heights]
    violating = [sum(h[1:]) for h in heights]

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

    for x, h in enumerate(heights):
        gi = h[1] + h[2]
        ax.text(x, sum(h) + 0.012, f"{gi:.0%} grounding-invisible",
                ha="center", fontsize=8, color=INK2)

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
    leg = ax.legend(frameon=False, fontsize=7.5, loc="upper left",
                    bbox_to_anchor=(1.01, 1.0))
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
