# Troubleshooting

| Symptom | Root cause | Fix |
|---|---|---|
| `OMEMO requires QCA (Qt Cryptographic Architecture)` at configure time | `BUILD_OMEMO=ON` without QCA found (`CMakeLists.txt`) | Install QCA for your Qt major version or drop `BUILD_OMEMO` |
| `tst_qxmppsasl` / `tst_qxmppstreaminitiationiq` missing | Only built with `BUILD_INTERNAL_TESTS=ON` (`tests/CMakeLists.txt`) | Reconfigure with `-DBUILD_INTERNAL_TESTS=ON -DCMAKE_BUILD_TYPE=Debug` |
| `tst_qxmppcallmanager` missing or skipped | Built only with `WITH_GSTREAMER=ON`; skipped when `QXMPP_TESTS_SKIP_CALL_MANAGER` is set (upstream CI sets it on macOS) | Enable GStreamer / unset the variable |
| Integration test cases reported as skipped | `QXMPP_TESTS_INTEGRATION_ENABLED`, `QXMPP_TESTS_JID`, `QXMPP_TESTS_PASSWORD` not set (`tests/IntegrationTesting.h`) | Export them in your shell only; never commit them |
| No QXmpp log output at all | Default logger type is `NoLogging` (`src/base/QXmppLogger.cpp:99`) | `client.logger()->setLoggingType(...)`; mind the sensitivity notes in [debugging-with-ai.md](debugging-with-ai.md) |
| `QXmppClientLog.log` appears in an unexpected folder | `FileLogging` uses a relative default path, resolved against the process working directory | `setLogFilePath()` with an absolute path |
| Two clients' logs are mixed | All clients share `QXmppLogger::getLogger()` unless `setLogger()` is called | Give each client its own `QXmppLogger` |
| `… Reconnection tries: N - Calculated delay: <ms>` or `… reconnection timer not active, relaunching...` lines in the host's log (prefixed with the function signature, `Q_FUNC_INFO`) | DisplayNote `qDebug()` lines in `src/client/QXmppClient.cpp` (94–95, 971) | Expected; the delay is randomised on purpose (5–70 s) |
| Client does not reconnect after `disconnectFromServer()` | Presence is set `Unavailable` there, and `_q_streamDisconnected()` only reconnects while it is `Available` (AB#126881) | Call `connectToServer()` explicitly |
| Client reconnects to the configured host instead of the server's resume `location` | DisplayNote disabled resume-host connections (`src/client/QXmppOutgoingClient.cpp:223–229`) | Expected on `1.6` |
| Pipeline deploy fails with `No build output at '<path>'` | A stage's staging path and `conanfile.py` `_source_folder()` disagree | Keep `platform:` in `ci/azure-pipelines.yml`, the profile list and `_source_folder()` in step ([release.md](release.md)) |
| macOS CI fails with `ENOTDIR … libQXmppQt6.4.dylib` | Versioned symlink chain cannot be staged by the CopyFiles task (comment in `CMakeLists.txt`) | Keep `-DBUILD_UNVERSIONED_LIBRARY=ON` in `cmakeCommonArgs` |
| Secret-scan pre-commit hook stopped running | `utils/setup-hooks.sh` overwrote `.git/hooks/pre-commit` | Re-run `/secret-scan-setup` |
| README says `BUILD_DOCUMENTATION` defaults to `ON` but docs are not built | `CMakeLists.txt` defaults it to `OFF` | Pass `-DBUILD_DOCUMENTATION=ON` |
| A fix on `master` never reaches Montage | DisplayNote ships the `1.6` branch | Port the change to `1.6` ([release.md](release.md)) |
