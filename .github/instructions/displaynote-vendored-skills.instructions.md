---
applyTo: ".agents/skills/code-review/**,.github/skills/code-review/**,.agents/skills/log-sanitise/**,.github/skills/log-sanitise/**"
---

# Vendored DisplayNote skills

The skill directories this file applies to (see `applyTo` above, written by
`/sync-skill` for the skills it synced) are copies of skills maintained in
DisplayNote's `displaynote-engineering` plugin. They are vendored code: this
repository does not own them, and the next sync overwrites any change made to
them here. Other skills under `.agents/skills/` or `.github/skills/` belong to
this repository and are reviewed like any other code.

When reviewing a pull request that touches these paths:

- Do not review the logic, style, performance or tests of these files, and do
  not suggest edits to them. A real defect belongs in the plugin repository,
  where it is fixed once for every repository that syncs the skill.
- If a pull request changes these files by hand instead of replacing them
  with a sync, say so once: the change will be lost on the next sync and
  should go upstream instead.
- If the same pull request mixes a skill sync with unrelated changes, suggest
  splitting them, so the sync can be reviewed as a sync.

These files are still instructions for agents working in this repository:
reading and following a skill's `SKILL.md` is unaffected by the above.

Never quote values from a `*.dnmap` file, from a raw log or from a log fixture
in a review comment: maps hold original identifiers, and logs are sanitised
with the `log-sanitise` skill before any AI tool reads them.
