"""Export the instrumentation profiles as DeTT&CT data-source administration YAML.

    python src/export_dettect.py

Why this exists
---------------
`profiles.py` is the only authored input in the whole analysis, and it is
therefore the paper's largest assumption. Expressing it in DeTT&CT's established
data-source administration format does three things:

  1. it stops the profiles being an ad-hoc invention of ours, and makes them an
     instance of a schema practitioners already maintain for their own estates;
  2. it lets a reviewer or an operator diff our assumed instrumentation against
     their real one, rather than taking it on trust;
  3. it makes the assumption falsifiable — anyone can substitute their own
     administration file and re-run the whole analysis.

DeTT&CT is a Rabobank CDC tool for scoring log-source visibility and detection
coverage against ATT&CK. It has no peer-reviewed write-up, so it is cited as
practitioner practice rather than as literature.

Note on the mapping: DeTT&CT administers *data sources*; ATT&CK v18+ moved the
actionable unit to *data components*. We emit one entry per data component, which
is the finer granularity, and set `applicable_to` to the ICS platform.

Quality scores here are deliberately uniform placeholders (see QUALITY below) —
the capacity gate is a binary availability test and does not consume them. They
are emitted so the files are schema-valid and so a real deployment can drop in
its own scores without changing shape.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import profiles

OUT = Path(__file__).resolve().parent.parent / "out" / "dettect"
OUT.mkdir(parents=True, exist_ok=True)

TODAY = date.today().isoformat()

# What supplies each tier in practice — used for the `products` field so a reader
# can see what hardware/software the assumption implies.
PRODUCTS = {
    "p1_flow": ["Network flow collector (NetFlow/IPFIX)", "OT network tap"],
    "p2_dpi": ["Industrial protocol DPI sensor"],
    "p3_historian": ["Process historian", "SCADA alarm server"],
    "p4_host": ["Windows Event Log", "EDR agent on EWS/HMI"],
    "p5_controller": ["Controller/PLC diagnostic log", "Engineering software audit log"],
}

# Placeholder quality: the gate is a binary availability test, so these are not
# consumed. Emitted for schema validity and for a real deployment to overwrite.
QUALITY = {
    "device_completeness": 3,
    "data_field_completeness": 3,
    "timeliness": 3,
    "consistency": 3,
    "retention": 3,
}


def _yaml_list(items: list[str], indent: int) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}- {i}" for i in items)


def emit(profile_key: str, label: str, coverage: frozenset[str],
         tier_products: dict[str, list[str]]) -> str:
    lines = [
        "version: 1.1",
        "file_type: data-source-administration",
        f"name: capacity-gate {profile_key} — {label}",
        "domain: ics-attack",
        "systems:",
        "  - applicable_to:",
        "      - ICS",
        "    platform:",
        "      - ICS",
        "data_sources:",
    ]
    for dc in sorted(coverage):
        prods = tier_products.get(dc, ["unspecified"])
        lines += [
            f"  - data_source_name: {dc}",
            "    data_source:",
            "      - applicable_to:",
            "          - ICS",
            f"        date_registered: '{TODAY}'",
            f"        date_connected: '{TODAY}'",
            "        products:",
            _yaml_list(prods, 10),
            "        available_for_data_analytics: true",
            "        comment: >-",
            f"          Assumed available under instrumentation profile "
            f"'{profile_key}' ({label}).",
            "        data_quality:",
        ]
        lines += [f"          {k}: {v}" for k, v in QUALITY.items()]

    lines += [
        "notes: >-",
        f"  Instrumentation profile '{profile_key}' from the capacity-gate analysis.",
        "  Cumulative tier: includes everything from the preceding tiers.",
        "  Quality scores are uniform placeholders — the capacity gate is a binary",
        "  availability test and does not consume them. Replace with real scores to",
        "  reuse this file for DeTT&CT visibility scoring.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    # which tier introduced each data component -> its products
    origin: dict[str, list[str]] = {}
    for tier in profiles.TIERS:
        for dc in tier.adds:
            origin.setdefault(dc, PRODUCTS.get(tier.key, ["unspecified"]))

    for key, label, cov in profiles.cumulative():
        path = OUT / f"{key}.yaml"
        path.write_text(emit(key, label, cov, origin), encoding="utf-8")
        print(f"  wrote out/dettect/{path.name}  ({len(cov)} data components)")

    readme = OUT / "README.md"
    readme.write_text(
        "# Instrumentation profiles as DeTT&CT administration files\n\n"
        "Generated by `src/export_dettect.py`. One file per cumulative tier.\n\n"
        "These express the only authored assumption in the analysis — what a given\n"
        "ICS deployment can observe — in the DeTT&CT data-source administration\n"
        "format, so it can be diffed against a real estate rather than taken on\n"
        "trust. Substitute your own administration file and re-run `run_analysis.py`\n"
        "to recompute every result against your own instrumentation.\n\n"
        "DeTT&CT: https://github.com/rabobank-cdc/DeTTECT (Rabobank CDC; practitioner\n"
        "tool, no peer-reviewed write-up — cite as practice, not literature).\n\n"
        "Quality scores are uniform placeholders: the capacity gate is a binary\n"
        "availability test and does not consume them.\n",
        encoding="utf-8")
    print(f"  wrote out/dettect/README.md")


if __name__ == "__main__":
    main()
