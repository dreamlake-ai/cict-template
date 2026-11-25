"""GPU smoke test: is the GPU there, and does it do real work?

Writes summary.json and metrics.json to --out; exits 0 when every check passed,
1 when a check failed, 2 when the job could not run at all.
"""
import argparse
import json
import os
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument("--out", default="outputs")
parser.add_argument("--size", type=int, default=8192, help="matrix size for the matmul benchmark")
args = parser.parse_args()
os.makedirs(args.out, exist_ok=True)

checks, metrics = [], {}


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
