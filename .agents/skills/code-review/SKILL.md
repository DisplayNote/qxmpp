---
name: code-review
description: DisplayNote's performance-first pre-PR code review for production, performance-critical environments — covers Android/embedded (API 26+), native C/C++, AI/LLM inference, networking & security, logging & diagnostics. Includes a mandatory SECURITY REVIEW pass that explicitly checks every diff for injection vulnerabilities, hardcoded secrets, insecure direct object references, and CVE-affected dependencies — any finding is Critical, and every review must end with a Security line reporting the four checks. Triggers when the user asks to "review my PR", "code review", "pre-PR review", "review this branch", or similar. Produces a prioritized findings list (Critical / High / Medium / Low) with concrete fixes and a final READY / NEEDS FIXES / BLOCKING verdict. Same instructions used by Claude, Codex and Copilot — keep all three copies of this skill in sync.
---

Do a pre-PR review of all changes on the current branch that would be included in a pull request.

Steps:
1. Detect all changes on the current branch that would be included in a pull request.
2. For each changed file, analyze the diff and identify any issues or improvements.
3. Output a prioritized list of findings: **Critical** (bugs, security, data loss), **High** (performance, correctness), **Medium** (design, maintainability), **Low** (style, minor). For each finding include: file, line range, issue, and a concrete fix.
4. Close the review with these two lines, in this order and nothing after them:
   1. A **Verdict**: READY / NEEDS FIXES / BLOCKING, and a one-line summary.
   2. A **Security:** line stating the result of the four mandatory security checks (injection, hardcoded secrets, insecure direct object references, CVE-affected dependencies), even when there are no findings — e.g. `Security: checked injection / hardcoded secrets / IDOR / CVE dependencies — no findings in this diff`. This is the last line of the review; a review without it is incomplete.

Apply these review principles:

## CORE PRINCIPLES

-   Assume production, performance-critical environments by default.
-   Optimize for latency, memory efficiency, and determinism.
-   Avoid unnecessary abstractions.
-   No speculative refactors.
-   No additional dependencies unless explicitly justified with
    measurable benefit.
-   All code must be compatible with stable toolchains.

------------------------------------------------------------------------

## PERFORMANCE REQUIREMENTS

-   Always consider time complexity (Big-O) for non-trivial logic.
-   Minimize heap allocations in hot paths.
-   Avoid blocking operations on UI, media, or inference threads.
-   Explicitly identify performance bottlenecks when relevant.
-   Prefer stack allocation where safe and appropriate.
-   Avoid hidden copies of large buffers.

------------------------------------------------------------------------

## ANDROID & EMBEDDED SYSTEMS

-   Assume Android API 26+ unless specified.
-   Highlight ANR risks explicitly.
-   Avoid reflection in performance-sensitive paths.
-   Be explicit about threading models.
-   Assume constrained CPU, memory, and thermal budgets.
-   JNI boundaries must be minimal and efficient.
-   No business logic inside JNI layers.

------------------------------------------------------------------------

## NATIVE (C / C++)

-   Explicit ownership semantics required.
-   No implicit allocations.
-   Avoid dynamic memory inside tight loops.
-   Prefer deterministic behavior over convenience APIs.
-   Design token streaming systems for incremental callbacks and
    cancellation.
-   Always consider thread safety.

------------------------------------------------------------------------

## AI / LLM INFERENCE

-   Prioritize deterministic sampling for diagnostics.
-   Separate prompt construction from inference execution.
-   Consider latency budgets and memory footprint explicitly.
-   Assume local-first architectures unless stated otherwise.
-   Avoid unnecessary token generation.
-   Always account for concurrency and cancellation support.

------------------------------------------------------------------------

## SECURITY REVIEW (mandatory)

Explicitly check every diff for these four items; any finding is
**Critical**:

-   Injection (SQL/command/path/format-string): untrusted input reaching
    an interpreter, shell, query, file path, or intent without
    validation/parameterisation.
-   Hardcoded secrets: keys, tokens, passwords, private keys, or
    connection strings in code, resources, build files, or logs; flag
    high-entropy literals.
-   Insecure direct object references: acting on a caller-supplied ID
    without verifying the caller is authorised for that object.
-   CVE-affected dependencies: check every new or version-changed
    dependency against known CVEs; flag unjustified additions.

Every review must end with a "Security:" line stating the result of
these four checks, even when there are no findings.

------------------------------------------------------------------------

## NETWORKING & SECURITY

-   Default to TLS 1.2+.
-   Never disable certificate validation.
-   Avoid insecure fallbacks.
-   Minimize handshake overhead when discussing embedded SSL.
-   Explicitly mention performance trade-offs in encryption choices.

------------------------------------------------------------------------

## LOGGING & DIAGNOSTICS

-   No verbose logging in performance paths.
-   No PII in logs.
-   Prefer structured logging.
-   Failure simulations must be deterministic and reproducible.

------------------------------------------------------------------------

## RESPONSE REQUIREMENTS

Responses must:

1.  Provide a direct, technically precise answer.
2.  Include high-level reasoning focused on performance implications.
3.  Present alternative approaches only if they differ meaningfully in
    performance profile.
4.  Provide concrete implementation guidance.

Avoid: - Tutorial-level explanations. - Marketing language. -
Over-engineered abstractions. - Unnecessary defensive coding unless
justified.

Performance, determinism, and architectural clarity take priority over
convenience.

<!--
CANONICAL SOURCE NOTE
This file is the canonical version of the code-review skill, maintained
inside the `displaynote-engineering` plugin. Claude Code users get it
automatically when the plugin is installed.

For Codex, GitHub Copilot, and other AI agents that read skill files
directly from a repository's working tree (typically under
`.agents/skills/<name>/SKILL.md` and `.github/skills/<name>/SKILL.md`),
do NOT hand-copy this file. Instead, run the plugin's `/sync-skill`
slash command from within the target repository:

    /sync-skill code-review

That command copies the canonical SKILL.md into both `.agents/skills/`
and `.github/skills/`, so every agent in DisplayNote's toolset
(Claude Code, Codex, Copilot, Kiro, etc.) sees the same review
instructions.

Never edit the per-repo copies by hand — they will be overwritten the
next time `/sync-skill` runs. All changes must land here, in the
plugin, and then propagate via the sync command.
-->
