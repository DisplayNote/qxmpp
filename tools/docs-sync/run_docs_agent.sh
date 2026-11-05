#!/usr/bin/env bash
# run_docs_agent.sh — run the headless docs-maintenance agent over the scope,
# edit documentation only, and stage the result. Roadmap 2.30.
#
# Engine is pluggable (ENGINE env): "copilot" (default) or "claude".
#   copilot : GitHub Copilot CLI in programmatic mode (`copilot -p`). Billed to
#             your existing Copilot seats — no separate model key. Auth via
#             COPILOT_GITHUB_TOKEN (a fine-grained PAT with Copilot access).
#   claude  : Claude Code headless (`claude -p`). Auth via ANTHROPIC_API_KEY.
#
# Inputs (env):
#   ENGINE              - copilot | claude   (default copilot)
#   MAINTENANCE_PROMPT  - default docs/ai/prompts/docs-maintenance.md
#   SCOPE_FILE          - default docs-scope.txt (one path per line;
#                         empty/absent => full drift sweep / catch-up)
#   MODEL               - optional model override (engine-specific)
#   MAX_TURNS           - claude only; default 60 (agent-loop / cost guardrail)
#   COPILOT_GITHUB_TOKEN- copilot engine auth
#   ANTHROPIC_API_KEY   - claude engine auth
#
# Output (consumed by the PR/branch step which commits/pushes/comments):
#   - stages only doc files (AGENTS.md CLAUDE.md doc docs Docs .docs-sync.json)
#   - writes docs-agent.log (full agent transcript)
# Host-agnostic: works under GitHub Actions or a plain shell.
set -euo pipefail

ENGINE="${ENGINE:-copilot}"
MAINTENANCE_PROMPT="${MAINTENANCE_PROMPT:-docs/ai/prompts/docs-maintenance.md}"
# Use plain `-` (not `:-`) so an explicitly empty SCOPE_FILE means "full drift
# sweep" (the documented contract), rather than silently falling back to
# docs-scope.txt if that file happens to exist locally.
SCOPE_FILE="${SCOPE_FILE-docs-scope.txt}"
MAX_TURNS="${MAX_TURNS:-60}"

if [ ! -f "$MAINTENANCE_PROMPT" ]; then
  echo "ERROR: maintenance prompt not found: $MAINTENANCE_PROMPT" >&2
  exit 2
fi

SCOPE=""
if [ -f "$SCOPE_FILE" ]; then
  # Single-pass awk (drop blank lines, stop after 400): a `sed | head -400` pipe
  # would SIGPIPE sed (exit 141) on larger files and abort under `set -o pipefail`.
  SCOPE="$(awk 'NF { print; if (++n == 400) exit }' "$SCOPE_FILE")"
fi

# Build the prompt: in-repo maintenance prompt + run-specific scope + hard rules.
{
  cat "$MAINTENANCE_PROMPT"
  echo
  echo "## Scope for this run"
  if [ -n "$SCOPE" ]; then
    echo "Update only the docs invalidated by these changed files:"
    echo "$SCOPE"
  else
    echo "No scope provided: perform a full drift sweep per Phase 0 (catch-up)."
  fi
  echo
  echo "## Non-negotiable output rules"
  echo "- Edit documentation only (AGENTS.md, CLAUDE.md, docs/**, .docs-sync.json). Never touch production code."
  echo "- NEVER edit doc/ (singular): it is upstream QXmpp's Doxygen input, not DisplayNote documentation. DisplayNote docs live in docs/."
  echo "- NEVER edit anything under tools/ - tools/docs-sync/** in particular. Those scripts run later in this same CI job and tools/docs-sync/README.md documents the guard that is checking you. If they have drifted from their behaviour, say so in your summary as a > TODO(human): instead of editing them."
  echo "- Keep .docs-sync.json in sync: add modules you newly document, drop tombstoned ones."
  echo "- Do NOT add AI/co-authorship attribution: no Co-authored-by trailers, no Generated-by/Assisted-by notes, no AI or tool credit in prose, commit messages, or PR text."
  echo "- This is an attribution rule, not a topic ban: keep existing AI-agent documentation (AGENTS.md, CLAUDE.md, docs/ai/**) accurate, and document AI features of the product normally."
  echo "- End your reply with a section '### Docs summary' (<=6 bullet lines) describing what you changed; list any TODO(human) items."
} > docs-agent-prompt.txt

PROMPT="$(cat docs-agent-prompt.txt)"

# Record HEAD so the post-agent guard can prove the agent didn't move it. The
# working-tree guard alone is bypassable: a `git commit`/`git reset --hard` by
# the agent leaves a clean tree relative to the new HEAD, hiding its edits.
HEAD_BEFORE="$(git rev-parse HEAD 2>/dev/null || true)"

case "$ENGINE" in
  copilot)
    # Auth: the Copilot CLI needs a USER token with Copilot access. The Actions
    # built-in GITHUB_TOKEN is a GitHub App (server-to-server) token and is
    # rejected by the Copilot model endpoint, so pass a PAT as COPILOT_GITHUB_TOKEN.
    # (Do NOT fall back to GH_TOKEN/GITHUB_TOKEN here — that would pick up the
    # Actions App token and fail with "server-to-server tokens are not supported".)
    if [ -z "${COPILOT_GITHUB_TOKEN:-}" ]; then
      echo "ERROR: COPILOT_GITHUB_TOKEN is not set. The Copilot CLI needs a USER" >&2
      echo "       token with Copilot access (fine-grained PAT, 'Copilot Requests'" >&2
      echo "       permission, from an account with a Copilot seat). The Actions" >&2
      echo "       built-in GITHUB_TOKEN does NOT work for Copilot inference." >&2
      exit 2
    fi
    command -v copilot >/dev/null || { echo "ERROR: copilot CLI not installed (npm i -g @github/copilot)" >&2; exit 2; }
    # --allow-tool auto-approves the agent's file writes and git shell commands
    # (reads need no approval); --no-ask-user makes it non-interactive.
    # No interpreter (python/python3/node) is allow-listed on purpose: this job's
    # environment carries COPILOT_PAT (and ANTHROPIC_API_KEY on the claude engine)
    # and the whole transcript is written to docs-agent.log, so a general-purpose
    # code-execution shell sitting next to those secrets buys nothing the docs
    # task needs. Docs-only is enforced again at staging.
    MODEL_ARG=(); [ -n "${MODEL:-}" ] && MODEL_ARG=(--model "$MODEL")
    copilot -p "$PROMPT" \
      "${MODEL_ARG[@]}" \
      --allow-tool='write' \
      --allow-tool='shell(git:*)' \
      --no-ask-user \
      2>&1 | tee docs-agent.log
    ;;
  claude)
    if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
      echo "ERROR: ANTHROPIC_API_KEY is not set (Claude engine auth)" >&2
      exit 2
    fi
    command -v claude >/dev/null || { echo "ERROR: claude CLI not installed (npm i -g @anthropic-ai/claude-code)" >&2; exit 2; }
    export DISABLE_AUTOUPDATER=1
    claude -p "$PROMPT" \
      --model "${MODEL:-claude-sonnet-4-6}" \
      --max-turns "$MAX_TURNS" \
      --permission-mode acceptEdits \
      --allowedTools "Read,Edit,Write,Glob,Grep,Bash(git*)" \
      2>&1 | tee docs-agent.log
    ;;
  *)
    echo "ERROR: unknown ENGINE '$ENGINE' (expected copilot|claude)" >&2
    exit 2
    ;;
esac

# The agent must not move HEAD. If it committed/reset, the working-tree guard
# below would see a clean tree and miss the change (and later steps would run
# whatever the agent left behind), so fail hard here.
HEAD_AFTER="$(git rev-parse HEAD 2>/dev/null || true)"
if [ "$HEAD_AFTER" != "$HEAD_BEFORE" ]; then
  echo "ERROR: agent moved HEAD ($HEAD_BEFORE -> $HEAD_AFTER); refusing to continue." >&2
  echo "::error title=docs-sync guard::the docs agent moved HEAD; refusing to continue (see the step log for the before/after shas)."
  exit 1
fi

# Guard: the agent must touch documentation surfaces only. Inspect the WHOLE
# working tree (not just what we stage), so a stray or injected edit — e.g. to
# the tools/docs-sync/*.sh scripts that later CI steps execute — can't slip
# through. The run's own generated artifacts are allowed. Derive touched paths
# from porcelain-free plumbing (name-only diff + untracked listing) so renames
# and paths with spaces don't trip a false positive. The agent has raw git
# shell access, so it could `git add` a stray file itself — diff against HEAD
# (not just the index) so a staged-but-uncommitted edit is still caught.
STRAY="$( { git diff --name-only HEAD; git ls-files --others --exclude-standard; } \
  | sort -u \
  | grep -Ev '^(AGENTS\.md|CLAUDE\.md|\.docs-sync\.json|docs-agent-prompt\.txt|docs-agent\.log|docs-scope\.txt|docs-freshness\.json|docs/.*)$' || true)"
if [ -n "$STRAY" ]; then
  echo "ERROR: agent modified files outside the documentation surfaces; aborting before any later step can run them:" >&2
  printf '  %s\n' "$STRAY" >&2
  STRAY_ESCAPED="$(printf '%s' "$STRAY" | tr '\012' ' ')"
  STRAY_ESCAPED="${STRAY_ESCAPED//'%'/'%25'}"
  STRAY_ESCAPED="${STRAY_ESCAPED//$'\r'/'%0D'}"
  echo "::error title=docs-sync guard::agent modified files outside the documentation surfaces: $STRAY_ESCAPED"
  exit 1
fi

# Stage only documentation surfaces (defense in depth against stray edits).
# Only pass paths that exist: `git add` aborts the whole command on a pathspec
# that matches nothing (e.g. `doc` in a repo whose docs root is `Docs`), which
# would silently stage nothing.
DOC_PATHS=()
for p in AGENTS.md CLAUDE.md docs .docs-sync.json; do
  [ -e "$p" ] && DOC_PATHS+=("$p")
done
if [ ${#DOC_PATHS[@]} -gt 0 ]; then
  git add -A "${DOC_PATHS[@]}"
fi

if git diff --cached --quiet; then
  echo "No documentation changes produced."
else
  echo "Documentation changes staged:"
  git diff --cached --stat
fi
