"""Claim model and Gates A and B.

Gate C lives in gate.py because it is the contribution and is checked against
ATT&CK's own data. Gates A and B are here: A is a restatement of existing
practice (referential grounding), B is the three-domain requirement function.

Note a structural fact that emerges here: ET (engineering / authorisation)
evidence has NO representation in ATT&CK's data-component vocabulary. There is
no component for change authorisation or management-of-change. ET sources
therefore contribute to domains(c) — which Gate B checks — but contribute
nothing to coverage(c), which Gate C checks. The two gates operate over
different vocabularies, which is precisely why both are needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Domain(Enum):
    IT = "IT"
    OT = "OT"
    ET = "ET"


class ClaimType(Enum):
    ACTOR = "Actor"                        # who did it
    IMPACT = "Impact"                      # what physically happened
    AUTHORISATION = "Authorisation"        # was it sanctioned
    JOIN = "Join"                          # two observations, same real event
    TECHNIQUE = "Technique"                # an ATT&CK technique occurred
    MALICIOUS_CHANGE = "MaliciousChange"   # a change, made by an actor, unsanctioned


# rho: claim type -> set of admissible domain-sets.  Any ONE set suffices;
# each set is all-or-nothing.  This is the three-domain asymmetry, formalised.
RHO: dict[ClaimType, tuple[frozenset[Domain], ...]] = {
    ClaimType.ACTOR:            (frozenset({Domain.IT}),),
    ClaimType.IMPACT:           (frozenset({Domain.OT}),),
    ClaimType.AUTHORISATION:    (frozenset({Domain.ET}),),
    ClaimType.JOIN:             (frozenset({Domain.IT, Domain.OT}),),
    ClaimType.TECHNIQUE:        (frozenset({Domain.IT}), frozenset({Domain.OT})),
    ClaimType.MALICIOUS_CHANGE: (frozenset({Domain.IT, Domain.ET}),
                                 frozenset({Domain.IT, Domain.OT, Domain.ET})),
}


@dataclass(frozen=True)
class Source:
    sid: str
    domain: Domain
    kappa: frozenset[str]        # ATT&CK data components this source can yield
    deployed: bool = True
    note: str = ""


@dataclass(frozen=True)
class Observation:
    oid: str                     # provenance ID
    source: Source
    asset: str
    t: int                       # minutes past midnight, for the toy scenario
    summary: str = ""


@dataclass(frozen=True)
class Claim:
    cid: str
    ctype: ClaimType
    subject: str                 # the asset or principal the claim is about
    window: tuple[int, int]
    cites: tuple[Observation, ...]
    text: str = ""
    technique: str | None = None       # required when ctype is TECHNIQUE
    derived_from: tuple[str, ...] = field(default_factory=tuple)

    @property
    def domains(self) -> frozenset[Domain]:
        return frozenset(o.source.domain for o in self.cites)

    @property
    def coverage(self) -> frozenset[str]:
        out: set[str] = set()
        for o in self.cites:
            out |= set(o.source.kappa)
        return frozenset(out)


# --------------------------------------------------------------------------- #
#  Gate A — referential grounding
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GateResult:
    passed: bool
    code: str = ""
    reason: str = ""


def gate_a(claim: Claim, known: set[str], reachable: dict[str, set[str]]
           ) -> GateResult:
    """Do the citations exist, concern the right asset, and fall in the window?

    `reachable[a]` is the set of assets that can reach asset `a` via a 62443
    conduit — needed because a claim about a PLC will legitimately cite
    observations from the jump host that reached it.
    """
    if not claim.cites:
        return GateResult(False, "R-A1", "claim cites no evidence")

    for o in claim.cites:
        if o.oid not in known:
            return GateResult(False, "R-A1", f"provenance {o.oid} does not resolve")

    for o in claim.cites:
        ok = o.asset == claim.subject or o.asset in reachable.get(claim.subject, set())
        if not ok:
            return GateResult(False, "R-A2",
                              f"{o.oid} concerns {o.asset}, not {claim.subject}")
        if not (claim.window[0] <= o.t <= claim.window[1]):
            return GateResult(False, "R-A2", f"{o.oid} falls outside the window")

    # Minimality. NOTE: the original formulation ("no strict subset satisfies the
    # other conjuncts of A") is degenerate — Gate A's other conjuncts are all
    # per-observation predicates, so every proper subset satisfies them and
    # nothing is ever minimal. Replaced with: a citation is load-bearing if
    # removing it either shrinks coverage(c) or breaks the domain requirement.
    #
    # This catches genuine REDUNDANCY. It does not, by itself, catch adversarial
    # padding — a citation that widens coverage is load-bearing by construction.
    # The defence against padding is the asset/reachability conjunct above, which
    # requires every citation to concern the claim's subject. Citation cardinality
    # is reported as a diagnostic alongside.
    if len(claim.cites) > 1:
        full_cov = claim.coverage
        for drop in claim.cites:
            rest = tuple(o for o in claim.cites if o is not drop)
            rest_domains = frozenset(o.source.domain for o in rest)
            rest_cov: set[str] = set()
            for o in rest:
                rest_cov |= set(o.source.kappa)
            contributes_coverage = frozenset(rest_cov) != full_cov
            contributes_domain = not _domains_ok(claim.ctype, rest_domains)
            if not (contributes_coverage or contributes_domain):
                return GateResult(False, "R-A3",
                                  f"{drop.oid} contributes nothing (redundant citation)")

    return GateResult(True)


# --------------------------------------------------------------------------- #
#  Gate B — domain sufficiency
# --------------------------------------------------------------------------- #

def _domains_ok(ctype: ClaimType, have: frozenset[Domain]) -> bool:
    return any(req <= have for req in RHO[ctype])


def gate_b(claim: Claim) -> GateResult:
    """OR over admissible domain-sets, AND within each set."""
    if _domains_ok(claim.ctype, claim.domains):
        return GateResult(True)
    needed = min(RHO[claim.ctype], key=lambda r: len(r - claim.domains))
    missing = sorted(d.value for d in (needed - claim.domains))
    return GateResult(False, "R-B",
                      f"missing domain evidence: {', '.join(missing)}")
