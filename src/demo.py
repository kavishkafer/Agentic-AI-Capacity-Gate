"""Worked demonstration: the gate stack on one converged IT/OT incident.

    python src/demo.py

Scenario (Purdue levels in brackets):
    WS-14   [3]    engineering workstation
    JUMP-01 [3.5]  jump host in the OT DMZ
    PLC-07  [1]    controller governing a pressure-regulating valve

    03:02  attacker authenticates to WS-14 with stolen credentials
    03:07  RDP session WS-14 -> JUMP-01
    03:14  Modbus function-16 write to PLC-07, altering valve control logic

Instrumentation is deliberately partial — the site has network monitoring with
packet inspection and a historian, but no controller-side logging, and its
management-of-change records are incomplete. That is the common case, and it is
what makes the gates do work.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attack
import gate
from claims import (RHO, Claim, ClaimType, Domain, Observation, Source,
                    gate_a, gate_b)
from gate import Outcome

# --------------------------------------------------------------------------- #
#  the site: sources and their capabilities
# --------------------------------------------------------------------------- #

WINLOG = Source("winlog@WS-14", Domain.IT, frozenset({
    "Process Creation", "Process Termination", "Command Execution",
    "Logon Session Creation", "Logon Session Metadata",
    "User Account Authentication", "File Access", "Script Execution",
}), note="Windows endpoint logging on the engineering workstation")

FIREWALL = Source("fw@DMZ", Domain.IT, frozenset({
    "Network Traffic Flow", "Network Connection Creation",
}), note="flow records at the IT/OT boundary")

MODBUS = Source("modbus-dpi@DMZ", Domain.OT, frozenset({
    "Network Traffic Content", "Network Traffic Flow",
}), note="packet capture with industrial protocol dissection")

HISTORIAN = Source("historian", Domain.OT, frozenset({
    "Process History/Live Data", "Device Alarm", "Process/Event Alarm",
    "Asset Inventory",
}), note="process values and device alarms")

MOC = Source("moc-records", Domain.ET, frozenset(), deployed=True,
             note="management-of-change records. NOTE: contributes to domains(c) "
                  "but nothing to coverage(c) — ATT&CK has no data component for "
                  "change authorisation")

# controller-side logging exists as a source type but is NOT deployed here
PLCLOG = Source("plclog@PLC-07", Domain.OT, frozenset({
    "Application Log Content", "Firmware Modification",
}), deployed=False, note="controller logic/firmware visibility — not installed")

SOURCES = [WINLOG, FIREWALL, MODBUS, HISTORIAN, MOC, PLCLOG]

# --------------------------------------------------------------------------- #
#  what was actually observed
# --------------------------------------------------------------------------- #

OBS = [
    Observation("prov-1001", WINLOG,    "WS-14",   182, "logon, user j.okafor"),
    Observation("prov-1002", WINLOG,    "WS-14",   184, "powershell.exe spawned"),
    Observation("prov-1003", FIREWALL,  "JUMP-01", 187, "RDP flow WS-14 -> JUMP-01"),
    Observation("prov-1004", MODBUS,    "PLC-07",  194, "Modbus fn-16 write, src 10.20.3.5"),
    Observation("prov-1005", HISTORIAN, "PLC-07",  196, "valve position 62% (bound 0-60%)"),
]
KNOWN = {o.oid for o in OBS}
REACHABLE = {"PLC-07": {"JUMP-01", "PLC-07"}, "JUMP-01": {"WS-14", "JUMP-01"},
             "WS-14": {"WS-14"}}
WINDOW = (120, 240)

O = {o.oid: o for o in OBS}

# --------------------------------------------------------------------------- #
#  claims the agent proposes
# --------------------------------------------------------------------------- #

CLAIMS = [
    Claim("c1", ClaimType.ACTOR, "WS-14", WINDOW, (O["prov-1001"],),
          "user j.okafor authenticated to WS-14"),

    Claim("c2", ClaimType.JOIN, "PLC-07", WINDOW,
          (O["prov-1003"], O["prov-1004"]),
          "the RDP session and the Modbus write are the same actor"),

    Claim("c3", ClaimType.IMPACT, "PLC-07", WINDOW, (O["prov-1005"],),
          "valve driven outside its engineering bounds"),

    Claim("c4", ClaimType.MALICIOUS_CHANGE, "PLC-07", WINDOW,
          (O["prov-1004"],),
          "the valve logic was maliciously and without authorisation changed"),

    Claim("c5", ClaimType.TECHNIQUE, "PLC-07", WINDOW,
          (O["prov-1004"], O["prov-1005"]),
          "a Program Download was performed on PLC-07", technique="T0843"),

    Claim("c6", ClaimType.TECHNIQUE, "PLC-07", WINDOW,
          (O["prov-1005"],),
          "this constituted a Loss of Safety", technique="T0880"),

    Claim("c7", ClaimType.ACTOR, "WS-14", WINDOW,
          (O["prov-1001"], O["prov-1005"]),
          "user j.okafor acted (padded with an unrelated OT observation)"),
]


def main() -> None:
    ics = attack.load("ics")

    print("=" * 74)
    print("SITE INSTRUMENTATION")
    print("=" * 74)
    for s in SOURCES:
        mark = " " if s.deployed else "x"
        print(f"  [{mark}] {s.sid:<18} {s.domain.value:<3} "
              f"{len(s.kappa):>2} components   {s.note[:38]}")
    deployed_cov = gate.coverage_from_kappa(s.kappa for s in SOURCES if s.deployed)
    print(f"\n  coverage(site) = {len(deployed_cov)} data components")

    print()
    print("=" * 74)
    print("CLAIMS THROUGH THE GATE STACK")
    print("=" * 74)

    for c in CLAIMS:
        print(f"\n{c.cid}  [{c.ctype.value}]  {c.text}")
        print(f"     cites {[o.oid for o in c.cites]}   "
              f"domains {sorted(d.value for d in c.domains)}")

        a = gate_a(c, KNOWN, REACHABLE)
        if not a.passed:
            print(f"     Gate A  REJECT [{a.code}]  {a.reason}")
            continue
        print("     Gate A  pass")

        b = gate_b(c)
        if not b.passed:
            print(f"     Gate B  REJECT [{b.code}]  {b.reason}")
            continue
        print("     Gate B  pass")

        if c.ctype is not ClaimType.TECHNIQUE:
            print("     Gate C  n/a (not a technique claim)")
            continue

        t = ics.techniques[c.technique]
        v = gate.capacity(t, c.coverage)
        if v.outcome is Outcome.PASS:
            print(f"     Gate C  pass  ({c.technique} {t.name})")
        elif v.outcome is Outcome.UNDEFINED:
            print(f"     Gate C  UNDEFINED  ({c.technique} {t.name})")
            print(f"             {v.rejection_reason}")
        else:
            print(f"     Gate C  REJECT [R-C]  ({c.technique} {t.name})")
            print(f"             requires {sorted(t.analytics[0].data_components)}")
            print(f"             coverage {sorted(c.coverage)}")
            print(f"             MISSING  {sorted(v.missing)}")
            print(f"             -> instrument {sorted(v.missing)} to make this provable")


if __name__ == "__main__":
    main()
