"""
The evidential capacity gate (Gate C).

    C(c) = OR  over DET in Strategies(T)
           OR  over AN  in Analytics(DET)
           AND over dc  in DataComponents(AN) :  dc in coverage(c)

Read: technique T is evidenceable from the cited sources iff at least one of
ATT&CK's own detection analytics has ALL of its required data components covered.

Nothing in this module is authored by us. The requirement side comes entirely
from the published ATT&CK bundle; the only input we supply is `coverage` — the
set of data components actually available, which is the declared instrumentation
model (see profiles.py).

The same function serves two purposes:
  * runtime gate      — coverage derived from a claim's cited observations
  * measurement study — coverage set to a hypothetical instrumentation profile
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from attack import Analytic, Corpus, Technique


class Outcome(Enum):
    """Three outcomes, not two.

    PASS / FAIL are claims about the evidence. UNDEFINED is a claim about the
    ontology: ATT&CK specifies no data components for this technique, so no
    capacity check is possible at all. Collapsing UNDEFINED into PASS (which a
    naive subset test does, since the empty set is a subset of everything) lets
    the least-evidenced claims through silently.
    """

    PASS = "pass"
    FAIL = "fail"
    UNDEFINED = "undefined"


@dataclass(frozen=True)
class Verdict:
    """The result of evaluating Gate C for one technique under one coverage set."""

    technique_id: str
    outcome: "Outcome"
    satisfied: tuple[Analytic, ...]          # routes that fully work
    closest: Analytic | None                 # route needing fewest additions
    missing: frozenset[str]                  # what `closest` still needs
    n_routes: int                            # how many analytics exist at all

    @property
    def evidenceable(self) -> bool:
        """True only for PASS. UNDEFINED is explicitly not evidenceable."""
        return self.outcome is Outcome.PASS

    @property
    def rejection_reason(self) -> str:
        if self.outcome is Outcome.PASS:
            return ""
        if self.outcome is Outcome.UNDEFINED:
            return ("no capacity check possible - ATT&CK defines no required "
                    "data components for this technique")
        if self.n_routes == 0:
            return "no analytic defined for this technique"
        return "missing data components: " + ", ".join(sorted(self.missing))


def capacity(technique: Technique, coverage: frozenset[str]) -> Verdict:
    """Evaluate Gate C. Decidable, terminating, and side-effect free."""
    analytics = technique.analytics

    # An analytic with no declared data components is trivially satisfied by the
    # subset test. That is a property of the ontology, not of the evidence, so it
    # is reported as UNDEFINED rather than silently passing.
    if analytics and all(not a.data_components for a in analytics):
        return Verdict(
            technique_id=technique.attack_id,
            outcome=Outcome.UNDEFINED,
            satisfied=(),
            closest=None,
            missing=frozenset(),
            n_routes=len(analytics),
        )

    satisfied = tuple(a for a in analytics if a.satisfied_by(coverage))

    closest: Analytic | None = None
    missing: frozenset[str] = frozenset()
    if not satisfied and analytics:
        # the route requiring the fewest additional data components
        closest = min(analytics, key=lambda a: len(a.missing_from(coverage)))
        missing = closest.missing_from(coverage)

    return Verdict(
        technique_id=technique.attack_id,
        outcome=Outcome.PASS if satisfied else Outcome.FAIL,
        satisfied=satisfied,
        closest=closest,
        missing=missing,
        n_routes=len(analytics),
    )


# --------------------------------------------------------------------------- #
#  sweeps over a whole corpus
# --------------------------------------------------------------------------- #

def evaluate_corpus(
    corpus: Corpus,
    coverage: frozenset[str],
    *,
    skip_empty_analytics: bool = False,
) -> dict[str, Verdict]:
    """Run the gate over every technique in a corpus.

    skip_empty_analytics: exclude techniques whose only analytic declares no data
    components at all. These are arguably incomplete records rather than genuinely
    unevidenceable techniques, so both readings are reported in the results.
    """
    out: dict[str, Verdict] = {}
    for tid, t in corpus.techniques.items():
        if skip_empty_analytics and t.analytics and all(
            not a.data_components for a in t.analytics
        ):
            continue
        out[tid] = capacity(t, coverage)
    return out


DENOMINATOR = "all"
"""Reporting denominator for every evidenceable fraction in the project.

  "all"       — all techniques in the corpus (97 for ICS). The operator-facing
                number: of everything in the threat model, this much is provable
                at your site. UNDEFINED techniques count against you, which is
                honest, provided the paper says why they can never be recovered.
  "checkable" — techniques the ontology states requirements for (85 for ICS).
                Isolates instrumentation adequacy from ontology silence.

Set to "all" (supervisor decision, 2 Sep 2026), with the 12 UNDEFINED
techniques reported explicitly alongside every headline figure. Consequence to
state plainly wherever a full-instrumentation figure appears: this ratio's
ceiling is 85/97 = 87.6%, not 100%, and no instrumentation spend closes the
remaining 12.4%.

Changing this changes REPORTING only. The gate is unaffected: an UNDEFINED
technique is never PASS under either setting, so no verdict, violation count,
or pre-registered prediction moves.
"""


def denominator(verdicts: dict[str, Verdict], which: str | None = None) -> int:
    """Size of the reporting denominator — see DENOMINATOR."""
    if (which or DENOMINATOR) == "all":
        return len(verdicts)
    return sum(v.outcome is not Outcome.UNDEFINED for v in verdicts.values())


def evidenceable_fraction(verdicts: dict[str, Verdict],
                          which: str | None = None) -> float:
    n = denominator(verdicts, which)
    if not n:
        return 0.0
    return sum(v.evidenceable for v in verdicts.values()) / n


# --------------------------------------------------------------------------- #
#  ontology-intrinsic analyses  (no authored input at all)
# --------------------------------------------------------------------------- #

def criticality(corpus: Corpus) -> list[tuple[str, int]]:
    """For each data component: how many techniques become unevidenceable if that
    single component is removed from an otherwise-complete instrumentation?

    Pure property of the published ontology — nothing authored.
    """
    full = corpus.all_data_component_names
    baseline = evaluate_corpus(corpus, full)
    n_base = sum(v.evidenceable for v in baseline.values())

    rows: list[tuple[str, int]] = []
    for dc in sorted(full):
        reduced = full - {dc}
        v = evaluate_corpus(corpus, reduced)
        lost = n_base - sum(x.evidenceable for x in v.values())
        rows.append((dc, lost))
    return sorted(rows, key=lambda r: -r[1])


def acquisition_order(corpus: Corpus, *, limit: int | None = None
                      ) -> list[tuple[str, int, int]]:
    """Greedy acquisition curve: which data component to instrument next, and
    what each one buys.

    Returns [(data_component, cumulative_PASS, marginal_gain), ...] in the order
    a site should acquire them to make the most techniques evidenceable soonest.

    Only techniques that CAN be checked count — UNDEFINED techniques are excluded,
    since no amount of instrumentation makes them evidenceable.

    Greedy is not guaranteed optimal for set cover, but the ordering is the point:
    it answers "what should we instrument first?" rather than "what is the minimum
    set?", and the first is the operationally useful question.
    """
    checkable = {
        tid: t for tid, t in corpus.techniques.items()
        if t.analytics and any(a.data_components for a in t.analytics)
    }

    def n_pass(cov: frozenset[str]) -> int:
        return sum(capacity(t, cov).outcome is Outcome.PASS for t in checkable.values())

    chosen: set[str] = set()
    remaining = set(corpus.all_data_component_names)
    prev = 0
    rows: list[tuple[str, int, int]] = []

    while remaining and (limit is None or len(rows) < limit):
        best, best_n = None, -1
        for dc in sorted(remaining):
            n = n_pass(frozenset(chosen | {dc}))
            if n > best_n:
                best, best_n = dc, n
        if best is None or best_n <= prev:
            break                      # no further progress possible
        chosen.add(best)
        remaining.discard(best)
        rows.append((best, best_n, best_n - prev))
        prev = best_n
        if best_n == len(checkable):
            break                      # everything checkable is now evidenceable
    return rows


def coverage_from_kappa(kappas: Iterable[frozenset[str]]) -> frozenset[str]:
    """coverage(c) = union of kappa(source(o)) over cited observations."""
    out: set[str] = set()
    for k in kappas:
        out |= set(k)
    return frozenset(out)
