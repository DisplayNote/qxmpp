# docs-sync — keep documentation in sync, nightly (roadmap 2.30)

Once a night, and only when code actually changed, a GitHub Actions workflow
runs the in-repo `docs-maintenance` prompt through an AI agent over the code
committed to `1.6` since the last documented point, makes the surgical doc
edits, and **opens one documentation PR** against `1.6`.

> **qxmpp:** `1.6` is DisplayNote's branch; the repository's default branch is
> `master` (plain upstream QXmpp). Read [qxmpp: default branch](#qxmpp-default-branch)
> before expecting the workflows to run.

This is the maintenance half of the documentation lifecycle: 1.19 *created* the
docs; 2.30 *keeps them in sync* automatically. It edits documentation only and
never blocks anything.

## Two workflows

- **`docs-sync.yml`** — **nightly** (03:00 UTC) + `workflow_dispatch`. Scoped to
  the code committed to `1.6` since the last documented commit; opens one
  `chore/docs-nightly-*` PR. This is the ongoing mechanism. It runs at most once
  a day, does nothing when no code changed, and pauses while a docs PR is open.
- **`docs-catchup.yml`** — a FULL drift sweep, on demand (`workflow_dispatch`)
  and weekly (Mondays 05:00 UTC). It opens one `chore/docs-catchup-*` PR. Use
  the on-demand run once per repo to reconcile the drift that built up *before*
  this existed; the weekly run is the safety net for silent drift a scoped diff
  can't see (behaviour changed, file barely moved).

### Why nightly and not per-PR

Earlier revisions ran on every `pull_request` push and committed docs into the
PR branch. One agent run per push per open PR is the dominant cost of this pack
and it re-reviewed the same docs repeatedly. Nightly caps it at one run per day
per repo. The trade-off: docs land in a **follow-up** PR rather than inside the
code PR that caused them, so a merged code PR is briefly undocumented. Review
the nightly PR promptly — the sync pauses while one is open.

## Engine — Copilot by default

The agent runs via the **GitHub Copilot CLI** in programmatic mode
(`copilot -p`), billed to your org's Copilot subscription.

**Auth requires a user PAT.** The Copilot CLI authenticates against the model
endpoint with a **user token that has Copilot access**. The Actions built-in
`GITHUB_TOKEN` is a GitHub App (server-to-server) token and is **rejected**
("GitHub App Server-To-Server Tokens are not supported for this endpoint"), so a
PAT is required: create repo secret **`COPILOT_PAT`** = a fine-grained PAT with
the **"Copilot Requests"** permission, owned by a user/service account that
holds a **Copilot seat**. It is passed as `COPILOT_GITHUB_TOKEN` on the agent
step only (the model call) — never for pushing.

> The no-PAT, built-in-token path (`copilot-requests: write`) only works under
> **GitHub Agentic Workflows (gh-aw)**, not the standalone `copilot` CLI used
> here. If avoiding a PAT matters, port these workflows to gh-aw.

To use **Claude Code** instead, set `ENGINE=claude` in the workflow and provide
`ANTHROPIC_API_KEY` (metered, pay-per-use; shares the 2.22 key). The rest of the
pack is identical — the engine is the only thing that changes.

## Files

| File | Purpose |
|---|---|
| `.github/workflows/docs-sync.yml` *(repo root)* | nightly workflow: schedule, anchor + scope, agent, PR |
| `.github/workflows/docs-catchup.yml` *(repo root)* | full-sweep workflow: on-demand backfill + weekly safety net |
| `tools/docs-sync/run_docs_agent.sh` | assembles the prompt + scope and runs the agent (Copilot or Claude) |
| `tools/docs-sync/open_catchup_pr.sh` | opens the documentation PR — `MODE=nightly` or `MODE=catchup` (default) |
| `tools/docs-sync/docs_freshness.py` | coverage + freshness metric (zero deps; the 2.30 gate) |
| `docs/ai/prompts/docs-maintenance.md` *(repo root)* | the drift-aware prompt the agent runs |
| `.docs-sync.json` *(repo root)* | per-repo manifest: module → doc → code paths |

## How it runs

- Triggers on `schedule` (nightly 03:00 UTC) and `workflow_dispatch`. There is
  no `pull_request` trigger, so pushing to a PR never starts an agent run.
- **Resumes from the last documented commit, not from "24h ago".** Every doc
  commit this pack creates carries a `Docs-sync-anchor: <sha>` trailer recording
  the base-branch commit it was written against. The next run diffs
  `<anchor>..HEAD`. This matters: a night that fails, is skipped (no PAT), or
  whose PR sits unmerged does **not** lose those code changes, because the anchor
  only advances when a docs PR merges. An explicit sha (rather than the doc
  commit's parent) keeps it correct under squash and rebase merges too.
  - First run on a repo with no such commit in history: falls back to a **26h**
    window (26, not 24, so scheduler drift can't leave a gap between two nights).
  - `workflow_dispatch` accepts a `since` input (a git date expression such as
    `3 days ago`) to override the anchor for a one-off wider sweep.
- Doc paths (`docs/**`, `AGENTS.md`, `CLAUDE.md`, `.docs-sync.json`, plus upstream
  QXmpp's Doxygen input `doc/**`) are filtered out of the scope, so the workflow never reacts
  to its own commits. **If no code changed, nothing else runs** — no agent, no
  PR, and the run stays green.
- **One docs PR at a time.** If a `chore/docs-*` PR is already open, the run
  skips before the (paid) agent step rather than stacking a second PR. Nothing is
  lost — the anchor hasn't advanced, so the next run re-proposes the full delta.
- If `COPILOT_PAT` isn't configured, the agent step is **skipped (not failed)** —
  the workflow emits a notice and stays green. Configure the secret (below) to
  actually run the agent.
- If the agent produces doc changes, they land on a fresh
  `chore/docs-nightly-<date>-<run>-<attempt>` branch and one PR is opened against
  `1.6`, labelled `docs-sync` + `ai-influenced`. Pushing with `GITHUB_TOKEN`
  does **not** re-trigger workflows, so there is no loop.

## One-time setup (per repo)

1. **Secret `COPILOT_PAT` (required for Copilot).** A fine-grained PAT with the
   "Copilot Requests" permission, from a user/service account that holds a
   Copilot seat. Settings → Secrets and variables → Actions → `COPILOT_PAT`.
   The built-in token cannot be used for Copilot inference (see Engine above).
   *(For the Claude engine instead: add `ANTHROPIC_API_KEY` and set `ENGINE: claude`.)*
2. **Workflow permissions.** Already enabled org-wide at DisplayNote (Settings →
   Actions → General → Workflow permissions = "Read and write"), so engineers
   don't need to touch this. The workflows also declare their own `permissions:`
   block. *(Only relevant if you fork this outside the org.)*
3. **Manifest.** Commit a `.docs-sync.json` at the repo root (see the example).
   Set `docs_root` per repo (`doc` for Montage, `Docs` for Launcher; `docs` here —
   qxmpp's `doc/` is upstream Doxygen input). The agent maintains the `modules`
   list from then on.
4. **Branch protection (recommended).** Require a human review on the PR and add
   a CODEOWNERS rule on the docs root (`docs/**` in this repo) so doc changes
   always get a set of eyes.
5. **Pin the Copilot CLI (recommended).** Both workflows install
   `@github/copilot@${{ vars.COPILOT_CLI_VERSION || 'latest' }}`. Set the repo
   variable `COPILOT_CLI_VERSION` (Settings → Secrets and variables → Actions →
   Variables) to a known-good version so CLI releases can't change flag/behaviour
   under you; bump it deliberately. Left unset, it tracks `latest`.
6. **Drop in the files** at the paths in the table above.
7. **Reconcile existing drift first.** Run `docs-catchup.yml` once via
   Actions → docs-catchup → "Run workflow" to open the backfill PR. Merging it
   plants the first `Docs-sync-anchor:` commit, which is what the nightly then
   resumes from. Verify the nightly with Actions → docs-sync → "Run workflow".

## Cost & guardrails (locked decisions)

- **Cost.** Copilot engine = flat cost on your existing seats (no metered key).
  At most **one agent run per repo per day**, scoped to the code changed since
  the last documented commit, and none at all on a quiet day or while a docs PR
  is open. *(Claude engine is metered; guarded by `--max-turns 60` and the sonnet
  model.)*
- **Docs-only.** The agent's tool allow-list (`write`, `shell(git:*)` — no
  interpreter, so no arbitrary code execution next to `COPILOT_PAT` /
  `ANTHROPIC_API_KEY`) and the staging restriction to
  `AGENTS.md CLAUDE.md docs .docs-sync.json` mean it cannot land
  production-code changes. In qxmpp `doc/` (upstream Doxygen) and `Docs/` are
  deliberately left out of the write surface, unlike the reference pack.
- **Always reviewed.** Commits land on a `chore/docs-*` branch behind a PR;
  nothing reaches a protected branch unreviewed.
- **Attribution.** Commit identity is the generic `docs-sync` bot, and the agent
  is told to add no AI/co-authorship attribution (no `Co-authored-by:` trailers,
  no "generated by" notes, no tool credit) in prose, commits or PR text. That is
  an attribution rule only — it does not stop the agent documenting the repo's
  own AI-agent files (`AGENTS.md`, `CLAUDE.md`, `docs/ai/**`) or AI features of
  the product. Add the `ai-influenced` label via branch policy
  or a CODEOWNERS automation if you want these counted in 2.3.

## Measuring the 2.30 gate

`docs_freshness.py` runs anywhere — no API key, no network:

```bash
python tools/docs-sync/docs_freshness.py --manifest .docs-sync.json --mode report
```

- **Coverage** = documented modules / declared modules (target ≥ 80%).
- **Freshness** = no module whose newest code commit is more than
  `freshness_max_lag_days` (default 30) newer than its doc.
- `--mode report` always exits 0 (use while ramping up). Switch to
  `--mode gate` (e.g. as a separate scheduled job or a required status check)
  once coverage is stable to make staleness a hard signal.

Each workflow uploads a `docs-freshness-*.json` artifact
(`docs-freshness-nightly-<run_id>`, `docs-freshness-catchup-<run_id>`); track the
`coverage` field over time to evidence "manual doc effort < 30 min/week".

## Local dry run (no push, no PR)

```bash
export ENGINE=copilot COPILOT_GITHUB_TOKEN=<pat>   # or: ENGINE=claude ANTHROPIC_API_KEY=sk-ant-...
# Same scope the nightly computes: code changed since the last documented commit.
# Before the first docs PR merges there is no anchor commit, and passing an empty
# rev to `git log` is an error — so only resolve the trailer when one exists, and
# let the HEAD~20 fallback below apply otherwise.
ANCHOR=""
DOCS_COMMIT=$(git log -1 --format=%H --grep='^Docs-sync-anchor:')
if [ -n "$DOCS_COMMIT" ]; then
  ANCHOR=$(git log -1 --format=%B "$DOCS_COMMIT" \
    | sed -n 's/^Docs-sync-anchor:[[:space:]]*//p' | tail -1)
fi
git diff --name-only "${ANCHOR:-HEAD~20}" HEAD \
  | grep -Ev '^(Docs/|doc/|docs/|AGENTS\.md|CLAUDE\.md|\.docs-sync\.json)' > docs-scope.txt
bash tools/docs-sync/run_docs_agent.sh   # edits + stages docs
git diff --cached --stat                 # inspect
git reset --hard                         # discard if only testing
```

## Notes / gotchas

- `fetch-depth: 0` is required: the freshness metric and the `<anchor>..HEAD`
  diff need full history.
- **Two tokens, no loop.** The `COPILOT_PAT` user token authenticates the model
  call only. Pushing + opening the PR use the built-in `GITHUB_TOKEN`, whose
  pushes do **not** re-trigger workflows — so the doc commit can't loop. Never
  push with the PAT (a PAT push *would* re-trigger).
- **Don't strip the `Docs-sync-anchor:` trailer** when merging a docs PR (e.g. by
  hand-editing the squash message). Without it the next run silently falls back
  to a 26h window and skips whatever came before that.
- The nightly documents `1.6` only. Code on a long-lived feature branch is
  documented once it merges, not before.
- Repos not yet through 1.19: run the `docs-init` skill once to bootstrap, then
  add these workflows. `docs_freshness.py` refuses to run without a manifest.
- *Silent drift* a scoped diff can't see is handled by `docs-catchup.yml` (the
  weekly full sweep), not by the nightly.

## qxmpp: default branch

GitHub runs `schedule` triggers, and offers `workflow_dispatch` ("Run workflow"),
only for workflow files that exist on the repository's **default branch**. On
`DisplayNote/qxmpp` that is `master`, which tracks upstream QXmpp and does not
carry these files, so with the pack on `1.6` alone neither workflow runs. One of
these is needed before the nightly does anything (a repository-admin decision,
not made in this PR):

- make `1.6` the default branch of `DisplayNote/qxmpp` (every DisplayNote PR
  already targets it); or
- add `.github/workflows/docs-sync.yml` and `docs-catchup.yml` to `master` as
  well. They check out `1.6` (`base` input / `ref:`) and run the scripts from
  there, so the copies on `master` only need to exist; the scripts, prompt and
  manifest stay on `1.6`.

GitHub Actions is enabled for the fork: upstream's `tests.yml` (`on: [push,
pull_request]`) has been registered since the push that added this pack, and it
runs on every branch push and PR. It is upstream's workflow, not DisplayNote CI
(Azure Pipelines gates the package); its `Install Qt` and `reuse` jobs fail here.
