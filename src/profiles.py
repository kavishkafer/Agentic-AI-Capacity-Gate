"""
Instrumentation profiles — THE AUTHORED PART.

Everything in gate.py and attack.py is derived from the published ATT&CK bundle.
This file is different: it declares what a given ICS deployment can actually
observe. It is the `kappa(s)` side of the architecture, and it is the only place
where our own judgement enters the capacity computation.

Profiles are cumulative tiers, ordered by how commonly they are found in the
field. Each names the data components that tier makes available. They are stated
explicitly, and swept, precisely so that a reader can disagree with one and
recompute.

Rationale for the ordering: passive network monitoring is the most common
minimal OT deployment; deep packet inspection is a distinct and often absent
capability; historian access is usually available for process engineering
reasons rather than security ones; host logging on engineering workstations and
HMIs is common where those hosts are Windows-managed; controller-side logging is
rare and is frequently the missing tier in real facilities.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    adds: frozenset[str]      # data components this tier contributes
    note: str = ""


# --- tiers ---------------------------------------------------------------- #

T1_NETWORK_FLOW = Profile(
    key="p1_flow",
    label="Network flow only",
    adds=frozenset({
        "Network Traffic Flow",
        "Network Connection Creation",
    }),
    note="passive tap, NetFlow-level metadata; no payload inspection",
)

T2_DPI = Profile(
    key="p2_dpi",
    label="+ deep packet inspection",
    adds=frozenset({
        "Network Traffic Content",
    }),
    note="full packet capture with industrial protocol dissection",
)

T3_HISTORIAN = Profile(
    key="p3_historian",
    label="+ historian / process data",
    adds=frozenset({
        "Process History/Live Data",
        "Device Alarm",
        "Process/Event Alarm",
        "Asset Inventory",
    }),
    note="process values and alarms, usually already collected for engineering",
)

T4_HOST = Profile(
    key="p4_host",
    label="+ host logging (EWS / HMI)",
    adds=frozenset({
        "Process Creation",
        "Process Termination",
        "Process Metadata",
        "Command Execution",
        "Script Execution",
        "OS API Execution",
        "Module Load",
        "File Access",
        "File Creation",
        "File Deletion",
        "File Modification",
        "File Metadata",
        "Logon Session Creation",
        "Logon Session Metadata",
        "User Account Authentication",
        "Service Creation",
        "Service Metadata",
        "Service Modification",
        "Scheduled Job Creation",
        "Scheduled Job Metadata",
        "Scheduled Job Modification",
        "Windows Registry Key Modification",
        "Windows Registry Key Deletion",
        "Network Share Access",
        "Drive Creation",
        "Drive Modification",
        "Software",
    }),
    note="Windows-class endpoint telemetry on engineering workstations and HMIs",
)

T5_CONTROLLER = Profile(
    key="p5_controller",
    label="+ controller-side logging",
    adds=frozenset({
        "Firmware Modification",
        "Application Log Content",
    }),
    note="PLC/controller logic and firmware visibility; rare in practice",
)

TIERS = (T1_NETWORK_FLOW, T2_DPI, T3_HISTORIAN, T4_HOST, T5_CONTROLLER)


# --- variants -------------------------------------------------------------- #
#
# Not a further tier. A variant is an existing tier with a stated component
# removed, used to test whether a result depends on one component.

CATCH_ALL = "Application Log Content"
"""ATT&CK's generic application-log component.

It appears in 41 ICS analytics but is the *sole* requirement of only 2. In the
other 39 it is the last missing piece of an analytic whose other requirements
are already met, so adding it completes them all at once: it alone carries
p5_controller from 51.8% to 100% of checkable techniques.

Whether it belongs in the controller tier is our judgement, not MITRE's. A PLC
does emit application logs, so its placement is defensible — but the ATT&CK
component is far broader than that reading, and the top tier's headline number
should not rest on it unexamined. Hence p5b.
"""


def _variants() -> dict[str, tuple[str, frozenset[str]]]:
    base = {k: cov for k, _, cov in cumulative()}
    return {
        "p5b_controller_strict": (
            "+ controller-side logging, catch-all excluded",
            base["p5_controller"] - {CATCH_ALL},
        ),
    }


def cumulative() -> list[tuple[str, str, frozenset[str]]]:
    """Cumulative coverage sets: (key, label, coverage) for each tier in order."""
    acc: set[str] = set()
    out = []
    for t in TIERS:
        acc |= set(t.adds)
        out.append((t.key, t.label, frozenset(acc)))
    return out


def named(key: str) -> frozenset[str]:
    for k, _, cov in cumulative():
        if k == key:
            return cov
    v = _variants()
    if key in v:
        return v[key][1]
    raise KeyError(key)


def label(key: str) -> str:
    for k, lbl, _ in cumulative():
        if k == key:
            return lbl
    v = _variants()
    if key in v:
        return v[key][0]
    raise KeyError(key)


def all_keys() -> list[str]:
    """Cumulative tiers in order, then variants."""
    return [k for k, _, _ in cumulative()] + list(_variants())
