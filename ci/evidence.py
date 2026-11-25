#!/usr/bin/env python3
"""Save a job's outputs as DreamLake CI/CT evidence.

    python3 ci/evidence.py OUTPUT_DIR [--include GLOB ...] [--exclude GLOB ...]

Copies the matching files under OUTPUT_DIR into $DREAMLAKE_RUN_DIR (keeping
their relative paths) and writes the evidence manifest, results.json, last.
DreamLake then uploads exactly those files to the run's evidence Source, where
the CI/CT run page lists and opens them.

- Your code keeps writing where it always did; nothing in it needs to know
  about DreamLake.
- If OUTPUT_DIR *is* $DREAMLAKE_RUN_DIR, files are listed in place.
- Limits DreamLake enforces are checked here first: at most 1024 files, each
  at most 2 GiB, relative paths without `..`. Files over the limit are skipped
  with a warning instead of failing the whole upload.
- Outside a DreamLake runner ($DREAMLAKE_RUN_DIR unset) it only prints what it
  would save, so the same workflow also runs on GitHub-hosted runners.

Standard library only; Python 3.8+.
"""
import argparse
import fnmatch
import json
import os
import shutil
import sys

MAX_FILES = 1024
MAX_BYTES = 2 * 1024**3


def matches(rel, patterns):
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(os.path.basename(rel), p) for p in patterns)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output_dir", help="directory your job wrote its outputs to")
    parser.add_argument("--include", action="append", default=[], metavar="GLOB",
                        help="keep only matching paths (relative to OUTPUT_DIR); repeatable; default: everything")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                        help="leave out matching paths; repeatable")
    args = parser.parse_args()

    src = os.path.abspath(args.output_dir)
    run_dir = os.environ.get("DREAMLAKE_RUN_DIR")
    if not os.path.isdir(src):
        print(f"evidence: {args.output_dir} does not exist; nothing to save", file=sys.stderr)
        return 0

    chosen, skipped = [], []
    for root, dirs, names in os.walk(src):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, src).replace(os.sep, "/")
            if rel == "results.json" or os.path.islink(path):
                continue
            if args.include and not matches(rel, args.include):
                continue
            if matches(rel, args.exclude):
                continue
            size = os.path.getsize(path)
            if size > MAX_BYTES:
                skipped.append((rel, f"{size / 1024**3:.1f} GiB is over the 2 GiB limit"))
                continue
            if len(chosen) >= MAX_FILES:
                skipped.append((rel, f"over the {MAX_FILES}-file limit"))
                continue
            chosen.append((rel, path))

    for rel, why in skipped:
        print(f"::warning::evidence: skipped {rel}: {why}")
    if not run_dir:
        print(f"evidence: not on a DreamLake runner ($DREAMLAKE_RUN_DIR unset); would save {len(chosen)} file(s)")
        for rel, _ in chosen:
            print(f"  {rel}")
        return 0

    run_dir = os.path.abspath(run_dir)
    in_place = os.path.realpath(src) == os.path.realpath(run_dir)
    for rel, path in chosen:
        if not in_place:
            dest = os.path.join(run_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(path, dest)
    # The manifest goes last: DreamLake reads it once the job has finished.
    with open(os.path.join(run_dir, "results.json"), "w") as f:
        json.dump([rel for rel, _ in chosen], f)
    total = sum(os.path.getsize(p) for _, p in chosen)
    print(f"evidence: saved {len(chosen)} file(s), {total / 1024**2:.1f} MiB; they appear on the run's DreamLake page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
