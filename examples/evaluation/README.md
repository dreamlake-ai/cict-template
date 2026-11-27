# Evaluation harness examples

```sh
uv run --python 3.12 --with 'dreamlake-eval[pytest]==0.1.1' --with 'pytest-asyncio>=1,<2' \
  python examples/evaluation/run.py --output /tmp/my-new-evaluation
```

The CPU example discovers `test_accuracy.py` and `test_async.py` independently,
records their full expected inventories before execution, and runs them as two
jobs sharing one evaluation ID. It reads only their explicitly named report files.
`aggregate/aggregate.json` retains coverage and outcomes; the root `.dreamrc`
opens the entire inventory and each metric subdirectory has its own `.dreamrc`.
Zero reward is measured; duration absent from the async test remains missing.

`pytest-asyncio` owns async fixtures and event-loop lifetime. This adapter works
alongside it. Awaiting local Python is not detached remote execution or durable
resume. External orchestration owns worker cancellation/recovery; retry with a
new attempt ID and increasing attempt number. Checkpoint restore belongs to the
workload, and fixture state is not transferred between workers.

The existing GPU, MuJoCo and Isaac Sim workflows call `run_workload.py` around
their existing commands. This is one explicit trial per workload, not discovery
of each simulator's internal checks. It records execution before starting,
preserves the command exit status, reads only the explicitly supplied metrics
file after completion, and writes reports under `outputs/evaluation/`. Existing
videos, telemetry and visualization files are retained. It does not capture
terminal output or auto-upload logs. No GPU/simulator run is performed by the CPU
acceptance workflow; those workflows still require manual dispatch.

Full guide: https://eval.dreamlake.ai

GitHub retries use `GITHUB_RUN_ATTEMPT` for attempt directories, IDs and numbers.
Command wrappers take `--job-id`; the included workflows combine GitHub job and
machine labels so identical test names on different machines remain separate.
For new matrix axes, include each variant in that explicit stable job identity.

## Optional links to existing Dash runs

Copy an actual run's canonical browser URL from DreamLake Dash. Use its
`https://dreamlake.ai/NAMESPACE/dash/PROJECT/RUN` address without query/fragment;
those uppercase terms describe the route, not an existing run. Local Dash files
and a recording prefix do not establish a published run URL.

Create your own JSON file mapping exact node IDs from discovery to those copied
URLs. For this example the IDs include `test_accuracy.py::test_accuracy[seed-zero]`
and `test_async.py::test_async_trial`. Omit entries without a real destination.
An empty `{}` is a valid map and records no links. Then run:

```sh
python examples/evaluation/run.py --output /tmp/new-linked-evaluation --dash-links /absolute/path/to/your-dash-links.json
```

The example-only `conftest.py` fixture calls
`eval_trial.artifact(actual_dash_run_url, name="Dash run")` for each explicitly
mapped test, including async tests. This is not a new framework option or an
automatic run finder. It creates no remote workload, uploads nothing, and makes
no claim that the destination exists or that the current reader can access it.
`aggregate.json` retains the selected attempt's references at
`rows[].attempt.artifacts`; use the canonical report, not the lossy `cict.json`
projection. A fresh retry must explicitly record its own link.
