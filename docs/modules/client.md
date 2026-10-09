# Module: client (`src/client`)

## Purpose and boundaries

Everything an XMPP client needs on top of `src/base`: the public `QXmppClient` facade
(including reconnection), the connection state machine (`QXmppOutgoingClient`), configuration,
and the feature managers (`QXmppClientExtension` subclasses). Server-side code does not belong
here.

## Public API

- `QXmppClient` (`QXmppClient.h`): `connectToServer()`, `disconnectFromServer()`, `send()`,
  `sendSensitive()`, `sendPacket()`, `addExtension()` / `addNewExtension<T>()`,
  `findExtension<T>()`, `logger()` / `setLogger()`; signals `connected()`, `disconnected()`,
  `error(QXmppClient::Error)`, `stateChanged()`, `messageReceived()`, `presenceReceived()`,
  `iqReceived()`, `sslErrors()`. The constructor installs `QXmppLogger::getLogger()`
  (process-wide singleton) as the logger (`QXmppClient.cpp:259`) and adds `QXmppTlsManager`
  plus, by default, the roster, vCard, version, entity-time and discovery managers.
- `QXmppConfiguration` (`QXmppConfiguration.h`): JID, password, host/port, TLS mode, SASL
  options (`setSaslAuthMechanism()`, `setUseSASLAuthentication()`,
  `setUseNonSASLAuthentication()`, `setNonSASLAuthMechanism()`), OAuth-style access tokens
  (`setFacebookAccessToken()`, `setGoogleAccessToken()`, `setWindowsLiveAccessToken()`),
  auto-reconnect, keep-alive.
- Managers (`*Manager*.h` in this folder), e.g. `QXmppRosterManager`, `QXmppVCardManager`,
  `QXmppDiscoveryManager`, `QXmppMucManager`, `QXmppPubSubManager`, `QXmppMamManager`,
  `QXmppHttpUploadManager`, `QXmppFileSharingManager`, `QXmppTransferManager`,
  `QXmppCallManager`, `QXmppJingleMessageInitiationManager`, `QXmppRegistrationManager`,
  `QXmppBlockingManager`.

Internal: `QXmppClient_p.h` (`QXmppClientPrivate`, reconnection state), `QXmppTlsManager_p.h`,
`QXmppOutgoingClient.cpp` (`QXmppOutgoingClientPrivate`, SASL / non-SASL auth, bind, SM).

## DisplayNote changes in this module

| Where | What | Work item |
|---|---|---|
| `QXmppClient.cpp:69–98` | randomised reconnection delay + `qDebug()` of try count and delay | AB#115566 |
| `QXmppClient.cpp:951` | `_q_streamConnected()` also stops the reconnection timer | AB#115566 |
| `QXmppClient.cpp:963–974` | `_q_streamDisconnected()` schedules a reconnect if none is pending and presence is `Available` (+ `qDebug()` line 971) | AB#126881 |
| `QXmppClient.cpp:992` | socket-error reconnects increment the try count | AB#115566 |
| `QXmppOutgoingClient.cpp:223–229` | do not connect to the stream-management resume host | AB#115566 |
| `QXmppOutgoingClient.cpp:758–759, 771–772, 797–798` | force `sessionStarted = true` after SM enabled / resumed / failed | AB#115566 |

Verify with `git log -p 3fa204ec..origin/1.6 -- src/client`.

## Dependencies

Upstream: `src/base`; optional QCA (`QXmppFileEncryption`, encrypted file sharing) and
GStreamer (`QXmppCallManager`, `QXmppCall`, `QXmppCallStream`). Downstream: applications
(Montage) and `src/omemo`.

## Testing in isolation

`tests/TestClient.h` is a `QXmppClient` subclass that records every `SENT` log entry and
lets a test `inject()` inbound XML and `expect()` / `takePacket()` the outbound packets,
without a network. Pattern: `tests/qxmppversionmanager/tst_qxmppversionmanager.cpp`.
Connection logic has `tests/qxmppclient/` and `tests/qxmppoutgoingclient/`; there is no test
for the DisplayNote reconnection or resumption changes. Tests that need a real server are
skipped unless the `QXMPP_TESTS_*` variables are set (`tests/IntegrationTesting.h`, see
[../runbooks/testing.md](../runbooks/testing.md)).

## Extension points and typical changes

- New feature manager: subclass `QXmppClientExtension`, override `handleStanza()` and
  `discoveryFeatures()`; dispatch IQ requests with `QXmpp::handleIqRequests<Iq…>()`
  (`QXmppIqHandling.h`). Pattern: `QXmppVersionManager.cpp`.
- Connection behaviour (reconnect, stream management, auth order) lives in
  `QXmppClient.cpp` and `QXmppOutgoingClient.cpp`; keep the DisplayNote changes above intact.
