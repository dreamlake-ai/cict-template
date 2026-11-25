# DreamLake CI/CT template

Run GitHub Actions jobs on **DreamLake GPU** machines and keep what each run
produced (videos, metrics, summaries) on its DreamLake run page. Three working
examples, each a single workflow you can copy into your own repository:

| Workflow | What it shows | First run | Later runs |
| --- | --- | --- | --- |
| [`gpu.yml`](.github/workflows/gpu.yml) | The GPU is there and does real work (PyTorch fp16 matmul) | ~3 min | ~1 min |
| [`mujoco.yml`](.github/workflows/mujoco.yml) | MuJoCo control task with checks and a rendered video (headless EGL) | ~2 min | ~1 min |
| [`isaac-sim.yml`](.github/workflows/isaac-sim.yml) | Headless Isaac Sim: rigid-body physics and RTX rendering | ~10–15 min | ~5 min |

Each run is billed by the GPU time it uses (RTX 5090 $1.20/GPU-hour, RTX PRO
6000 $2.40/GPU-hour; while billing is on Stripe's sandbox, paid with test
cards). The examples only start when you run them, never on push.

## Start here

**New repository**: choose **Use this template** above and create it
**private**. DreamLake runs jobs from private repositories only: a public
repository runs anyone's pull request on your GPUs.

**Existing repository**: copy one workflow from `.github/workflows/` and
`ci/evidence.py` into it. Nothing else in your code changes.

Then, in DreamLake:

1. **Connect GitHub**: CI / CT → **Setup** → Connect GitHub, and select this
   repository when GitHub asks which repositories the DreamLake App may use.
2. **DreamLake GPU**: Setup shows whether it is enabled for your namespace
   (the DreamLake team enables it); choose **Start using**.
3. **Credit**: a namespace owner adds credit in Settings → Billing. Jobs wait
   in the queue, and say why, until there is enough.
4. **Run**: CI / CT → **Run workflow**, pick this repository, a workflow and a
   branch, and run. Or use GitHub's **Actions → Run workflow**.

`dl cict status <namespace>` shows which of these steps are done.

## How a workflow uses DreamLake

Three things, all visible in [`gpu.yml`](.github/workflows/gpu.yml):

```yaml
jobs:
  gpu:
    runs-on: dreamlake-gpu-rtx5090        # 1. a DreamLake GPU label
    steps:
      - uses: actions/checkout@v4
      - run: python my_tests.py --out outputs   # your code, writing where it always does
      - name: Save evidence                # 2. keep the outputs, pass or fail
        if: always()
        run: python3 ci/evidence.py outputs
```

3. **Exit codes decide pass or fail**: your job's own steps decide; DreamLake
   does not read a result format. The examples exit 0 when every check passed,
   1 when a check failed and 2 when they could not run.

What `ci/evidence.py` saves appears on the run's DreamLake page and in the
namespace's evidence Source. Optional files DreamLake understands:

- `metrics.json` — headline numbers it charts:
  `[{"step": 0, "values": {"pass_rate": 1.0, "fps": 812}}]` (at most 128
  points of 16 numbers).
- `.dreamrc` — opens the run folder as a visualization in the Source viewer
  (for example a MuJoCo replay with a timeline). See the DreamLake docs.

`ci/evidence.py OUTPUT_DIR [--include GLOB] [--exclude GLOB]` copies the files
into `$DREAMLAKE_RUN_DIR` and writes the manifest DreamLake reads
(`results.json`): at most 1024 files, each at most 2 GiB; bigger files are
skipped with a warning. Outside DreamLake it only prints what it would save,
so the same workflow still runs on GitHub-hosted runners.

## On the machine

| | |
| --- | --- |
| Per job | 1 GPU, 8 CPU cores, 32 GB memory; 2 h (`dreamlake-gpu-rtx5090`, `-rtxpro6000`) or 8 h (`dreamlake-gpu-rtx5090-8h`) |
| OS | x86_64 Linux (Ubuntu), NVIDIA driver installed, outbound internet |
| You are | an ordinary user: no root, no `apt install` (install with pip/uv/conda into your own directories) |
| `$DREAMLAKE_CACHE_DIR` | kept between runs and private to your namespace: put package caches and downloads here |
| `$RUNNER_TEMP` | the node's own disk for this run; large installs go here, removed after the job |
| `$DREAMLAKE_RUN_DIR` | this run's evidence folder (what `ci/evidence.py` writes to) |

Tips the examples follow:

- **Cache dependencies** in `$DREAMLAKE_CACHE_DIR` (`UV_CACHE_DIR`,
  `PIP_CACHE_DIR`, model downloads): the first run pays for the download, the
  next ones do not.
- **Headless rendering**: MuJoCo needs `MUJOCO_GL=egl`; Isaac Sim runs with
  `headless: True` and needs `OMNI_KIT_ACCEPT_EULA=YES`.
- **Big installs** (Isaac Sim is ~35 GB unpacked) go on the node's own disk
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
evidence it saved. The DreamLake docs' CI/CT guide lists every state.
