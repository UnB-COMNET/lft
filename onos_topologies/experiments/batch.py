"""Repeat existing runners without copying their orchestration logic"""

import sys
from pathlib import Path
import argparse
import time
import traceback

# Resolve checkout imports when executed directly
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "onos_topologies.experiments"

from .registry import load, mode_key


def run_batch(
    experiment,
    modes,
    seeds,
    auto_start=True,
    settle_s=15,
    hindering="degrade",
    continue_on_error=True,
):
    if experiment not in {"rnp", "diamond"}:
        raise ValueError("Batch supports rnp and diamond")
    # Validate the complete plan before creating any containers.
    keys = [mode_key(experiment, mode) for mode in modes]
    seeds = tuple(seeds)
    if not keys or not seeds or settle_s < 0:
        raise ValueError("Provide modes, seeds and a non-negative settle time")
    if hindering not in {"degrade", "take down"}:
        raise ValueError("hindering must be 'degrade' or 'take down'")
    if experiment == "rnp" and hindering != "degrade":
        raise ValueError("RNP supports degradation only")
    runner = load(experiment)
    failures = []
    for key in keys:
        for seed in seeds:
            mode = runner.MODES[key]["name"]
            suffix = f"seed{seed}" if experiment == "rnp" else f"{seed:02d}"
            run_name = f"{mode}-{hindering}-{suffix}"
            kwargs = dict(algorithm=key, auto_start=auto_start, run_name=run_name)
            if experiment == "rnp":
                kwargs["seed"] = seed
            else:
                kwargs["hindering"] = hindering
            print(f"\n [BATCH] {run_name}\n")
            try:
                runner.main(**kwargs)
            except Exception:
                if not continue_on_error:
                    raise
                failures.append(run_name)
                traceback.print_exc()
            time.sleep(settle_s)
    print(f" [BATCH] Done: {len(keys) * len(seeds)} runs, {len(failures)} failed.")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=("rnp", "diamond"))
    parser.add_argument("--modes", nargs="+", required=True)
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=list(range(1, 11)),
        help="RNP seeds; repetition numbers for diamond",
    )
    parser.add_argument("--settle", type=float, default=15)
    parser.add_argument("--manual-services", action="store_true")
    parser.add_argument(
        "--hindering", choices=("degrade", "take down"), default="degrade"
    )
    args = parser.parse_args()
    try:
        failures = run_batch(
            args.experiment,
            args.modes,
            args.seeds,
            auto_start=not args.manual_services,
            settle_s=args.settle,
            hindering=args.hindering,
        )
    except ValueError as error:
        parser.error(str(error))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
