"""``python -m native_e2e run|verify`` (CAP-0174 contract §3).

``run --commit <sha> --out <dir>`` runs the rows in spec §2.3 order from the checkout in the
current folder, writes the receipt and ``SHA256SUMS`` and runs the scan; exit 0 only when
every Phase 1 row is ``pass`` or ``pending`` and the scan is clean (1: a row is not; 2: the
scan found a pattern; 3: bad arguments). The workflow passes its optional inputs as
``--capability``, ``--work-item`` and ``--plant-redaction-canary``.

``verify <dir>`` checks a run's or a downloaded artifact: schema, sums and redaction
re-scan; exit 0 iff all pass. With ``GITHUB_STEP_SUMMARY`` set both append to the job summary.
Windows only for ``run`` (the rows drive the VM); ``verify`` is portable.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from native_e2e import publish, runner
from native_e2e.context import RunContext

USAGE_ERROR = 3


def _summary() -> Path | None:
    value = os.environ.get("GITHUB_STEP_SUMMARY")
    return Path(value) if value else None


def _workflow_run() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        return "local"
    return f"{run_id}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m native_e2e", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the native rows and write the artifact folder")
    run.add_argument("--commit", required=True)
    run.add_argument("--out", required=True, type=Path)
    run.add_argument("--capability")
    run.add_argument("--work-item")
    run.add_argument("--plant-redaction-canary", action="store_true")
    verify = commands.add_parser("verify", help="check an artifact folder before upload")
    verify.add_argument("folder", type=Path)
    return parser


def _run(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        print("run: --commit must be 40 lower-case hex digits", file=sys.stderr)
        return USAGE_ERROR
    out = args.out.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print("run: --out must be a new or empty folder", file=sys.stderr)
        return USAGE_ERROR
    ctx = RunContext(
        commit=args.commit, out=out, repo=Path.cwd().resolve(), workflow_run=_workflow_run()
    )
    try:
        runner.prepare(ctx)
        rows = runner.execute(ctx)
    except Exception as error:  # noqa: BLE001 - the receipt still records what ran
        print(f"run: unexpected {type(error).__name__}", file=sys.stderr)
        rows = {}
    return publish.finalize(
        ctx,
        rows,
        capability=args.capability,
        work_item=args.work_item,
        plant_canary=args.plant_redaction_canary,
        summary=_summary(),
    )


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    if args.command == "run":
        return _run(args)
    return publish.verify(args.folder.resolve(), _summary())


if __name__ == "__main__":
    raise SystemExit(main())
