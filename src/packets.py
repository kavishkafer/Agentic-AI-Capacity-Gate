"""Build incident items from ATT&CK's documented procedure examples.

Each item is a real, MITRE-authored description of a technique being used in a
named campaign, intrusion set, or malware family — with the technique itself as
ground truth. 271 such procedures exist in ICS v19.2, covering 86 of 97
techniques.

Why this source and not synthetic scenarios
-------------------------------------------
The experiment must not be circular. If we synthesised evidence from a
technique's own data-component requirements, the capacity gate would pass by
construction. Procedure descriptions are written independently of the detection
model — they describe what the adversary *did*, not what telemetry would record
it — so the narrative and the requirement side come from different places.

The leakage problem, and why it helps us
----------------------------------------
Procedure descriptions frequently paraphrase the technique name ("...by
modifying parameters" for Modify Parameter). That inflates attribution accuracy.

This does not weaken the measurement — it strengthens it. Our headline is not
whether the model names the right technique; it is whether the model claims a
technique it *cannot prove* from the telemetry it has been told is available.
Handing the model the easiest possible attribution task and still observing
over-claiming is the stronger result, because poor attribution cannot be blamed.

We flag leakage per item anyway (`name_leak`) and report results split both ways.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# words too generic for a leak test
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "via", "with",
    "system", "systems", "device", "devices", "data", "information", "service",
    "services", "control", "controls", "network", "networks", "i/o", "module",
}

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CITATION = re.compile(r"\(Citation:[^)]*\)")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Item:
    item_id: str
    narrative: str          # cleaned procedure description
    gold_id: str            # ground-truth technique, e.g. T0836
    gold_name: str
    actor: str              # campaign / malware / intrusion-set name
    actor_type: str
    name_leak: bool         # does the technique name appear in the narrative?
    required: frozenset[str]  # data components ATT&CK requires for gold_id
    checkable: bool         # False when the technique is UNDEFINED (no requirements)


def _clean(text: str, actor: str) -> str:
    """Strip markdown links and citations. Keep the actor name — it identifies the
    incident and is information a real analyst would have."""
    t = _MD_LINK.sub(r"\1", text or "")
    t = _CITATION.sub("", t)
    return _WS.sub(" ", t).strip()


def _leaks(technique_name: str, narrative: str) -> bool:
    """True if the technique's distinctive words appear in the narrative."""
    words = {w for w in re.findall(r"[a-z]+", technique_name.lower())
             if w not in _STOP and len(w) > 3}
    if not words:
        return False
    low = narrative.lower()
    # stem-ish match: 'modifying' should hit 'modify'
    return all(any(w[:max(4, len(w) - 2)] in low for _ in (0,)) for w in words)


def load_items(corpus, version: str = "19.2") -> list[Item]:
    """corpus: an attack.Corpus for the same domain/version (supplies requirements)."""
    raw = json.loads((DATA / f"ics-{version}.json").read_text(encoding="utf-8"))
    objs = [o for o in raw["objects"]
            if not o.get("x_mitre_deprecated") and not o.get("revoked")]
    by_id = {o["id"]: o for o in objs}

    # stix id -> attack id, for techniques
    tech_attack_id = {}
    for o in objs:
        if o["type"] != "attack-pattern":
            continue
        for ref in o.get("external_references", []):
            if ref.get("source_name") in ("mitre-attack", "mitre-ics-attack"):
                tech_attack_id[o["id"]] = ref.get("external_id", "")

    items: list[Item] = []
    n = 0
    for o in objs:
        if o.get("relationship_type") != "uses":
            continue
        tgt = by_id.get(o.get("target_ref", ""))
        src = by_id.get(o.get("source_ref", ""))
        if not tgt or not src or tgt.get("type") != "attack-pattern":
            continue
        desc = (o.get("description") or "").strip()
        if not desc:
            continue

        tid = tech_attack_id.get(tgt["id"], "")
        t = corpus.techniques.get(tid)
        if not t:
            continue

        actor = src.get("name", "unknown")
        narrative = _clean(desc, actor)
        if len(narrative) < 40:          # too thin to reason about
            continue

        req: frozenset[str] = frozenset()
        checkable = False
        if t.analytics:
            req = t.analytics[0].data_components
            checkable = bool(req)

        n += 1
        items.append(Item(
            item_id=f"P{n:03d}",
            narrative=narrative,
            gold_id=tid,
            gold_name=t.name,
            actor=actor,
            actor_type=src.get("type", "?"),
            name_leak=_leaks(t.name, narrative),
            required=req,
            checkable=checkable,
        ))
    return items


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attack

    ics = attack.load("ics")
    items = load_items(ics)
    leaked = sum(i.name_leak for i in items)
    checkable = sum(i.checkable for i in items)
    print(f"items                 : {len(items)}")
    print(f"  distinct techniques : {len({i.gold_id for i in items})}")
    print(f"  name leak           : {leaked} ({leaked/len(items):.0%})")
    print(f"  checkable (has reqs): {checkable} ({checkable/len(items):.0%})")
    print(f"  UNDEFINED gold      : {len(items)-checkable}")
    print("\nsample:")
    for i in items[:3]:
        print(f"\n  {i.item_id}  gold={i.gold_id} {i.gold_name}  leak={i.name_leak}")
        print(f"    actor: {i.actor} ({i.actor_type})")
        print(f"    requires: {sorted(i.required) or '— none (UNDEFINED) —'}")
        print(f"    {i.narrative[:180]}")
