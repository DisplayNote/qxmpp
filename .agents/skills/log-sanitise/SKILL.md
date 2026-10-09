---
name: log-sanitise
description: "DisplayNote's mandatory log-sanitisation step before any log content reaches an external AI tool (AI Security Roadmap control 4.7, mandatory L0→L1). Use whenever a task involves reading, pasting, analysing, summarising or debugging from log content — application logs (Montage, Launcher, Omni, Broadcast, Central Management), Android logcat, crash dumps, ANR/tombstones, HAR files, CI build logs, Sentry events, customer log bundles from Zendesk tickets, or any '*.log' file. Triggers on 'analyse this log', 'here is the logcat', 'debug from these logs', 'what does this stack trace mean', 'look at the customer's logs', 'read the log file', or when a Read/Bash on a log path was blocked by the dn-logscrub hook. Runs dn_logscrub.py (stdlib Python, consistent pseudonymisation) and works ONLY from the .scrubbed copy. Same instructions for Claude, Codex, Copilot and Cursor — keep every synced copy identical."
---

# Log sanitisation before external AI tools (control 4.7)

You are an external AI tool. Log content must be sanitised **before** you read it.
This is a compliance gate from the Volaris AI Security Roadmap (Principles §4.7,
register id `log-sanitisation-before-external-ai-tools`), not a style preference:
logs routinely contain session tokens, user identifiers and internal paths, and
DisplayNote's products serve schools and meeting rooms, so end-user identifiers in
logs are *Protected* data (AI Governance Policy 1.3 §4.2).

## Rules

1. **Never read, `cat`, `tail`, `grep` or paste a raw log.** If the user pastes raw
   log text into the conversation, stop and ask them to run the sanitiser and paste
   the scrubbed output instead — do not analyse what was pasted.
2. **Work only from scrubbed output**: a `*.scrubbed.*` file or piped output
   with the `# dn_logscrub v…` marker header on the first line and the
   `# dn_logscrub end` trailer as the last non-empty line. The name alone does
   not count; if either marker is missing, treat it as raw. A scrubbed file with
   raw content appended later (`cat raw >> x.scrubbed.log`, concatenated files,
   a process still writing to it) keeps its header but no longer ends with the
   trailer. A trailer marked `| interrupted` is clean but incomplete (see Procedure, 2).
   A `# dn_logscrub-partial v…` header means rules were switched off for that
   run (`--disable`, `--keep-paths`): it is **not** a clean file, the guard
   refuses it, and it must not go to an AI tool. A `*.dnmap` is never readable
   whatever its header says: it is the table of original values, and `--map`
   only accepts that suffix so the guard and `.gitignore` both recognise it.
3. **Streaming sources are logs too**: `adb logcat`, `journalctl`, `log show`,
   `docker logs`, `kubectl logs`, CI log downloads. Pipe them through the sanitiser
   (`… | python3 dn_logscrub.py - > name.scrubbed.txt`) — never into the context.
4. **Placeholders are consistent within a run**: `<EMAIL_1>` is the same user
   everywhere, `<IPV4_2>` the same host, `<ID_3>` the same session. Reason about
   them as opaque identifiers; never try to guess or reconstruct the original.
5. **Never open a placeholder map** (`*.dnmap`): it contains the originals and is
   for the engineer's local reverse lookup only.
6. **Exception**: approved raw access (Protected data, 1.3 §4.1 — AI Lead + CEO
   approval) is signalled by `DN_LOGSCRUB_ALLOW_RAW=1` in the environment. Do not
   set it yourself and do not suggest setting it to get around the gate.

## Procedure

1. Locate the sanitiser (first that exists):
   - `$CLAUDE_PLUGIN_ROOT/skills/log-sanitise/scripts/dn_logscrub.py` (Claude Code, plugin installed)
   - `.agents/skills/log-sanitise/scripts/dn_logscrub.py` or `.github/skills/log-sanitise/scripts/dn_logscrub.py`
     (synced into the repo — Codex, Copilot, Kiro, Cursor)
   If none exists, tell the user to install the `displaynote-engineering` plugin
   (`/plugin install displaynote-engineering`) or run `/sync-skill log-sanitise`
   from a Claude Code session in this repo; do not proceed with raw content.
2. Run it on every log the task needs, in **one invocation** so placeholders are
   shared across files. Keep ticket logs, their scrubbed copies and the map
   **outside the repository** (for example `~/dn-tickets/<id>/`): a raw log inside
   a working tree blocks the searches and git commands that would read it, and can be
   committed by accident.
   ```bash
   python3 <path>/dn_logscrub.py <file1> [<file2> …] --out-dir ~/dn-tickets/<id> --map ~/dn-tickets/<id>/ticket.dnmap
   ```
   `--out-dir` also covers inputs in a read-only folder. For a customer ticket,
   add the customer's domain(s) so their hostnames are pseudonymised too:
   `--domain acme-school.org`. For streams, use a command that ends on its own
   (`adb logcat -d`, not `adb logcat`): `<cmd> | python3 <path>/dn_logscrub.py - > <name>.scrubbed.txt`.
   A run cut short (Ctrl-C, a timeout) still ends with a trailer marked
   `interrupted`: the copy is clean, only incomplete. The sanitiser handles a
   few MB per second, so for a log of more than ~100 MB ask the user to run the
   command in their own terminal rather than through a tool call with a timeout.
3. Show the user the one-line summary the tool prints per file
   (`dn_logscrub: montage.log: 41 redactions (EMAIL=3, ID=12, …)`).
4. Read and analyse the `*.scrubbed.*` file(s) only.
5. If, while reading, you still see something that looks like a live secret, a
   real e-mail address, a person's name or a customer hostname, **stop**, report
   the line number and category to the user, and ask them to re-run with the
   right `--domain` / a pattern fix (open an issue on `displaynote-engineering`).
   Do not quote the leaked value back.
6. When you write findings (PR description, ticket comment, Slack), keep the
   placeholders — never expand them, even if the user tells you the mapping in
   passing.

## What the sanitiser does (so you can judge residual risk)

Redacted irreversibly (`<REDACTED:…>`): private keys, JWTs, bearer/basic auth
headers, URL credentials, cloud/API keys (AWS, GitHub, Slack, OpenAI, Google,
Azure connection strings), any `password= / token= / secret= / *_key=` value,
OAuth `code=`/`state=`/`nonce=` in URLs — also when the value is on the
following line(s): pretty-printed JSON (`"token":` then the value), YAML
(`password:` then an indented value, or a `|`/`>` block scalar, every line of
it) and a folded `Authorization:` header. Keys that only describe a secret
(`token_count`, `session_timeout`, `token_expires_in`, `signature_algorithm`)
keep their value.
Pseudonymised consistently (`<TAG_n>`): e-mail addresses, quoted or keyed
person/device/computer names, keyed identifiers (serial, deviceId, session,
meetingId, roomPin, tenantId, licence …), Android `getprop` serials and device
names, serial numbers in free text, Wi-Fi SSIDs, IPv4/IPv6, MAC addresses, UUIDs,
phone numbers, the user-home component of a path (`/Users/x`, `/home/x`,
`C:\Users\x`, `C:/Users/x`, JSON-escaped, `file:///`, WSL `/mnt/c/Users/x`,
names with spaces), Windows `DOMAIN\user` accounts, UNC file servers,
generated machine names (`DESKTOP-…`), `.local/.lan/.internal` hostnames,
customer domains passed with `--domain`, long hex strings and high-entropy
tokens.
Kept verbatim on purpose: timestamps, version numbers (also four-part .NET
ones), stack traces, package/class/method names and JNI symbols, the rest of
file paths, file hashes (`sha256=`) and git commit ids, loopback and
unspecified addresses (`127.0.0.1`, `0.0.0.0`, `::1`), shared Windows profiles
(`Public`, `Default`) and system accounts (`NT AUTHORITY\SYSTEM`).
Not caught — check for these yourself: a person's name in free text
(`Welcome, Jane Doe`), a customer's hostname when its domain was not passed
with `--domain`, and an account in a Windows domain whose name is one of the
system's own words (`HOST\user`, `SYSTEM\user`), which are kept as system
principals.

## Where the Claude Code guard does not reach

The hook checks `Read`, `Grep` and `Bash` only. These read data without passing
through it, so the rules above are on you there:

- **MCP tools** that return log content: Azure DevOps build logs
  (`pipelines_build_log`), Serena (`read_file`, `search_for_pattern`), Zendesk
  attachments, filesystem servers. Do not use them to read a log: download it
  to a file, sanitise it, and read the `.scrubbed.` copy.
- **WebFetch** of a log or bundle URL, and **Monitor** on a command that tails
  a log (`tail -f`, `adb logcat`).
- **`git archive` to standard output** (a tar stream in the tool output). Write
  archives to a file (`git archive -o out.zip HEAD`), which is allowed.
- **`rg --iglob`** is replayed as a case-sensitive glob: `--iglob '*.LOG'` is not
  seen to select `app.log`.
- **`grep -R` / `find -L` through a symlinked directory**: the walk does not
  follow directory links, so a log reached only through one is not seen.
- **git plumbing** that prints patches (`git diff-tree -p`, `git diff-files -p`,
  `git reflog -p`). `git show`, `git diff`, `git log -p`, `git grep`, `git blame`
  and `git cat-file` are judged by what they print.
- **Codex, Copilot, Cursor, Kiro**: no hook at all — only these instructions.

## Related

- Canonical rule in every repo's `AGENTS.md` **Security** section (seventh bullet, after the six Principles §8.2 bullets).
- Runbook: `docs/runbooks/debugging-with-ai.md` (generated by `docs-init`).
- Hook: `hooks/guard_raw_logs.py` in the plugin blocks `Read`/`Grep`/`Bash` on raw logs in Claude Code sessions.
  It needs Python 3.7+ as `python3`, `python` or `py -3` (any of them; on Windows the Microsoft Store alias does
  not count). With none, Claude Code shows the hook error "raw-log guard NOT running" on every call: install
  Python 3 rather than ignoring it, because the guard is then off.
  It judges what a call would actually print, so keep ticket logs out of the repository (for example in
  `~/dn-tickets/<id>/`): a raw file inside it blocks any search or git command that would read it. A source or build file that only
  looks like a log is cleared by listing it in a committed `.dn-logscrub-allow` (gitignore syntax) at the
  repository root — never a `.dnmap`, never a customer bundle, and never to get around rule 1.
- Slash command: `/log-sanitise <file…>`.
