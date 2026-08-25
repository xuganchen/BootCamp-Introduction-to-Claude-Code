"""Orchestrate the whole pipeline: stages 01-07, then the verification gate.

Exit codes
----------
0  every stage ran and, if `bdc_08_checks.py` exists, every check passed.
1  a stage raised, or a check failed.

The gate is imported lazily inside a try/except ImportError so the pipeline is
runnable before `bdc_08_checks.py` exists.  When the gate is missing the run
still exits 0, but it prints a loud warning: an unverified run is not a
verified run, and nothing is promoted to `output/` either way - promotion is
the gate's job, not this script's.

Usage
-----
    python3 code/run_all.py
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bdc_09_utils import log  # noqa: E402

STAGES = [
    ("01 resolve", "bdc_01_resolve"),
    ("02 fetch", "bdc_02_fetch"),
    ("03 extract", "bdc_03_extract"),
    ("04 parse SOI", "bdc_04_parse_soi"),
    ("05 parse balance sheet", "bdc_05_parse_bs"),
    ("06 normalize", "bdc_06_normalize"),
    ("07 panels", "bdc_07_panels"),
]


def run_stage(label: str, module_name: str, stage_argv: list[str] | None = None) -> bool:
    import importlib

    log.info("=" * 72)
    log.info("STAGE %s", label)
    started = time.monotonic()
    try:
        module = importlib.import_module(module_name)
        # Only stage 01 takes selection arguments; every other stage reads what
        # stage 01 wrote. Passing argv explicitly keeps this script's own flags
        # out of the stages' argparse (and out of the gate's).
        rc = module.main(stage_argv) if stage_argv is not None else module.main()
    except Exception:
        log.error("STAGE %s FAILED\n%s", label, traceback.format_exc())
        return False
    # Stages signal failure by raising or by returning a non-zero int.
    # Stages 01/02 return their result payload; anything non-int is success.
    if isinstance(rc, int) and rc != 0:
        log.error("STAGE %s returned %s", label, rc)
        return False
    log.info("STAGE %s ok (%.1fs)", label, time.monotonic() - started)
    return True


def run_gate() -> bool | None:
    """Run the verification gate if it exists.  None = gate not present."""
    try:
        import bdc_08_checks  # type: ignore
    except ImportError:
        log.warning("=" * 72)
        log.warning("bdc_08_checks.py not found: the run is UNVERIFIED and nothing "
                    "has been promoted to output/.")
        return None
    log.info("=" * 72)
    log.info("STAGE 08 verification gate")
    try:
        rc = bdc_08_checks.main([])  # explicit: the gate takes no flags from here
    except Exception:
        log.error("VERIFICATION GATE FAILED\n%s", traceback.format_exc())
        return False
    if isinstance(rc, int) and rc != 0:
        log.error("VERIFICATION GATE returned %s", rc)
        return False
    if rc is False:
        log.error("VERIFICATION GATE returned False")
        return False
    log.info("verification gate passed")
    return True


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Run stages 01-07 and the verification gate.")
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--period-end", default=None,
                    help="target period end as YYYY-MM-DD; default is the most recent filing")
    ap.add_argument("--form", default=None, choices=["10-Q", "10-K"])
    args = ap.parse_args()

    resolve_argv: list[str] = []
    if args.ticker:
        resolve_argv += ["--ticker", args.ticker]
    if args.period_end:
        resolve_argv += ["--period-end", args.period_end]
    if args.form:
        resolve_argv += ["--form", args.form]

    for label, module_name in STAGES:
        stage_argv = resolve_argv if module_name == "bdc_01_resolve" else None
        if not run_stage(label, module_name, stage_argv):
            return 1
    result = run_gate()
    if result is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
