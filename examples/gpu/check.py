"""GPU smoke test: is the GPU there, and does it do real work?

Writes summary.json and metrics.json to --out, and a sustained-load trace
DreamLake's viewer charts from the run's evidence (episodes/load/gpu.csv:
throughput, power, temperature and utilization over --load-seconds, laid out by
.dreamrc). Exits 0 when every check passed, 1 when a check failed, 2 when the
job could not run at all.
"""
import argparse
import json
import os
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument("--out", default="outputs")
parser.add_argument("--size", type=int, default=8192, help="matrix size for the matmul benchmark")
parser.add_argument("--load-seconds", type=float, default=10, help="seconds of sustained load to trace (0: none)")
args = parser.parse_args()
os.makedirs(args.out, exist_ok=True)

checks, metrics = [], {}

# DreamLake's viewer config for the run folder: the load trace as charts on one timeline.
DREAMRC = """version: 1
name: GPU under sustained fp16 matmul load
dataset:
  format: folder
  episodes: "episodes/*/"
  fps: 10
views:
  - view: timeline
  - view: lineChart
    title: fp16 matmul (TFLOPS)
    series:
      - { field: [gpu, tflops] }
  - view: lineChart
    title: Power (W)
    series:
      - { field: [gpu, power_w] }
  - view: lineChart
    title: Temperature (C) and utilization (%)
    series:
      - { field: [gpu, temperature_c], label: temperature }
      - { field: [gpu, utilization_pct], label: utilization }
"""


def gpu_state():
    """Power (W), temperature (C) and utilization (%) from nvidia-smi; None where it cannot say."""
    try:
        line = subprocess.run(["nvidia-smi", "--query-gpu=power.draw,temperature.gpu,utilization.gpu",
                               "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
        return [float(v) if v.strip() not in ("", "[N/A]") else None for v in line.splitlines()[0].split(",")]
    except Exception:
        return [None, None, None]


def check(name, passed, observed, expected):
    checks.append({"name": name, "passed": bool(passed), "observed": observed, "expected": expected})


try:
    smi = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                         capture_output=True, text=True, timeout=60).stdout.strip().splitlines()
except Exception as e:  # no driver at all: the job could not run
    smi = []
    print(f"nvidia-smi failed: {e}")
check("nvidia-smi sees a GPU", smi, smi, ">= 1 GPU")

try:
    import torch

    check("PyTorch sees CUDA", torch.cuda.is_available(), torch.version.cuda, "CUDA available")
    if torch.cuda.is_available():
        a = torch.randn(args.size, args.size, device="cuda", dtype=torch.float16)
        b = torch.randn(args.size, args.size, device="cuda", dtype=torch.float16)
        for _ in range(3):  # warm up
            a @ b
        torch.cuda.synchronize()
        n, t0 = 20, time.time()
        for _ in range(n):
            a @ b
        torch.cuda.synchronize()
        seconds = time.time() - t0
        tflops = 2 * args.size**3 * n / seconds / 1e12
        metrics["fp16_matmul_tflops"] = round(tflops, 1)
        check("fp16 matmul throughput", tflops > 10, round(tflops, 1), "> 10 TFLOPS")

        if args.load_seconds > 0:
            # Sustained load, sampled every 0.1 s: does throughput hold as the GPU heats up?
            episode = os.path.join(args.out, "episodes", "load")
            os.makedirs(episode, exist_ok=True)
            rows, start = [], time.time()
            while time.time() - start < args.load_seconds:
                t1, n = time.time(), 0
                while time.time() - t1 < 0.1:
                    a @ b
                    n += 1
                    if n % 4 == 0:
                        torch.cuda.synchronize()
                torch.cuda.synchronize()
                dt = time.time() - t1
                power, temp, util = gpu_state()
                rows.append((time.time() - start, 2 * args.size**3 * n / dt / 1e12, power, temp, util))
            with open(os.path.join(episode, "gpu.csv"), "w") as f:
                f.write("timestamp,tflops,power_w,temperature_c,utilization_pct\n")
                for r in rows:
                    f.write(",".join("" if v is None else f"{v:.3f}" for v in r) + "\n")
            with open(os.path.join(args.out, ".dreamrc"), "w") as f:
                f.write(DREAMRC)
            sustained = sorted(r[1] for r in rows)[len(rows) // 2]
            metrics["sustained_tflops_median"] = round(sustained, 1)
            # Throughput that collapses under load points at throttling or a sick GPU.
            check("throughput holds under load", sustained > 0.7 * tflops, round(sustained, 1), f"> 70% of {round(tflops, 1)} TFLOPS")
except ImportError as e:
    check("PyTorch installed", False, str(e), "import torch")

passed = all(c["passed"] for c in checks)
summary = {"passed": passed, "gpus": smi, "checks": checks}
print(json.dumps(summary, indent=2))
with open(os.path.join(args.out, "summary.json"), "w") as f:
    json.dump(summary, f, indent=2)
# metrics.json: headline numbers DreamLake charts on the run page ([{step, values}]).
metrics["checks_passed"] = sum(c["passed"] for c in checks) / len(checks)
with open(os.path.join(args.out, "metrics.json"), "w") as f:
    json.dump([{"step": 0, "values": metrics}], f)
raise SystemExit(0 if passed else 1)
