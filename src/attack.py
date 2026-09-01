"""
Load MITRE ATT&CK STIX bundles and resolve the v18+ detection chain:

    Technique  <--detects--  DetectionStrategy
                                  |  x_mitre_analytic_refs
                                  v
                              Analytic
                                  |  x_mitre_log_source_references[].x_mitre_data_component_ref
                                  v
                            DataComponent

This is the substrate for the evidential capacity gate. Nothing here is authored
by us: the requirement side comes from the published bundle unmodified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


# --------------------------------------------------------------------------- #
#  model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Analytic:
    stix_id: str
    attack_id: str          # ANxxxx
    name: str
    data_components: frozenset[str]   # data component NAMES, e.g. "Process Creation"
    platforms: tuple[str, ...]

    def satisfied_by(self, coverage: frozenset[str]) -> bool:
        """All required data components present -> this route is available."""
        return self.data_components <= coverage

    def missing_from(self, coverage: frozenset[str]) -> frozenset[str]:
        return self.data_components - coverage


@dataclass(frozen=True)
class DetectionStrategy:
    stix_id: str
    attack_id: str          # DETxxxx
    name: str
    analytics: tuple[Analytic, ...]


@dataclass(frozen=True)
class Technique:
    stix_id: str
    attack_id: str          # Txxxx / Txxxx.yyy
    name: str
    is_subtechnique: bool
    domain: str             # "ics" | "enterprise"
    strategies: tuple[DetectionStrategy, ...]

    @property
    def analytics(self) -> tuple[Analytic, ...]:
        return tuple(a for s in self.strategies for a in s.analytics)

    @property
    def has_detection(self) -> bool:
        return any(s.analytics for s in self.strategies)


@dataclass
class Corpus:
    domain: str
    version: str
    techniques: dict[str, Technique] = field(default_factory=dict)   # keyed by Txxxx
    data_components: dict[str, str] = field(default_factory=dict)    # stix_id -> name

    @property
    def all_data_component_names(self) -> frozenset[str]:
        return frozenset(self.data_components.values())

    def __len__(self) -> int:
        return len(self.techniques)


# --------------------------------------------------------------------------- #
#  loading
# --------------------------------------------------------------------------- #

def _attack_id(obj: dict) -> str:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") in ("mitre-attack", "mitre-ics-attack"):
            return ref.get("external_id", "")
    return ""


def _live(obj: dict) -> bool:
    """Exclude deprecated and revoked objects — they are not part of the current model."""
    return not obj.get("x_mitre_deprecated") and not obj.get("revoked")


def load(domain: str, version: str = "19.2") -> Corpus:
    path = DATA / f"{domain}-{version}.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    objs = [o for o in bundle["objects"] if _live(o)]
    by_id = {o["id"]: o for o in objs}

    # data components: stix id -> human name
    data_components = {
        o["id"]: o["name"] for o in objs if o["type"] == "x-mitre-data-component"
    }

    # analytics
    analytics: dict[str, Analytic] = {}
    for o in objs:
        if o["type"] != "x-mitre-analytic":
            continue
        dcs = set()
        for ref in o.get("x_mitre_log_source_references", []):
            dc_id = ref.get("x_mitre_data_component_ref")
            if dc_id in data_components:
                dcs.add(data_components[dc_id])
        analytics[o["id"]] = Analytic(
            stix_id=o["id"],
            attack_id=_attack_id(o),
            name=o.get("name", ""),
            data_components=frozenset(dcs),
            platforms=tuple(o.get("x_mitre_platforms", [])),
        )

    # detection strategies
    strategies: dict[str, DetectionStrategy] = {}
    for o in objs:
        if o["type"] != "x-mitre-detection-strategy":
            continue
        ans = tuple(
            analytics[a] for a in o.get("x_mitre_analytic_refs", []) if a in analytics
        )
        strategies[o["id"]] = DetectionStrategy(
            stix_id=o["id"],
            attack_id=_attack_id(o),
            name=o.get("name", ""),
            analytics=ans,
        )

    # strategy --detects--> technique
    detects: dict[str, list[DetectionStrategy]] = {}
    for o in objs:
        if o["type"] != "relationship" or o.get("relationship_type") != "detects":
            continue
        src, tgt = o["source_ref"], o["target_ref"]
        if src in strategies and tgt in by_id:
            detects.setdefault(tgt, []).append(strategies[src])

    techniques: dict[str, Technique] = {}
    for o in objs:
        if o["type"] != "attack-pattern":
            continue
        tid = _attack_id(o)
        if not tid:
            continue
        techniques[tid] = Technique(
            stix_id=o["id"],
            attack_id=tid,
            name=o.get("name", ""),
            is_subtechnique=bool(o.get("x_mitre_is_subtechnique")),
            domain=domain,
            strategies=tuple(detects.get(o["id"], [])),
        )

    return Corpus(
        domain=domain,
        version=version,
        techniques=techniques,
        data_components=data_components,
    )
