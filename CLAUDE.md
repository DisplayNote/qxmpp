# CLAUDE.md — qxmpp (DisplayNote fork, `1.6` line)

@AGENTS.md

`AGENTS.md` is the source of truth (including the mandatory `## Security` section).
This file only lists the rules that hurt most when ignored.

## DO

- Work on, and branch from, `1.6` — DisplayNote's packaged line (`conanfile.py`,
  `ci/azure-pipelines.yml`). `master` is plain upstream QXmpp.
- Keep the DisplayNote reconnection and stream-resumption changes
  (`src/client/QXmppClient.cpp`, `src/client/QXmppOutgoingClient.cpp`) when merging upstream
  fixes; reference the `AB#` work item in commits.
- Follow the existing class pattern: `QXmpp<Name>` + `_p.h` private header, `QXMPP_EXPORT`,
  Doxygen with `\since QXmpp 1.X`, SPDX header on every new file.
- Use `QStringLiteral`, `Q_EMIT`/`Q_SIGNALS`/`Q_SLOTS`, `std::as_const` — the build defines
  `QT_NO_KEYWORDS`, `QT_NO_FOREACH` and `QT_NO_CAST_TO_ASCII`.
- Log through `QXmppLoggable` (`debug()`, `info()`, `warning()`), not `qDebug`/`qWarning`.
- Add a Qt Test under `tests/<name>/tst_<name>.cpp` and register it with `add_simple_test`.
- Format edited files with `clang-format -i` (repo `.clang-format`).
- Sanitise any QXmpp or host log before reading it: `/log-sanitise <file>`
  ([docs/runbooks/debugging-with-ai.md](docs/runbooks/debugging-with-ai.md)).

## DON'T

- Don't log credentials, tokens, JIDs, message bodies or full stanzas at new call sites;
  `logSent()`/`logReceived()` already carry the raw XML stream.
- Don't change `cmakeCommonArgs`, stage `platform` paths or `conanfile.py` `_source_folder()`
  independently — the three must agree or the deploy fails (see
  [docs/runbooks/release.md](docs/runbooks/release.md)).
- Don't edit `doc/` (upstream Doxygen) for DisplayNote documentation; use `docs/`.
- Don't run `utils/setup-hooks.sh` — it overwrites `.git/hooks/pre-commit` (the secret-scan hook).
- Don't commit `QXMPP_TESTS_JID` / `QXMPP_TESTS_PASSWORD` values or any log file.
- Don't add new third-party dependencies without flagging them (see `AGENTS.md#security`).

## Useful commands

```bash
cmake -B build -DBUILD_TESTS=ON -DBUILD_EXAMPLES=OFF
cmake --build build
cd build && ctest --output-on-failure -R tst_qxmppclient
```

Slash commands from the `displaynote-engineering` plugin that apply here:
`/log-sanitise`, `/secret-scan-setup`, `/docs-update`.

## Pointers

- Architecture and data flows: [docs/architecture.md](docs/architecture.md)
- Modules: [docs/modules/](docs/modules/)
- Runbooks: [docs/runbooks/](docs/runbooks/)
- Glossary: [docs/glossary.md](docs/glossary.md)
