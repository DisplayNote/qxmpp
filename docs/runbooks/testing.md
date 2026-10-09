# Testing

## What exists

- **Unit tests** (Qt Test): one executable per folder `tests/<name>/tst_<name>.cpp`,
  registered with `add_simple_test(<name> [extra sources])` in `tests/CMakeLists.txt`
  (`qxmpptransfermanager`, `qxmpputils` and `qxmpphttpuploadmanager` have their own
  `CMakeLists.txt`). Built when `BUILD_TESTS=ON` (the CMake default).
- **Internal tests**: test unexported symbols (`qxmppsasl`, `qxmppstreaminitiationiq`,
  `qxmppomemodata`); need `-DBUILD_INTERNAL_TESTS=ON` and a debug build (`CONTRIBUTING.md`).
- **Feature-gated tests**: `qxmppfileencryption` (`WITH_QCA`), `qxmppcallmanager`
  (`WITH_GSTREAMER`; skipped when `QXMPP_TESTS_SKIP_CALL_MANAGER` is set), OMEMO tests (`BUILD_OMEMO`).
- **Integration tests**: compiled into `qxmppcallinvitemanager`, `qxmpphttpuploadmanager`,
  `qxmppjinglemessageinitiationmanager`, `qxmppomemomanager` and `qxmppvcardmanager`
  (`tests/IntegrationTesting.h`), skipped unless `QXMPP_TESTS_INTEGRATION_ENABLED=1`,
  `QXMPP_TESTS_JID` and `QXMPP_TESTS_PASSWORD` are set. They log in to a real server with that
  account.

There are no end-to-end or UI tests, and no tests for the DisplayNote reconnection /
resumption changes.

## Where tests run

- Locally only, in practice. DisplayNote CI (`ci/azure-pipelines.yml`) configures every
  platform with `-DBUILD_TESTS=OFF`.
- `.github/workflows/tests.yml` (upstream) would run `tests/travis/build-and-test`, but GitHub
  Actions workflows are not registered on `DisplayNote/qxmpp` (only Copilot code review runs
  there), so it does not run for this fork.

## Run

```bash
cmake -B build -DBUILD_TESTS=ON -DBUILD_INTERNAL_TESTS=ON -DCMAKE_BUILD_TYPE=Debug
cmake --build build
cd build && ctest --output-on-failure                 # all
cd build && ctest --output-on-failure -R qxmppsasl    # one test
```

## Add a test

1. Create `tests/<name>/tst_<name>.cpp` with a `QObject` test class and `QTEST_MAIN`
   (copy `tests/qxmppversionmanager/tst_qxmppversionmanager.cpp` for a manager, or
   `tests/qxmppversioniq/` for a parse/serialise round trip using `parsePacket()` /
   `serializePacket()` from `tests/util.h`).
2. Register it: `add_simple_test(<name>)` — append `TestClient.h` if it uses `TestClient`.
3. For a test that must reach a server, guard it with the macros in `tests/IntegrationTesting.h`.

## Logging in tests

`TestClient` (`tests/TestClient.h`) switches its logger to `SignalLogging` and records
`SENT` entries; with `debugEnabled` it prints them with `qDebug` (line 82). Several tests
(`tst_qxmppcallmanager`, `tst_qxmppiceconnection`) use `StdoutLogging`, so their output
contains STUN dumps and stanzas. With integration tests enabled,
`tests/qxmppomemomanager/tst_qxmppomemomanager.cpp` prints every `SENT`/`RECEIVED` entry of a
real login with `qDebug` (lines 185–191 and later), so its output carries the test account's
SASL exchange, and `tests/qxmpphttpuploadmanager/tst_qxmpphttpuploadmanager.cpp:435` prints the
upload URL — treat test output as a log (see [debugging-with-ai.md](debugging-with-ai.md)).
