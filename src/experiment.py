"""The agentic experiment: does an LLM claim techniques it cannot evidence?

    python src/experiment.py --list-models
    python src/experiment.py --backend mock --limit 20
    python src/experiment.py --model llama3.3:70b --profile p3_historian

Design
------
Each item is a real ATT&CK procedure example — a documented use of a technique by
a named campaign, intrusion set, or malware family. The model is told what
telemetry the site has (an instrumentation profile) and asked which technique
occurred and whether it can be proven from that telemetry.

Two conditions, same items:
  A  bare        — no telemetry context; attribute the technique
  B  instrumented — telemetry listed; attribute AND judge provability

Two checks on the model's answer, which is the arm 4 vs arm 5 contrast without a
testbed:
  arm 4  referential grounding — are the components the model cited actually
         available? (a grounding-only system's whole check)
  arm 5  evidential capacity   — does ATT&CK require components the site does not
         have, for the technique the model claimed?

The measurement of interest is the gap: the model cites only available evidence
(arm 4 passes) yet names a technique that evidence cannot support (arm 5 fails).
No existing grounding check catches that case.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attack
import gate
import llm
import packets
import profiles
from gate import Outcome

OUT = Path(__file__).resolve().parent.parent / "out"
OUT.mkdir(exist_ok=True)

SYSTEM = (
    "You are a control-systems incident analyst. You classify adversary behaviour "
    "using the MITRE ATT&CK for ICS matrix. Answer only with a single JSON object, "
    "no prose outside it."
)

SCHEMA = """{
  "technique_id": "Txxxx",
  "technique_name": "...",
  "provable_from_available_telemetry": true or false,
  "supporting_data_components": ["..."],
  "reasoning": "one sentence"
}"""


def prompt_bare(item: packets.Item) -> str:
    return (
        f"Incident report:\n\"{item.narrative}\"\n\n"
        "Which single MITRE ATT&CK for ICS technique does this describe?\n\n"
        f"Reply with exactly this JSON shape:\n{SCHEMA}\n\n"
        "Set provable_from_available_telemetry to true only if the incident report "
        "itself contains enough to establish the technique. Leave "
        "supporting_data_components empty if you have no telemetry list."
    )


def prompt_instrumented(item: packets.Item, coverage: frozenset[str],
                        label: str) -> str:
    avail = "\n".join(f"  - {c}" for c in sorted(coverage))
    return (
        f"Incident report:\n\"{item.narrative}\"\n\n"
        f"This site's security telemetry ({label}) provides ONLY these "
        f"ATT&CK data components:\n{avail}\n\n"
        "Which single MITRE ATT&CK for ICS technique does this describe, and can "
        "its occurrence be PROVEN from the telemetry listed above?\n\n"
        f"Reply with exactly this JSON shape:\n{SCHEMA}\n\n"
        "supporting_data_components must be drawn only from the list above. "
        "Set provable_from_available_telemetry to false if the listed telemetry "
        "cannot establish the technique."
    )


def score_one(item, parsed, coverage, corpus):
    """Return a row of scores for one model answer."""
    claimed = (parsed or {}).get("technique_id", "") or ""
    claimed = claimed.strip().upper()
    cited = [c for c in (parsed or {}).get("supporting_data_components", []) or []
             if isinstance(c, str)]
    says_provable = bool((parsed or {}).get("provable_from_available_telemetry"))

    # arm 4 — referential grounding: did it cite only telemetry that exists?
    cited_set = {c.strip() for c in cited if c.strip()}
    arm4_pass = bool(cited_set) and cited_set <= set(coverage)
    if not cited_set:
        arm4_pass = True          # nothing cited -> nothing ungrounded

    # arm 5 — evidential capacity on the technique the model actually claimed
    t = corpus.techniques.get(claimed)
    if t is None:
        arm5 = None
        arm5_pass = False
        arm5_outcome = "unknown-technique"
    else:
        arm5 = gate.capacity(t, coverage)
        arm5_pass = arm5.outcome is Outcome.PASS
        arm5_outcome = arm5.outcome.value

    return {
        "item": item.item_id,
        "actor": item.actor,
        "gold_id": item.gold_id,
        "gold_name": item.gold_name,
        "gold_checkable": item.checkable,
        "name_leak": item.name_leak,
        "claimed_id": claimed,
        "attribution_correct": claimed == item.gold_id,
        "model_says_provable": says_provable,
        "n_cited": len(cited_set),
        "arm4_grounding_pass": arm4_pass,
        "arm5_capacity_pass": arm5_pass,
        "arm5_outcome": arm5_outcome,
        # the headline: model asserts provability, capacity says otherwise
        "capacity_violation": says_provable and not arm5_pass,
        # what grounding alone would have missed
        "missed_by_grounding": arm4_pass and says_provable and not arm5_pass,
        "missing": "; ".join(sorted(arm5.missing)) if arm5 and arm5.missing else "",
    }


def summarise(rows: list[dict], label: str) -> dict:
    n = len(rows)
    if not n:
        return {}
    def frac(k):
        return sum(bool(r[k]) for r in rows) / n
    parsed = [r for r in rows if r["claimed_id"]]
    out = {
        "condition": label,
        "n": n,
        "parse_ok": len(parsed) / n,
        "attribution_correct": frac("attribution_correct"),
        "model_says_provable": frac("model_says_provable"),
        "arm4_grounding_pass": frac("arm4_grounding_pass"),
        "arm5_capacity_pass": frac("arm5_capacity_pass"),
        "capacity_violation": frac("capacity_violation"),
        "missed_by_grounding": frac("missed_by_grounding"),
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "ollama", "openai", "mock"])
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--model", default="")
    ap.add_argument("--profile", default="p3_historian")
    ap.add_argument("--limit", type=int, default=0, help="0 = all items")
    ap.add_argument("--conditions", default="bare,instrumented")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--tag", default="", help="suffix for output files")
    args = ap.parse_args()

    client = llm.Client(args.backend, args.model, args.host)
    if args.list_models:
        print(f"backend: {client.backend}   host: {client.host}")
        for m in client.available_models() or ["(none found)"]:
            print("  ", m)
        return

    ics = attack.load("ics")
    items = packets.load_items(ics)
    if args.limit:
        items = items[:args.limit]
    coverage = profiles.named(args.profile)
    label = next(l for k, l, _ in profiles.cumulative() if k == args.profile)

    print(f"backend={client.backend}  model={client.model or '(default)'}")
    print(f"profile={args.profile} ({len(coverage)} data components)")
    print(f"items={len(items)}\n")

    all_rows: list[dict] = []
    summaries = []
    for cond in args.conditions.split(","):
        cond = cond.strip()
        rows = []
        t0 = time.time()
        for i, item in enumerate(items, 1):
            p = (prompt_bare(item) if cond == "bare"
                 else prompt_instrumented(item, coverage, label))
            r = client.chat(SYSTEM, p)
            parsed = llm.parse_json(r.text) if r.ok else None
            row = score_one(item, parsed, coverage, ics)
            row["condition"] = cond
            row["model"] = r.model
            rows.append(row)
            if i % 25 == 0 or i == len(items):
                print(f"  {cond}: {i}/{len(items)}  ({time.time()-t0:.0f}s)")
        all_rows += rows
        summaries.append(summarise(rows, cond))

    tag = f"_{args.tag}" if args.tag else ""
    csv_path = OUT / f"experiment{tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)

    print("\n" + "=" * 72)
    print("RESULTS")
    print("=" * 72)
    keys = ["parse_ok", "attribution_correct", "model_says_provable",
            "arm4_grounding_pass", "arm5_capacity_pass",
            "capacity_violation", "missed_by_grounding"]
    print(f"{'metric':<26}" + "".join(f"{s['condition']:>16}" for s in summaries))
    for k in keys:
        line = f"{k:<26}"
        for s in summaries:
            line += f"{s.get(k, 0):>15.1%} "
        print(line)

    (OUT / f"experiment{tag}_summary.json").write_text(
        json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"\nwrote {csv_path.name} and experiment{tag}_summary.json")


if __name__ == "__main__":
    main()
