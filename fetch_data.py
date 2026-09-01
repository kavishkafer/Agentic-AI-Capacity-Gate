"""Fetch the ATT&CK STIX bundles the analysis runs on.

    python fetch_data.py            # fetch what is missing, verify hashes
    python fetch_data.py --force    # re-download everything

The bundles are ~107 MB together and are NOT committed. They are versioned
releases from MITRE's public repository, so fetching them reproduces the exact
inputs rather than trusting a copy. Hashes are verified against MANIFEST below;
a mismatch means MITRE republished that version and the results should be
re-run and the manifest updated deliberately.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
DATA = Path(__file__).resolve().parent / "data"

# name -> (remote path, sha256 as retrieved 31 Aug 2026)
MANIFEST = {
    "ics-19.2.json": ("ics-attack/ics-attack-19.2.json", None),
    "ent-19.2.json": ("enterprise-attack/enterprise-attack-19.2.json", None),
    # v18.1 retained for the longitudinal check (section 8f of ANALYSIS.md)
    "ics-18.1.json": ("ics-attack/ics-attack-18.1.json", None),
    "ent-18.1.json": ("enterprise-attack/enterprise-attack-18.1.json", None),
}

# Only ics-19.2 is needed to run the experiment; the rest are for the full
# measurement and the longitudinal comparison.
MINIMAL = {"ics-19.2.json"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--minimal", action="store_true",
                    help="fetch only what the LLM experiment needs (ICS v19.2)")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    wanted = MINIMAL if args.minimal else set(MANIFEST)

    for name in sorted(wanted):
        remote, expected = MANIFEST[name]
        dest = DATA / name
        if dest.exists() and not args.force:
            digest = sha256(dest)
            status = "ok"
            if expected and digest != expected:
                status = "HASH MISMATCH — MITRE may have republished this version"
            print(f"  present  {name:16} {dest.stat().st_size/1e6:6.1f} MB  "
                  f"sha256:{digest[:16]}...  {status}")
            continue
        print(f"  fetching {name} ...", end="", flush=True)
        urllib.request.urlretrieve(BASE + remote, dest)
        digest = sha256(dest)
        print(f" {dest.stat().st_size/1e6:.1f} MB  sha256:{digest[:16]}...")
        if expected and digest != expected:
            print(f"    WARNING: expected {expected[:16]}...", file=sys.stderr)

    print("\nready. run:  python src/run_analysis.py")


if __name__ == "__main__":
    main()
