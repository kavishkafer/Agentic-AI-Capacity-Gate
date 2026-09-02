"""Profile sweep driver — the same items and models across all five profiles.

    python experiments/profile_sweep/run_sweep.py \
        --backend openai --host http://localhost:8000 \
        --model "<exact-id>" --name deepseek

Runs the `instrumented` condition at p1..p5 for one model, writing
out/experiment_sweep_<name>_<profile>.csv per tier. Resumable: an existing
output file for a profile is skipped, so an interrupted sweep can be restarted
without redoing completed tiers.

Run one model at a time if vLLM serves one model per process.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "out"
PROFILES = ["p1_flow", "p2_dpi", "p3_historian", "p4_host", "p5_controller"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="openai")
    ap.add_argument("--host", default="http://localhost:8000")
    ap.add_argument("--model", required=True, help="exact id from --list-models")
    ap.add_argument("--name", required=True, help="short label: deepseek|gemma|qwen")
    ap.add_argument("--limit", type=int, default=0, help="0 = all 271 items")
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--profiles", default=",".join(PROFILES))
    ap.add_argument("--force", action="store_true", help="redo completed profiles")
    args = ap.parse_args()

    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    OUT.mkdir(exist_ok=True)

    print(f"model : {args.model}")
    print(f"name  : {args.name}")
    print(f"tiers : {', '.join(profiles)}")
    print(f"note  : instrumented condition only — bare is profile-independent\n")

    t_all = time.time()
    for i, prof in enumerate(profiles, 1):
        tag = f"sweep_{args.name}_{prof}"
        dest = OUT / f"experiment_{tag}.csv"
        if dest.exists() and not args.force:
            print(f"[{i}/{len(profiles)}] {prof:<15} already done — skipping")
            continue

        print(f"[{i}/{len(profiles)}] {prof:<15} running ...", flush=True)
        t0 = time.time()
        cmd = [
            sys.executable, str(ROOT / "src" / "experiment.py"),
            "--backend", args.backend,
            "--host", args.host,
            "--model", args.model,
            "--profile", prof,
            "--conditions", "instrumented",
            "--tag", tag,
            "--max-tokens", str(args.max_tokens),
        ]
        if args.limit:
            cmd += ["--limit", str(args.limit)]

        r = subprocess.run(cmd, cwd=ROOT)
        if r.returncode != 0:
            print(f"    FAILED (exit {r.returncode}) — stopping so the "
                  f"partial sweep is not silently analysed")
            sys.exit(r.returncode)
        print(f"    done in {(time.time()-t0)/60:.1f} min")

    print(f"\nsweep complete for {args.name} in {(time.time()-t_all)/60:.1f} min")
    print("next: python experiments/profile_sweep/analyse_sweep.py")


if __name__ == "__main__":
    main()
