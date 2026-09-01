"""Tests for the evidential capacity gate.

Run:  python -m pytest tests -q        (or)   python tests/test_gate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import attack  # noqa: E402
import gate  # noqa: E402
import profiles  # noqa: E402
from gate import Outcome  # noqa: E402

ICS = attack.load("ics")
ENT = attack.load("ent")


# --------------------------------------------------------------------------- #
#  the formula
# --------------------------------------------------------------------------- #

def test_conjunction_all_required_components_needed():
    """T0843 needs 4 components; 3 of 4 must fail (ICS has no alternative route)."""
    t = ICS.techniques["T0843"]
    required = t.analytics[0].data_components
    assert len(required) == 4

    assert gate.capacity(t, required).outcome is Outcome.PASS
    for drop in required:
        partial = required - {drop}
        v = gate.capacity(t, partial)
        assert v.outcome is Outcome.FAIL, f"dropping {drop} should fail"
        assert v.missing == frozenset({drop})


def test_disjunction_any_satisfied_route_passes():
    """Enterprise techniques with >1 analytic pass if ANY route is fully covered."""
    multi = [t for t in ENT.techniques.values() if len(t.analytics) > 1]
    assert multi, "expected Enterprise techniques with multiple analytics"
    t = multi[0]
    one_route = min(t.analytics, key=lambda a: len(a.data_components))
    assert gate.capacity(t, one_route.data_components).outcome is Outcome.PASS


def test_superset_coverage_still_passes():
    """Extra coverage never breaks a passing claim (monotonicity)."""
    t = ICS.techniques["T0843"]
    assert gate.capacity(t, ICS.all_data_component_names).outcome is Outcome.PASS


def test_zero_coverage_evidences_nothing():
    """No instrumentation -> nothing PASSes. Guards the empty-set subset trap."""
    v = gate.evaluate_corpus(ICS, frozenset())
    assert sum(x.outcome is Outcome.PASS for x in v.values()) == 0


# --------------------------------------------------------------------------- #
#  the third verdict
# --------------------------------------------------------------------------- #

def test_empty_requirement_is_undefined_not_pass():
    """T0880 Loss of Safety declares no data components -> UNDEFINED, never PASS."""
    t = ICS.techniques["T0880"]
    assert t.analytics and not t.analytics[0].data_components
    for cov in (frozenset(), ICS.all_data_component_names):
        v = gate.capacity(t, cov)
        assert v.outcome is Outcome.UNDEFINED
        assert v.evidenceable is False


def test_entire_impact_tactic_is_undefined():
    """All 12 ICS Impact-tactic techniques lack a usable analytic."""
    impact = ["T0813", "T0815", "T0826", "T0827", "T0828", "T0829",
              "T0831", "T0832", "T0837", "T0879", "T0880", "T0882"]
    full = ICS.all_data_component_names
    for tid in impact:
        assert gate.capacity(ICS.techniques[tid], full).outcome is Outcome.UNDEFINED


# --------------------------------------------------------------------------- #
#  corpus-level invariants
# --------------------------------------------------------------------------- #

def test_full_coverage_evidences_every_checkable_technique():
    """With everything deployed, every technique that CAN be checked passes."""
    for corpus in (ICS, ENT):
        v = gate.evaluate_corpus(corpus, corpus.all_data_component_names)
        checkable = [x for x in v.values() if x.outcome is not Outcome.UNDEFINED]
        assert all(x.outcome is Outcome.PASS for x in checkable)


def test_coverage_is_monotone_across_profile_tiers():
    """Adding instrumentation never reduces the number of evidenceable techniques."""
    counts = []
    for _key, _label, cov in profiles.cumulative():
        v = gate.evaluate_corpus(ICS, cov)
        counts.append(sum(x.outcome is Outcome.PASS for x in v.values()))
    assert counts == sorted(counts), f"non-monotone: {counts}"


def test_ics_has_no_alternative_routes():
    """Structural claim in the paper: every ICS technique has exactly one analytic."""
    assert {len(t.analytics) for t in ICS.techniques.values()} == {1}


def test_coverage_from_kappa_unions_sources():
    k1 = frozenset({"Network Traffic Flow"})
    k2 = frozenset({"Network Traffic Content", "Device Alarm"})
    assert gate.coverage_from_kappa([k1, k2]) == frozenset(
        {"Network Traffic Flow", "Network Traffic Content", "Device Alarm"}
    )


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except AssertionError as e:
                print(f"  FAIL  {name}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
