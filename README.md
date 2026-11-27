# DreamLake Evaluations template

Run GitHub Actions jobs on **DreamLake GPU** machines and keep what each run
produced (videos, metrics, summaries) on its DreamLake run page. Three working
examples, each a single workflow you can copy into your own repository:

| Workflow | What it shows | Time on the GPU | Cost (RTX 5090) |
| --- | --- | --- | --- |
| [`gpu.yml`](.github/workflows/gpu.yml) | The GPU is there and does real work (PyTorch fp16 matmul); charts throughput, power and temperature under 10 s of load | ~3 min the first time (PyTorch downloads), ~1 min after | ~$0.06 |
| [`mujoco.yml`](.github/workflows/mujoco.yml) | A control task with checks; replays the rendered video with the joint angles against their targets (MuJoCo, headless EGL) | under 1 min | ~$0.01 |
| [`isaac-sim.yml`](.github/workflows/isaac-sim.yml) | Headless Isaac Sim: rigid-body physics and RTX rendering; replays the camera video with the cubes' height and speed | ~5 min; up to ~15 min on a node that has not installed Isaac Sim yet | $0.10–0.30 |

Each run is billed by the GPU time it uses (RTX 5090 $1.20/GPU-hour, RTX PRO
6000 $2.40/GPU-hour; while billing is on Stripe's sandbox, paid with test
cards). The GPU examples only start when you run them, never on push.


## Start with existing pytest tests

Install `dreamlake-eval[pytest]==0.1.0`. Existing pytest assertions, parametrization,
markers and fixtures remain pytest's. Add `--eval-output NEW_DIR --eval-run-id ID
--eval-job-id JOB --eval-attempt-id ATTEMPT` to emit explicit reports. Collection
imports test modules/hooks but does not execute test bodies or set up fixtures:
`dreamlake-eval discover --output suite.json -- tests/`.

The CPU-only [evaluation workflow](.github/workflows/evaluation.yml) runs the
[pytest and async example](examples/evaluation/README.md), discovers individual
files, records expected jobs, then assembles per-metric `.dreamrc` heatmaps.
It runs on ordinary GitHub-hosted CPU runners. The GPU workflows remain manual.
No DreamLake GPU allocation or billing setup is needed for this local example.

## Start here

**New repository**: choose **Use this template** above and create it
**private**. DreamLake runs jobs from private repositories only: a public
repository runs anyone's pull request on your GPUs.

**Existing repository**: copy one workflow from `.github/workflows/`, or make
two changes to your own: the `runs-on` label, and the evidence step below.
Nothing else in your code changes.

Then, in DreamLake:

1. **Connect GitHub**: Evaluations → **Setup** → Connect GitHub, and select this
   repository when GitHub asks which repositories the DreamLake App may use.
2. **DreamLake GPU**: Setup shows whether it is enabled for your namespace
   (the DreamLake team enables it); choose **Start using**.
3. **Credit**: a namespace owner adds credit in Settings → Billing. Jobs wait
   in the queue, and say why, until there is enough.
4. **Run**: Evaluations → **Run workflow**, pick this repository, a workflow and a
   branch, and run. Or use GitHub's **Actions → Run workflow**.

`dl cict status <namespace>` shows which of these steps are done.

## How a workflow uses DreamLake

Three things, all visible in [`gpu.yml`](.github/workflows/gpu.yml):

```yaml
jobs:
  gpu:
    runs-on: blacksmith-4vcpu-gpu-rtx5090-ubuntu-2404        # 1. a DreamLake GPU label
    steps:
      - uses: actions/checkout@v4
      - run: python my_tests.py --out outputs   # your code, writing where it always does
      - uses: dreamlake-ai/cict-evidence@v1   # 2. keep the outputs, pass or fail
        if: always()
        with:
          path: outputs
```

3. **Exit codes decide the GitHub job result**: the evaluation harness also
   emits structured execution states, explicit verdicts and metrics. The examples exit 0 when every check passed,
   1 when a check failed and 2 when they could not run.

What [`dreamlake-ai/cict-evidence`](https://github.com/dreamlake-ai/cict-evidence) saves appears on the run's DreamLake page and in the
namespace's evidence Source. Optional files DreamLake understands:

- `metrics.json` — headline numbers it charts:
  `[{"step": 0, "values": {"pass_rate": 1.0, "fps": 812}}]` (at most 128
  points of 16 numbers).
- `.dreamrc` — opens the run folder as a visualization in DreamLake's viewer
  (the run page's Evidence tab and the Source). Every example writes one: an
  `episodes/<name>/` folder holds videos (`*.mp4`, H.264) and tables
  (`*.csv` with a `timestamp` column, in seconds) on one clock, and the
  `.dreamrc` lays them out as a video, charts and a timeline. Copy one from
  `examples/` and change the file and column names; the DreamLake docs list
  every view.

The step copies the files into `$DREAMLAKE_RUN_DIR` and writes the manifest
DreamLake reads (`results.json`): at most 1024 files, each at most 2 GiB;
bigger files are skipped with a warning. `include` / `exclude` take globs, one
per line. On GitHub-hosted runners it only lists what it would save, so the
same workflow still runs there.

## On the machine

| | |
| --- | --- |
| Per job | 1 GPU, 8 CPU cores, 32 GB memory; 2 h (`blacksmith-4vcpu-gpu-rtx5090-ubuntu-2404`, `blacksmith-4vcpu-gpu-rtxpro6000-ubuntu-2404`) or 8 h (`blacksmith-4vcpu-gpu-rtx5090-8h-ubuntu-2404`) |
| OS | x86_64 Linux (Ubuntu), NVIDIA driver installed, outbound internet |
| You are | an ordinary user: no root, no `apt install` (install with pip/uv/conda into your own directories) |
| `$DREAMLAKE_CACHE_DIR` | kept between runs on the cluster, separate for your namespace: package caches and downloads |
| `$RUNNER_TEMP` | the node's own disk for this run; large installs go here, removed after the job |
| `$DREAMLAKE_RUN_DIR` | this run's evidence folder (what the evidence step writes to) |
| `$DREAMLAKE_NODE_CACHE_DIR` | kept between runs on the same node, on its own disk, separate for your namespace: big installs and models (DreamLake frees it when the node runs short of disk) |

Tips the examples follow:

- **Install your environment in the workflow**, as on GitHub-hosted runners:
  `uv` is on PATH, and DreamLake sets `UV_CACHE_DIR`, `PIP_CACHE_DIR`
  (cluster cache) and `HF_HOME`, `TORCH_HOME` (node cache), so the first run
  pays for downloads and the next ones do not. No `sudo`/`apt`, no Docker; use
  `uv`, not `python3 -m venv` + `pip` (the system Python has no pip).
- **Headless rendering**: DreamLake sets `MUJOCO_GL=egl` and
  `PYOPENGL_PLATFORM=egl`; Isaac Sim runs with `headless: True` and needs
  `OMNI_KIT_ACCEPT_EULA=YES`.
- **Isaac Sim version**: the example installs 6.2. Isaac Sim 5.1's RTX renderer
  crashes at start-up on the NVIDIA 610 drivers newer nodes run; 6.x runs on
  both the 580 and 610 drivers.
- **Big installs** that should survive between runs go in
  `$DREAMLAKE_NODE_CACHE_DIR` (Isaac Sim keeps its wheels and shader cache
  there). Big installs (Isaac Sim is ~35 GB unpacked) go on the node's own disk
  (`$RUNNER_TEMP`), not on a shared volume.
- **System libraries** a node lacks can be unpacked from Ubuntu packages into
  your own directory and put on `LD_LIBRARY_PATH`; see
  `examples/isaac-sim/run.sh` (libGLU for Isaac Sim's RTX renderer).
- **Inputs**: pass `${{ inputs.* }}` through `env:`, never inside `run:`.
- **Time**: keep `timeout-minutes` under the machine type's limit; a job is
  stopped at that limit.

## When something goes wrong

The run's DreamLake page shows where it waits or failed: why a job is held
(credit, billing, a GPU slot), the step that failed with its log, and the
evidence it saved. The DreamLake docs' Evaluations guide lists every state.
