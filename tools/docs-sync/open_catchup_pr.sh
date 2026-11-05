#!/usr/bin/env bash
# open_catchup_pr.sh — open a dedicated documentation PR. Roadmap 2.30.
#
# Used by both scheduled workflows, neither of which has a PR context. It takes
# the doc changes the agent has already staged, puts them on a fresh branch, and
# opens ONE PR against the base branch for review.
#
# Two modes (MODE env):
#   catchup  (default) - docs-catchup.yml: the one-time backfill and the weekly
#                        FULL drift sweep. The right unit for reconciling drift
#                        that accumulated before this automation existed.
#   nightly            - docs-sync.yml: the nightly sync, scoped to the code
#                        committed to the base branch since the last documented
#                        commit.
#
# Both modes defer to ANY open docs PR (nightly or catch-up) so the two can't
# propose competing edits.
#
# No-op (exit 0) when the agent produced no changes.
#
# Inputs (env):
#   GH_TOKEN    - built-in GITHUB_TOKEN (push + PR). Pushing with it does not
#                 re-trigger workflows.
#   BASE        - base branch to target (default 1.6).
#   MODE        - catchup | nightly (default catchup).
set -euo pipefail

BASE="${BASE:-1.6}"
MODE="${MODE:-catchup}"
: "${GH_TOKEN:?GH_TOKEN required (push + PR create/edit)}"

case "$MODE" in
  catchup)
    BRANCH_PREFIX="chore/docs-catchup-"
    # Broader than our own prefix on purpose: don't stack a catch-up PR on top
    # of an open nightly PR (or vice versa) and hand reviewers conflicting docs.
    DUP_PREFIX="chore/docs-"
    NO_CHANGES_MSG="Drift sweep produced no documentation changes — nothing to open."
    COMMIT_SUBJECT="docs: reconcile technical documentation with current code"
    COMMIT_BODY="One-time/scheduled drift sweep that brings AGENTS.md / CLAUDE.md / docs back in
sync with the code as it stands today (roadmap 2.30). Review for factual
accuracy before merging."
    PR_TITLE="docs: catch-up — reconcile documentation with current code"
    PR_HEADING="### Documentation catch-up (roadmap 2.30)"
    PR_INTRO="This PR reconciles the documentation with the current state of the code — a full
drift sweep, including the silent drift a scoped diff can't see (behaviour
changed, file barely moved).

Please review for factual accuracy before merging."
    ;;
  nightly)
    BRANCH_PREFIX="chore/docs-nightly-"
    # Broader than our own prefix on purpose: don't stack a nightly PR on top of
    # an open catch-up PR (or vice versa) and hand reviewers conflicting docs.
    DUP_PREFIX="chore/docs-"
    NO_CHANGES_MSG="Nightly sync produced no documentation changes — nothing to open."
    COMMIT_SUBJECT="docs: sync technical documentation with recent code changes"
    COMMIT_BODY="Nightly scoped sync that brings AGENTS.md / CLAUDE.md / docs in line with the
code committed to ${BASE} since the last documentation PR (roadmap 2.30).
Review for factual accuracy before merging."
    PR_TITLE="docs: sync documentation with recent code changes"
    PR_HEADING="### Documentation sync (roadmap 2.30)"
    PR_INTRO="This PR updates the documentation invalidated by the code committed to
\`${BASE}\` since the last documentation PR merged. It runs once a night, and
only when code actually changed.

Please review for factual accuracy before merging — until it is merged or
closed, the nightly sync pauses (it never stacks a second docs PR)."
    ;;
  *)
    echo "ERROR: unknown MODE '$MODE' (expected catchup|nightly)" >&2
    exit 2
    ;;
esac

if git diff --cached --quiet; then
  echo "$NO_CHANGES_MSG"
  exit 0
fi

# Don't pile up duplicate documentation PRs: if a matching one is still open
# (e.g. last week's sweep or last night's sync wasn't merged yet), skip this run.
# The callers gate on this too; this is the defense-in-depth copy.
# Fail closed: swallowing the error with `|| echo 0` would read a gh/API failure
# as "nothing open" and open the duplicate PR this check exists to prevent.
if ! OPEN_DOCS_PRS="$(gh pr list --state open --json headRefName \
  --jq "[.[] | select(.headRefName | startswith(\"$DUP_PREFIX\"))] | length")"; then
  echo "ERROR: could not list open PRs to check for an existing documentation PR;" >&2
  echo "       refusing to open one rather than risk a duplicate." >&2
  exit 1
fi
case "$OPEN_DOCS_PRS" in
  ''|*[!0-9]*)
    echo "ERROR: unexpected open-PR count '$OPEN_DOCS_PRS'; refusing to open a duplicate." >&2
    exit 1
    ;;
esac
if [ "$OPEN_DOCS_PRS" != "0" ]; then
  echo "An open documentation PR ($DUP_PREFIX*) already exists; skipping to avoid duplicates."
  exit 0
fi

# Include RUN_ATTEMPT: RUN_ID is stable across re-runs, so without it a re-run
# would reuse the same branch name and collide with the already-pushed branch.
BRANCH="${BRANCH_PREFIX}$(date +%Y%m%d)-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"

git config user.email "github-actions[bot]@users.noreply.github.com"
git config user.name  "docs-sync"

CHANGED="$(git diff --cached --name-only)"

# Defense in depth: never open a documentation PR that carries non-documentation
# changes, even if an earlier step mis-staged a file.
DISALLOWED="$(printf '%s\n' "$CHANGED" | grep -Ev '^(AGENTS\.md|CLAUDE\.md|\.docs-sync\.json|docs/)' || true)"
if [ -n "$DISALLOWED" ]; then
  echo "ERROR: refusing to open a documentation PR with non-documentation files:" >&2
  printf '  %s\n' "$DISALLOWED" >&2
  exit 1
fi

# The base-branch commit these docs were written against. Recorded as a commit
# trailer so the nightly run can resume from exactly here instead of guessing a
# time window: everything up to this sha is documented, everything after it is
# not. An explicit sha (rather than the commit's first parent) keeps this correct
# under merge, squash and rebase merges alike. See docs-sync.yml "Compute
# nightly scope".
ANCHOR_SHA="$(git rev-parse HEAD)"

git checkout -b "$BRANCH"
git commit --quiet \
  -m "$COMMIT_SUBJECT" \
  -m "$COMMIT_BODY" \
  -m "Docs-sync-anchor: $ANCHOR_SHA"
git push origin "HEAD:refs/heads/$BRANCH"

# Regenerate the freshness report now that the documentation commit exists:
# docs_freshness.py reads `git log`, so the pre-commit report understates how
# fresh the docs now are. Best-effort — never block PR creation on it.
if [ -f tools/docs-sync/docs_freshness.py ] && [ -f .docs-sync.json ]; then
  python3 tools/docs-sync/docs_freshness.py --manifest .docs-sync.json \
    --json-out docs-freshness.json --mode report >/dev/null 2>&1 || true
fi

# Defang @mentions in the changed-file list (rendered as raw markdown) so a
# stray @user/@team in a path can't ping people. ZWSP after each '@'.
ZWSP=$(printf '\342\200\213')   # U+200B zero-width space (UTF-8 E2 80 8B)
CHANGED_DISPLAY="${CHANGED//@/@$ZWSP}"

# Render the file list capped at 50 entries with an "…and N more" tail, so a full
# drift sweep can't blow past GitHub's PR-body size limit. awk reads all input
# (no early exit) so this is safe under `set -o pipefail`.
FILES_BLOCK="$(printf '%s\n' "$CHANGED_DISPLAY" | awk 'NF{ if (n < 50) printf "- %s\n", $0; n++ } END{ if (n > 50) printf "- …and %d more\n", n - 50 }')"

COV_LINE=""
if [ -f docs-freshness.json ]; then
  COV_LINE="$(python3 - <<'PY'
import json
try:
    with open("docs-freshness.json", encoding="utf-8") as fh:
        d = json.load(fh)
    print(f"Coverage {d.get('coverage',0)*100:.1f}% ({d.get('documented_modules')}/{d.get('total_modules')} modules).")
except Exception:
    pass
PY
)"
fi
TODOS="$(grep -rn "TODO(human)" AGENTS.md CLAUDE.md Docs doc docs 2>/dev/null | head -20 || true)"
BODY="$(cat <<EOF
$PR_HEADING

$PR_INTRO

**Files**
$FILES_BLOCK

${COV_LINE:+**Freshness** — $COV_LINE
}
$( [ -n "$TODOS" ] && printf '**Needs your input (TODO markers)**\n```\n%s\n```\n' "$TODOS" )

_Documentation-only; generic automation commit identity._
EOF
)"

# Create the PR first WITHOUT labels: `gh pr create --label X` aborts if a label
# doesn't exist in the repo, which would fail an otherwise-valid scheduled run.
gh pr create --base "$BASE" --head "$BRANCH" \
  --title "$PR_TITLE" \
  --body "$BODY" 2>&1 || {
    echo "gh pr create failed; branch '$BRANCH' is pushed — open the PR manually." >&2
    exit 1
  }
# Labels are best-effort: don't fail the run if they aren't defined in the repo.
# We're on the freshly-created branch, so let gh resolve its PR (no identifier).
gh pr edit --add-label "docs-sync" --add-label "ai-influenced" 2>/dev/null \
  || echo "Note: could not add docs-sync/ai-influenced labels (create them to categorize documentation PRs)." >&2
echo "Opened $MODE documentation PR from $BRANCH -> $BASE."
