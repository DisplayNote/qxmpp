# Module: omemo (`src/omemo`)

## Purpose and boundaries

Optional OMEMO end-to-end encryption, built as a separate library
(`QXmppOmemoQt5` / `QXmppOmemoQt6`) only with `-DBUILD_OMEMO=ON`, which also requires QCA
(`WITH_QCA`) and `libomemo-c` via pkg-config (`CMakeLists.txt`). Upstream usage notes:
[src/omemo/README.md](../../src/omemo/README.md). DisplayNote CI does not set `BUILD_OMEMO`, so
the Conan package does not contain it; the only DisplayNote change here is the
`BUILD_UNVERSIONED_LIBRARY` handling in `src/omemo/CMakeLists.txt`.

## Public API

- `QXmppOmemoManager` (`QXmppOmemoManager.h`): a `QXmppClientExtension` +
  `QXmppE2eeExtension`; `load()`, `setUp()`, `setSecurityPolicy()`, device/trust signals.
- `QXmppOmemoStorage` (abstract) and `QXmppOmemoMemoryStorage` (in-memory implementation).

## Dependencies

Upstream: the main QXmpp library, QCA, libomemo-c. Downstream: applications that enable E2EE.

## Testing in isolation

`tests/qxmppomemomanager/` (its cases are integration tests: they log in with the
`QXMPP_TESTS_*` account), `tests/qxmppomemomemorystorage/`, and `tests/qxmppomemodata/`
(internal tests only); all built only with `BUILD_OMEMO=ON`.

## Typical changes

Storage backends: subclass `QXmppOmemoStorage`. Protocol changes go in
`QXmppOmemoManager_p.cpp`. Its `warning()` lines include JIDs and device IDs
(e.g. `QXmppOmemoManager_p.cpp:1115`, `:1149`, `:3055`).
