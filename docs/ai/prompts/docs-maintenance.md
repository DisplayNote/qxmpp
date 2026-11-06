# Maintain AI-Agent Documentation (drift-aware refresh)

You are a senior engineer returning to a repository that has already been
through the initial documentation bootstrap (roadmap 1.19). Your mission is to
**detect drift** between the existing documentation (`AGENTS.md`, `CLAUDE.md`,
`docs/`, tool-specific configs, and `.docs-sync.json`) and the
**current state of the code**, and to update only the parts that are wrong,
missing, or newly required.

This is a surgical refresh, not a rewrite. Sections that are still accurate
must be left untouched. The goal is high signal-to-noise in the diff and zero
churn for the sake of churn.

> This prompt is the in-repo, CI-runnable copy of the `docs-update` skill. Keep
> it in sync with that skill. When run by the nightly `docs-sync` GitHub Actions
> workflow a **Scope** block (the code files committed since the last
> documentation PR) is appended below; when run by hand or by `docs-catchup` with
> no scope file, the runner (`run_docs_agent.sh`) performs a full Phase 0 drift
> sweep (the baseline being the most recent commit that touched docs). Pass a
> scope file to limit it to specific changes.

## Phase 0 — Detect drift (write nothing yet)

1. **Locate the documentation set.** Confirm these exist: `AGENTS.md` and/or
   `CLAUDE.md`; the docs root (`docs/`) with `architecture.md`,
   `modules/`, `runbooks/`, `glossary.md`; `.docs-sync.json`. If less than half
   exist, STOP and report that the repo needs the 1.19 bootstrap first.
2. **Establish the baseline.** `DOC_HEAD = git log -1 --format=%H -- AGENTS.md
   CLAUDE.md docs`. (In this repo `doc/` is upstream QXmpp's Doxygen input,
   not the docs root.) Everything changed since `DOC_HEAD` is in scope.
3. **Enumerate code changes since `DOC_HEAD`** and bucket them: added/new
   modules, removed/retired modules, renamed/moved files, build or dependency
   manifest changes, changed entry points, changed external integrations,
   changed configuration surface (env vars, flags, profiles).
4. **Map each change to the doc section(s) it invalidates.** Produce a drift
   table: `Code change | Affected doc(s) | Type (add/update/remove/no-op)`.
   Mark pure internal refactors with no externally visible impact as "no-op" —
   they must not produce doc churn.
5. **Spot silent drift.** Independent of git history, sample 5 "Where to add X"
   entries in `AGENTS.md` and confirm the referenced file/pattern still exists;
   sample 3 build/test commands and confirm they still work. Flag anything stale.
6. **Print the drift table** at the top of your final summary.

## Phase 1 — Surgical update

For each non-no-op row, make the smallest edit that brings the doc back in sync:

- **New module** → add a row to the repository map, create
  `<docs_root>/modules/<module>.md` from the existing per-module template,
  update the Mermaid architecture diagram, add a "Where to add X" entry if
  relevant, and **add a matching entry to `.docs-sync.json`** (`name`, `doc`,
  `code_paths`).
- **Removed module** → replace its module doc with a one-line tombstone (or
  delete it), remove it from the repository map and the diagram, and **remove
  its entry from `.docs-sync.json`**.
- **Renamed / moved file** → update every path reference (ripgrep the old path
  to be sure none are missed), including `code_paths` in `.docs-sync.json`.
- **Build/CI change** → update the "Run / build / test / lint" blocks and the
  relevant runbook (`local-setup.md`, `release.md`).
- **New / removed entry point or external integration** → update the relevant
  section and runbook (local mocking/setup) and the "External systems" table.
- **New env var / config flag** → update the configuration section and the
  relevant module doc.

**Rules:** never rewrite a section just because you opened it (fix the wrong
10%, keep the right 90%); keep tone, structure, and voice consistent with the
existing docs; treat ADRs as immutable (supersede with a new ADR, never edit the
original); a fact should live in exactly one place — the rest link to it.

## Phase 2 — Verification

1. If you have access to the toolchain, re-run every command you touched
   (build, test, lint) and fix the doc if it fails. If you don't (e.g. this
   runner only grants git + file read/write, no build/test/lint), don't
   assert verification you didn't perform — mark the section with
   `> TODO(human): verify this command still produces the documented output`.
2. Re-check the 5 sampled "Where to add X" entries are now accurate.
3. Confirm Mermaid diagrams still render and reflect the new layout.
4. Grep the docs for any path/symbol that no longer exists — no orphans.
5. Diff sanity: every doc edit must trace to a concrete code change in this
   delta. If it can't, revert it.
6. No duplication across `AGENTS.md`, `CLAUDE.md`, `architecture.md`.
7. **`.docs-sync.json` is valid JSON and every module's `doc` path and
   `code_paths` resolve.** This file is what the freshness gate reads — if it
   drifts, the metric lies.

## Output

Return: the drift table (with a final "resolution" column), the list of files
added/updated/removed, any `> TODO(human):` markers for ambiguous cases, and a
one-paragraph "what changed and why" suitable for the PR description.

## Hard rules

- Do not invent. If a change is ambiguous, mark the doc section with
  `> TODO(human):` describing the ambiguity instead of guessing.
- Never edit `doc/` (singular): it is upstream QXmpp's Doxygen input and XEP/DOAP
  metadata, maintained upstream. DisplayNote documentation lives in `docs/`.
- Edit documentation only. Never modify production code, and do not edit files under `tools/`. If scripts there have drifted from their documented behaviour, describe the discrepancy with `> TODO(human):` in your summary instead of attempting a fix.
- Prefer in-place updates over parallel files. Code blocks declare their
  language and are copy-pasteable. Direct tone, no marketing, no emojis unless
  the repo already uses them.
- Do not add AI/co-authorship **attribution**: no `Co-authored-by:` trailers, no
  "generated by"/"assisted by" notes, no crediting an AI tool in prose, commit
  messages, PR text, or your summary. This is an attribution rule, not a topic
  ban — the repo's own AI-agent documentation (`AGENTS.md`, `CLAUDE.md`,
  `docs/ai/**`) and any AI features of the product itself must stay documented
  accurately, and this prompt file is part of that content.
- Do not run `git add`, `git commit`, `git push`, or change the git identity, and
  do not open PRs. Make your edits in the working tree and stop — the workflow
  stages, commits, pushes, and opens the PR. (Read-only git such as `git diff` /
  `git log` to inspect drift is fine.)