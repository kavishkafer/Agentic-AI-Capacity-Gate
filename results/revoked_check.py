"""Post-hoc: how much of the measured signal is stale ATT&CK IDs, not capacity?

Reads an experiment CSV, resolves revoked->current technique IDs from the same
bundle the instrument uses, and re-scores. Does NOT modify the instrument.

    python revoked_check.py out/experiment_deepseek.csv
"""
from __future__ import annotations
import csv, json, sys
from pathlib import Path

REPO = Path("/home/dgx-spark-01/Research_Kavishka/CRCI 2026-PhD arch/Agentic-AI-Capacity-Gate")
sys.path.insert(0, str(REPO / "src"))
import attack, gate, profiles
from gate import Outcome


def revoked_map(version: str = "19.2") -> dict[str, tuple[str, str]]:
    """old attack-id -> (new attack-id, name)."""
    raw = json.loads((REPO / "data" / f"ics-{version}.json").read_text())
    by_id = {o["id"]: o for o in raw["objects"]}

    def aid(o):
        for r in o.get("external_references", []):
            if r.get("source_name") in ("mitre-attack", "mitre-ics-attack"):
                return r.get("external_id", "")
        return ""

    out = {}
    for o in raw["objects"]:
        if o.get("relationship_type") != "revoked-by":
            continue
        s, t = by_id.get(o.get("source_ref", "")), by_id.get(o.get("target_ref", ""))
        if s and t and s.get("type") == "attack-pattern":
            old, new = aid(s), aid(t)
            if old and new:
                out[old] = (new, t.get("name", ""))
    return out


def main(path: str) -> None:
    rmap = revoked_map()
    ics = attack.load("ics")
    coverage = profiles.named("p3_historian")
    rows = list(csv.DictReader(open(path)))

    print(f"revoked->current map ({len(rmap)} entries):")
    for old, (new, name) in sorted(rmap.items()):
        print(f"  {old:<10} -> {new:<12} {name}")
    print()

    conds = sorted({r["condition"] for r in rows})
    for cond in conds:
        sub = [r for r in rows if r["condition"] == cond]
        n = len(sub)
        stale = attr = attr_remap = 0
        viol_genuine = viol_stale = 0
        missed_genuine = 0
        for r in sub:
            claimed = r["claimed_id"]
            says = r["model_says_provable"] == "True"
            arm4 = r["arm4_grounding_pass"] == "True"
            unknown = r["arm5_outcome"] == "unknown-technique"
            eff = rmap.get(claimed, (claimed, ""))[0]
            was_stale = unknown and claimed in rmap
            stale += was_stale
            attr += claimed == r["gold_id"]
            attr_remap += eff == r["gold_id"]

            # re-score capacity on the remapped id
            t = ics.techniques.get(eff)
            if t is None:
                a5pass, resolved = False, False
            else:
                a5pass, resolved = gate.capacity(t, coverage).outcome is Outcome.PASS, True
            if says and not a5pass:
                if resolved:
                    viol_genuine += 1
                    missed_genuine += arm4
                else:
                    viol_stale += 1

        p = lambda x: f"{x/n:6.1%}"
        print(f"--- {cond}  (n={n}) ---")
        print(f"  unresolvable ids                  {p(n and stale)}  ({stale})  <- revoked in v19.2")
        print(f"  attribution_correct  as-scored    {p(attr)}  ({attr})")
        print(f"  attribution_correct  ID-remapped  {p(attr_remap)}  ({attr_remap})")
        print(f"  capacity_violation   GENUINE      {p(viol_genuine)}  ({viol_genuine})  <- ATT&CK consulted")
        print(f"  capacity_violation   stale-id     {p(viol_stale)}  ({viol_stale})  <- never checked")
        print(f"  missed_by_grounding  GENUINE      {p(missed_genuine)}  ({missed_genuine})")
        print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(REPO / "out/experiment_smoke.csv"))
