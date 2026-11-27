"""Explicit adapter around existing GPU/simulator commands; never captures logs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from dreamlake_eval import Recorder, manifest, write_aggregate
from dreamlake_eval.model import atomic_write

parser = argparse.ArgumentParser()
parser.add_argument("--name", required=True)
parser.add_argument("--job-id", help="Stable unique job/machine/variant identity within the evaluation")
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--metrics", type=Path, help="Explicit existing [{step,values}] metrics file")
parser.add_argument("command", nargs=argparse.REMAINDER)
args = parser.parse_args()
command = args.command[1:] if args.command[:1] == ["--"] else args.command
if not command:
    parser.error("a workload command is required after --")
evaluation = os.environ.get("GITHUB_RUN_ID") or str(uuid.uuid4())
number = int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
job_id = args.job_id or args.name
suite = {"schemaVersion": "dreamlake.eval/v1", "kind": "suite", "suiteId": args.name,
         "collection": {"complete": True, "observations": []},
         "trials": [{"id": args.name, "nodeId": args.name, "caseId": args.name,
                     "selection": "selected", "context": {"adapter": "explicit-command"}}]}
plan = manifest(evaluation, {job_id: suite})
recorder = Recorder(suite, args.output / f"attempt-{number}", run_id=evaluation, job_id=job_id,
                    attempt_id=f"{job_id}-{number}", attempt_number=number)
atomic_write(args.output / "manifest.json", plan)
trial = recorder.trial(args.name)
trial.start()
started = time.monotonic()
code, execution, verdict = 2, "error", "inconclusive"
reason = "explicit_command_exit"
try:
    code = subprocess.run(command).returncode  # inherited streams, no capture/index
    execution = "completed" if code in (0, 1) else "interrupted" if code < 0 else "error"
    verdict = "passed" if code == 0 else "failed" if code == 1 else "inconclusive"
    if args.metrics and args.metrics.exists():
        points = json.loads(args.metrics.read_text())
        if not isinstance(points, list):
            raise ValueError("metrics must be a list of explicit sample points")
        for point in points:
            if not isinstance(point, dict) or not isinstance(point.get("values"), dict):
                raise ValueError("each sample must contain a values object")
            for name, value in point["values"].items():
                trial.metric(name, value, step=point.get("step"))
except KeyboardInterrupt:
    code, execution, verdict = 130, "interrupted", "inconclusive"
    reason = "interrupted"
except Exception:  # adapter failures must never retain a successful workload verdict
    code, execution, verdict = 2, "error", "inconclusive"
    reason = "adapter_error"
finally:
    trial.metric("workloadDurationSeconds", time.monotonic() - started)
    trial.complete(execution, verdict, reason=reason)
    recorder.finish(exit_code=code, interrupted=execution == "interrupted")
    names = list(recorder.snapshot()["trials"][0]["attempt"]["metrics"])
    write_aggregate(plan, [recorder.output / "eval.json"], args.output / "aggregate", metrics=names)
raise SystemExit(code if code >= 0 else 128 - code)
