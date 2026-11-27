"""CPU-only command adapter acceptance; no simulator or GPU invocation."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

WRAPPER = Path(__file__).with_name("run_workload.py")


@pytest.mark.parametrize("metrics", [None, {}, [{"values": None}], [{"values": []}], [None], [{"values": {"score": "invalid"}}]])
def test_invalid_metrics_cannot_retain_pass(tmp_path, monkeypatch, metrics):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    source = tmp_path / "metrics.json"
    source.write_text(json.dumps(metrics))
    output = tmp_path / "output"
    result = subprocess.run([sys.executable, str(WRAPPER), "--name", "cpu", "--job-id", "cpu:variant",
                             "--output", str(output), "--metrics", str(source), "--",
                             sys.executable, "-c", "pass"])
    assert result.returncode == 2
    report = json.loads((output / "attempt-1/eval.json").read_text())
    assert report["jobId"] == "cpu:variant"
    attempt = report["trials"][0]["attempt"]
    assert attempt["execution"] == "error" and attempt["verdict"] == "inconclusive"


@pytest.mark.parametrize("code,state,verdict", [(0, "completed", "passed"), (1, "completed", "failed"), (2, "error", "inconclusive")])
def test_preserves_command_outcomes_and_retry_identity(tmp_path, monkeypatch, code, state, verdict):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    output = tmp_path / "output"
    result = subprocess.run([sys.executable, str(WRAPPER), "--name", "cpu", "--job-id", "cpu:variant",
                             "--output", str(output), "--", sys.executable, "-c", f"raise SystemExit({code})"])
    assert result.returncode == code
    report = json.loads((output / "attempt-2/eval.json").read_text())
    assert report["attemptNumber"] == 2 and report["attemptId"] == "cpu:variant-2"
    attempt = report["trials"][0]["attempt"]
    assert attempt["execution"] == state and attempt["verdict"] == verdict
