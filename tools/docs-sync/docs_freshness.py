#!/usr/bin/env python3
"""
docs_freshness.py — documentation coverage + freshness metric for roadmap 2.30.

Zero third-party dependencies (stdlib + git only). Works on any repo that ships
a `.docs-sync.json` manifest at its root.

It answers two questions, both required by the 2.30 gate:

  1. COVERAGE  — what share of the modules declared in the manifest actually
                 have a non-trivial doc file? (target: >= 80%)
  2. FRESHNESS — for each module, is its doc older than the code it documents?
                 A module is STALE when its newest code commit is more than
                 `freshness_max_lag_days` newer than its newest doc commit.

The script is read-only. It prints a human summary, writes a machine-readable
JSON report, and chooses an exit code based on --mode:

  --mode report  (default) : always exit 0  (observe-only; use while ramping up)
  --mode gate              : exit 1 if coverage < target, any module is stale, OR
                             any of a module's declared code paths no longer
                             exists (manifest drift)

Usage:
  python tools/docs-sync/docs_freshness.py \
      --manifest .docs-sync.json \
      --json-out docs-freshness.json \
      --mode report

Manifest schema (.docs-sync.json):
{
  "docs_root": "doc",
  "coverage_target": 0.80,
  "freshness_max_lag_days": 30,
  "min_doc_bytes": 400,
  "modules": [
    {
      "name": "signaling",
      "doc": "doc/modules/signaling.md",
      "code_paths": ["src/common/signaling"]
    }
  ],
  "ignore_code_globs": ["**/*.md", "**/CMakeLists.txt"]
}
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def run_git(args, cwd):
    """Run a git command, returning stripped stdout ('' on failure)."""
    try:
        out = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip()
    except FileNotFoundError:
        print("ERROR: git not found on PATH", file=sys.stderr)
        sys.exit(2)


def last_commit_epoch(paths, cwd, ignore_globs):
    """Newest commit-timestamp (unix epoch) touching any of `paths`.

    Returns 0 if no commit ever touched them (path missing / untracked)."""
    if not paths:
        return 0
    # One `git log` for the whole path set instead of one per path: git already
    # takes several pathspecs and reports the newest commit touching any of them,
    # which is exactly the value this function returns. On a manifest with many
    # code paths that is the difference between one process spawn and N.
    ts = run_git(["log", "-1", "--format=%ct", "--"] + list(paths), cwd)
    newest = int(ts) if ts.isdigit() else 0
    # Ignore-globs are advisory: they exist so a future, finer-grained
    # implementation can exclude doc/build noise from "code" timestamps.
    # The current path-level granularity does not need them, but we keep the
    # parameter so the manifest contract stays stable.
    _ = ignore_globs
    return newest


def doc_is_present(doc_path, repo_root, min_bytes):
    """A doc 'counts' only if it exists and is larger than a placeholder."""
    full = os.path.join(repo_root, doc_path)
    if not os.path.isfile(full):
        return False, 0
    size = os.path.getsize(full)
    return size >= min_bytes, size


def missing_code_paths(code_paths, repo_root):
    """Declared code paths that no longer resolve on disk.

    Every declared path must exist: with `any()` a module that lists five paths
    of which four were deleted still looked healthy, so real manifest drift went
    unreported until the last path vanished."""
    return [p for p in code_paths if not os.path.exists(os.path.join(repo_root, p))]


def human_date(epoch):
    if not epoch:
        return "never"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser(description="Docs coverage + freshness metric (roadmap 2.30)")
    ap.add_argument("--manifest", default=".docs-sync.json")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--json-out", default="docs-freshness.json")
    ap.add_argument("--mode", choices=["report", "gate"], default="report")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    manifest_path = os.path.join(repo_root, args.manifest)
    if not os.path.isfile(manifest_path):
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        print("Run docs-init/docs-update to generate it, or add it by hand.", file=sys.stderr)
        sys.exit(2)

    with open(manifest_path, encoding="utf-8") as fh:
        m = json.load(fh)

    target = float(m.get("coverage_target", 0.80))
    max_lag_days = int(m.get("freshness_max_lag_days", 30))
    min_doc_bytes = int(m.get("min_doc_bytes", 400))
    ignore_globs = m.get("ignore_code_globs", [])
    modules = m.get("modules", [])
    max_lag_secs = max_lag_days * 86400

    if not modules:
        print("ERROR: manifest declares no modules", file=sys.stderr)
        sys.exit(2)

    # Validate each module up front so a malformed entry fails fast with a clear
    # message instead of silently looking like "manifest drift" (e.g. an empty
    # code_paths would otherwise look like a module whose code all vanished).
    for i, mod in enumerate(modules):
        name = mod.get("name")
        doc = mod.get("doc")
        code_paths = mod.get("code_paths")
        if not isinstance(name, str) or not name.strip():
            print(f"ERROR: module #{i} is missing a non-empty 'name'", file=sys.stderr)
            sys.exit(2)
        if not isinstance(doc, str) or not doc.strip():
            print(f"ERROR: module '{name}' is missing a non-empty 'doc' path", file=sys.stderr)
            sys.exit(2)
        if (not isinstance(code_paths, list) or not code_paths
                or not all(isinstance(p, str) and p.strip() for p in code_paths)):
            print(f"ERROR: module '{name}' must declare a non-empty 'code_paths' list of strings", file=sys.stderr)
            sys.exit(2)

    rows = []
    documented = 0
    stale = []
    missing_code = []
    missing_detail = {}

    for mod in modules:
        name = mod["name"]
        doc_path = mod["doc"]
        code_paths = mod.get("code_paths", [])

        gone = missing_code_paths(code_paths, repo_root)
        if gone:
            # Code this module pointed at is gone — manifest drift.
            missing_code.append(name)
            missing_detail[name] = gone

        has_doc, doc_size = doc_is_present(doc_path, repo_root, min_doc_bytes)
        if has_doc:
            documented += 1

        code_epoch = last_commit_epoch(code_paths, repo_root, ignore_globs)
        doc_epoch = last_commit_epoch([doc_path], repo_root, ignore_globs)
        lag = code_epoch - doc_epoch  # >0 => code newer than doc
        # bool(): the `and` chain short-circuits to the int 0 when code_epoch is
        # 0, which would put `"stale": 0` (not false) in the JSON report.
        is_stale = bool(has_doc and code_epoch and lag > max_lag_secs)

        if is_stale:
            stale.append(name)

        rows.append({
            "module": name,
            "doc": doc_path,
            "documented": has_doc,
            "doc_bytes": doc_size,
            "code_last_commit": human_date(code_epoch),
            "doc_last_commit": human_date(doc_epoch),
            "lag_days": round(lag / 86400, 1) if (code_epoch and doc_epoch) else None,
            "stale": is_stale,
        })

    total = len(modules)
    coverage = documented / total if total else 0.0

    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "repo": os.path.basename(repo_root.rstrip("/")),
        "coverage": round(coverage, 4),
        "coverage_target": target,
        "documented_modules": documented,
        "total_modules": total,
        "stale_modules": stale,
        "manifest_drift_missing_code": missing_code,
        "manifest_drift_missing_paths": missing_detail,
        "freshness_max_lag_days": max_lag_days,
        "modules": rows,
    }

    with open(os.path.join(repo_root, args.json_out), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    # ---- human summary -----------------------------------------------------
    print("=" * 72)
    print(f"Documentation freshness — {report['repo']}")
    print("=" * 72)
    print(f"Coverage : {coverage*100:5.1f}%  ({documented}/{total} modules)   target >= {target*100:.0f}%")
    print(f"Stale    : {len(stale)} module(s)  (code newer than doc by > {max_lag_days}d)")
    print("-" * 72)
    print(f"{'module':28} {'doc?':5} {'code':11} {'doc':11} {'lag(d)':7} stale")
    for r in rows:
        print(f"{r['module'][:28]:28} "
              f"{'yes' if r['documented'] else 'NO':5} "
              f"{r['code_last_commit']:11} "
              f"{r['doc_last_commit']:11} "
              f"{str(r['lag_days']) if r['lag_days'] is not None else '-':7} "
              f"{'STALE' if r['stale'] else ''}")
    if missing_code:
        print("-" * 72)
        print("Manifest drift (declared code path no longer exists):")
        for name in missing_code:
            print(f"  {name}: " + ", ".join(missing_detail.get(name, [])))
    print("=" * 72)

    failing = coverage < target or bool(stale) or bool(missing_code)
    if args.mode == "gate" and failing:
        reasons = []
        if coverage < target:
            reasons.append(f"coverage {coverage*100:.1f}% < target {target*100:.0f}%")
        if stale:
            reasons.append(f"{len(stale)} stale module(s)")
        if missing_code:
            reasons.append(f"{len(missing_code)} module(s) with missing code paths (manifest drift)")
        print("GATE FAILED: " + "; ".join(reasons), file=sys.stderr)
        sys.exit(1)

    print(f"mode={args.mode}: " + ("issues found (not gating)" if failing else "all good"))
    sys.exit(0)


if __name__ == "__main__":
    main()
