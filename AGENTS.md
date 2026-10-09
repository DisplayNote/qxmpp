# AGENTS.md — qxmpp (DisplayNote fork, `1.6` line)

## Project snapshot

- QXmpp: cross-platform C++/Qt XMPP client and server library (upstream
  [qxmpp-project/qxmpp](https://github.com/qxmpp-project/qxmpp), LGPL-2.1-or-later).
  DisplayNote keeps this fork at `github.com/DisplayNote/qxmpp`, builds it in Azure Pipelines and
  publishes it as the Conan package `qxmpp` (user/channel `@dn/…`, see
  [docs/runbooks/release.md](docs/runbooks/release.md)); Montage links it for XMPP signalling.
- Stack on `1.6`: C++17, CMake ≥ 3.16, Qt 5.15 or Qt 6 (`Core`, `Network`, `Xml`); DisplayNote
  builds against Qt 6.8.8 (`ci/azure-pipelines.yml`). Optional QCA, libomemo-c (OMEMO) and
  GStreamer (Jingle calls), all off in DisplayNote builds. `project(qxmpp VERSION 1.6.1)` in
  `CMakeLists.txt`; DisplayNote release tags `v1.6.2`–`v1.6.5`.
- **`1.6` is the DisplayNote branch.** It is upstream 1.6.1 plus DisplayNote commits
  (`git log --oneline origin/master..origin/1.6`): `conanfile.py`, `ci/azure-pipelines.yml`
  (`DisplayNote/qt-conan-ci` templates), the DisplayNote "Building" section of `README.md`,
  `BUILD_UNVERSIONED_LIBRARY` and a default install prefix in `CMakeLists.txt`, Win64 exports
  in `src/base/QXmppUtils.h`, randomised reconnection delays in `src/client/QXmppClient.cpp`
  (AB#115566, AB#126881) and stream-resumption workarounds in
  `src/client/QXmppOutgoingClient.cpp` (AB#115566). `master` is plain upstream; DisplayNote PRs
  target `1.6`.

## Security

- NEVER suggest hardcoded credentials, API keys, or connection strings
- NEVER generate code that logs PII or sensitive data
- Flag any code that introduces new external dependencies
- Prefer established authentication patterns (OAuth2, JWT) over custom implementations
- Do not generate SQL without parameterised queries
- Flag any configuration changes that affect network exposure or access controls
- NEVER read raw log files or paste log content into a prompt — sanitise with `dn_logscrub` first (`/log-sanitise <file>`) and work only from the `.scrubbed` copy (AI Security Roadmap 4.7)

Repo-specific:

- `QXmppLogger` `SENT`/`RECEIVED` entries are the raw XML stream, including SASL payloads
  (base64, not encrypted — PLAIN carries the password), the password of legacy `jabber:iq:auth`
  and `jabber:iq:register` stanzas, OAuth access tokens used as SASL passwords, JIDs and message
  bodies. Treat any QXmpp log as credential-bearing; see
  [docs/runbooks/debugging-with-ai.md](docs/runbooks/debugging-with-ai.md).
- Integration tests read real account credentials from `QXMPP_TESTS_JID` /
  `QXMPP_TESTS_PASSWORD` (`tests/IntegrationTesting.h`); never commit them.

## Repository map

```text
src/            library sources (one library target, QXmppQt5 / QXmppQt6)
  base/         stanzas/IQs, XML (de)serialisation, QXmppStream, SASL, STUN/ICE, logger, tasks
  client/       QXmppClient, QXmppOutgoingClient, configuration, client extensions (managers)
  server/       QXmppServer and server-side streams (built into the same library)
  omemo/        optional OMEMO module, separate target QXmppOmemoQt5/6 (BUILD_OMEMO)
tests/          Qt Test unit tests, one folder per test (tst_<name>.cpp); TestClient.h, util.h
  travis/       upstream CI build scripts (used by .github/workflows/tests.yml)
examples/       small upstream example programs (example_0_connected … example_9_vCard)
ci/             DisplayNote Azure Pipelines definition (azure-pipelines.yml)
conanfile.py    DisplayNote Conan 1.x recipe that packages the CI-staged install tree
doc/            upstream Doxygen sources and XEP/DOAP metadata (upstream material — do not edit)
docs/           DisplayNote AI-agent docs (architecture, modules, runbooks, glossary)
cmake/          Find modules (GStreamer, GLib) and legacy QXmpp package config
utils/          upstream git-hook helper (clang-format pre-commit) and logo rendering
.github/        upstream workflows and PR template; DisplayNote-vendored skills (skills/) and
                Copilot instructions (instructions/)
.agents/        DisplayNote-vendored agent skills (log-sanitise), synced from displaynote-engineering
```

## Run / build / test / lint

Full detail in [docs/runbooks/local-setup.md](docs/runbooks/local-setup.md),
[docs/runbooks/testing.md](docs/runbooks/testing.md) and, for the Conan package,
[docs/runbooks/release.md](docs/runbooks/release.md). Short version:

```bash
cmake -B build -DBUILD_TESTS=ON -DBUILD_EXAMPLES=OFF
cmake --build build
cd build && ctest --output-on-failure
```

```bash
# format edited files (repo ships .clang-format)
clang-format -i src/<edited-files> tests/<edited-files>
```

CMake options: `CMakeLists.txt` (the `README.md` "Building (original)" table is upstream's and
says `BUILD_DOCUMENTATION` defaults to `ON`; `CMakeLists.txt` defaults it to `OFF`). DisplayNote
additions: `BUILD_UNVERSIONED_LIBRARY` (CI sets it `ON`) and the default
`CMAKE_INSTALL_PREFIX` of `install/<CMAKE_SYSTEM_NAME>/<CMAKE_BUILD_TYPE>`.

## Architecture overview

Summary only; diagrams and flows live in [docs/architecture.md](docs/architecture.md).

- **base** (`src/base`) — data model and protocol plumbing shared by client and server:
  stanza/IQ classes with `parse()`/`toXml()`, `QXmppStream` (socket, XML framing, raw logging,
  XEP-0198 `QXmppStreamManager`), SASL clients/servers (`QXmppSasl.cpp`), STUN/TURN/ICE
  (`QXmppStun.cpp`), `QXmppLogger`, `QXmppTask`/`QXmppPromise`. [docs/modules/base.md](docs/modules/base.md)
- **client** (`src/client`) — `QXmppClient` (public facade, reconnection), `QXmppOutgoingClient`
  (DNS SRV, TLS, SASL / non-SASL auth, bind, stream management), `QXmppConfiguration`, and the
  `QXmppClientExtension` managers (roster, vCard, MUC, PubSub, MAM, HTTP upload, calls…).
  [docs/modules/client.md](docs/modules/client.md)
- **server** (`src/server`) — `QXmppServer`, incoming client/server streams, dialback,
  password checker. [docs/modules/server.md](docs/modules/server.md)
- **omemo** (`src/omemo`) — `QXmppOmemoManager` end-to-end encryption, optional.
  [docs/modules/omemo.md](docs/modules/omemo.md)

## Coding conventions (observed)

- Class names `QXmpp<Thing>`; private implementation in `QXmpp<Thing>_p.h` / `<Thing>Private`
  (d-pointer); public symbols marked `QXMPP_EXPORT`; new API documented with Doxygen and
  `\since QXmpp 1.X` (`.github/pull_request_template.md`).
- Compile definitions (`CMakeLists.txt`): `QT_NO_CAST_TO_ASCII`, `QURL_NO_CAST_FROM_STRING`,
  `QT_NO_KEYWORDS`, `QT_NO_FOREACH`, `QT_DISABLE_DEPRECATED_BEFORE=0x050F00`. Use `Q_EMIT`,
  `Q_SIGNALS`, `Q_SLOTS`, `std::as_const`; string literals are `QStringLiteral(...)` in most
  newer code (implicit `const char *` → `QString` still compiles on this branch).
- Async APIs return `QXmppTask<T>` (`src/base/QXmppTask.h`) fulfilled by `QXmppPromise<T>`.
- Logging: classes derive from `QXmppLoggable` and call `debug()`/`info()`/`warning()`/
  `logSent()`/`logReceived()`, which reach the client's `QXmppLogger`. `src/` also has a few
  plain `qWarning`/`qDebug` calls (including the two DisplayNote reconnection `qDebug` lines);
  don't add new ones, and never log credentials or stanza content at new call sites.
- Every file carries SPDX copyright/licence headers (REUSE, see `CONTRIBUTING.md`).
- Formatting: `.clang-format`; `utils/setup-hooks.sh` installs a `git-clang-format` pre-commit
  hook (see Gotchas before running it).
- Commits: upstream style is short, capitalised, imperative (`OmemoManager: Fix …`). DisplayNote
  commits on `1.6` mostly use `AB#<id> <change>` or `AB#<id> CI: <change>`, merged through GitHub PRs
  into `1.6`.

## Patterns to follow / avoid

- Follow: a payload class with `parseElementFromChild()` / `toXmlElementFromChild()`
  (`src/base/QXmppVersionIq.cpp`); a manager dispatching IQs with
  `QXmpp::handleIqRequests<…>()` (`src/client/QXmppVersionManager.cpp`).
- Avoid: commenting code out instead of making it conditional (as the DisplayNote
  resumption workaround in `QXmppOutgoingClient::connectToHost()` does) — new DisplayNote
  behaviour changes should carry an `AB#` reference and a reason in the code comment.
- Avoid: logging through `qDebug()` with stanza content, JIDs or credentials; it bypasses the
  host's `QXmppLogger` configuration and lands in the host's own logs.

## Where to add X

| Adding… | Go to | Pattern to copy |
|---|---|---|
| A new stanza/IQ payload | `src/base/QXmpp<Name>Iq.{h,cpp}` + `src/CMakeLists.txt` (`INSTALL_HEADER_FILES`, `SOURCE_FILES`) | `src/base/QXmppVersionIq.cpp` |
| A client feature / XEP manager | `src/client/QXmpp<Name>Manager.{h,cpp}` subclassing `QXmppClientExtension` | `src/client/QXmppVersionManager.cpp`; IQ dispatch via `src/client/QXmppIqHandling.h` |
| Reconnection / login behaviour | `src/client/QXmppClient.cpp` (`getNextReconnectTime()`, `_q_stream*()`), `src/client/QXmppOutgoingClient.cpp` (`handleStanza()`) | existing DisplayNote changes (`git log -p 3fa204ec..origin/1.6 -- src/client`) |
| A supported-XEP entry | `doc/doap.xml` (upstream PR checklist) | existing `<implements>` entries |
| A unit test | `tests/<name>/tst_<name>.cpp` + `add_simple_test(<name>)` in `tests/CMakeLists.txt` | `tests/qxmppversionmanager/` (uses `TestClient.h`) |
| A test needing private symbols | same, inside `if(BUILD_INTERNAL_TESTS)` | `tests/qxmppsasl/` |
| A CMake option used by DisplayNote CI | `CMakeLists.txt` + `cmakeCommonArgs` in `ci/azure-pipelines.yml` | `BUILD_UNVERSIONED_LIBRARY` |
| A new packaged platform | a stage in `ci/azure-pipelines.yml`, its profile in `conanProfiles`, the staging path in `conanfile.py` `_source_folder()` | the `macos_arm64` stage |
| A changelog entry | `CHANGELOG.md` top section (upstream only; DisplayNote changes are not listed there) | existing bullets |

## Gotchas

- Work on `1.6`; `master` is plain upstream (`project(qxmpp VERSION 1.8.0)`) and is not what Montage gets.
- `utils/setup-hooks.sh` copies `utils/pre-commit.sh` over `.git/hooks/pre-commit`, replacing
  the DisplayNote secret-scan hook installed by `/secret-scan-setup`. Do not run it in a clone
  that has the secret-scan hook, or chain both hooks by hand.
- `QXmppLogger::getLogger()` is a process-wide singleton; every `QXmppClient` uses it by default
  (`src/client/QXmppClient.cpp:259`). Changing its logging type affects all clients in the process.
- `FileLogging` writes to a relative path (`QXmppClientLog.log`) in the process working directory
  unless `setLogFilePath()` is called (`src/base/QXmppLogger.cpp:99`).
- DisplayNote stream-resumption workarounds (`src/client/QXmppOutgoingClient.cpp`): the
  resume-host connection is commented out (lines 223–229, so a resumed session reconnects to the
  configured host or SRV result), and `sessionStarted` is forced `true` after stream management
  is enabled, resumed or fails (lines 758–759, 771–772, 797–798), which makes `isConnected()`
  (line 282) report `true`. Keep both when porting upstream fixes.
- Reconnection (`src/client/QXmppClient.cpp`): delays are randomised (`getNextReconnectTime()`,
  lines 69–98), a socket error and a disconnect while presence is `Available` both schedule a
  reconnect (lines 963–974, 989–992), and `disconnectFromServer()` sets presence `Unavailable`,
  so a logged-out client does not reconnect (AB#126881).
- The default `CMAKE_INSTALL_PREFIX` (`install/<CMAKE_SYSTEM_NAME>/<CMAKE_BUILD_TYPE>`) is not the
  layout `conanfile.py` reads (`Macos/<arch>/<BuildType>`, `Android/<arch>/<BuildType>`,
  `<os>/<BuildType>`, relative to where `conan export-pkg` runs); pass `--prefix` explicitly as
  `README.md` does.
- `qxmppsasl` and other internal tests only build with `BUILD_INTERNAL_TESTS=ON`;
  `qxmppcallmanager` only with `WITH_GSTREAMER=ON`. DisplayNote CI builds with `BUILD_TESTS=OFF`.
- The `doc/` folder is upstream Doxygen input; DisplayNote docs go under `docs/`.

## Glossary

See [docs/glossary.md](docs/glossary.md).

## External systems

| System | Role | Where configured / mocked |
|---|---|---|
| XMPP server | Peer of every client connection (Montage's signalling server in production) | `QXmppConfiguration` (`src/client/QXmppConfiguration.h`); unit tests use `TestClient` (`tests/TestClient.h`), which captures sent packets and injects inbound XML; integration tests need `QXMPP_TESTS_*` env vars |
| STUN/TURN servers | ICE for Jingle calls / file transfer | `QXmppCallManager::setStunServers`/`setTurnServer`; `tests/qxmppiceconnection/` |
| QCA, libomemo-c | Crypto for OMEMO and encrypted file sharing | `WITH_QCA`, `BUILD_OMEMO` in `CMakeLists.txt` |
| GStreamer | Audio/video for Jingle calls | `WITH_GSTREAMER`, `cmake/modules/FindGStreamer.cmake` |
| Azure Pipelines + `DisplayNote/qt-conan-ci` 2.4.0 | DisplayNote CI: builds every platform and deploys the Conan package | `ci/azure-pipelines.yml`, `conanfile.py`; [docs/runbooks/release.md](docs/runbooks/release.md) |
| Conan (1.x) | Package format consumed by Montage | `conanfile.py` (`from conans import ConanFile`) |
| GitHub Actions | Upstream workflows (`.github/workflows/tests.yml`, `push-docs.yml`); not registered on `DisplayNote/qxmpp` — only Copilot code review runs there | — |
