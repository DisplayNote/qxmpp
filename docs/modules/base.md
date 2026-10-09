# Module: base (`src/base`)

## Purpose and boundaries

Protocol data model and plumbing shared by client and server: stanza/IQ/nonza classes and
their XML (de)serialisation, the XML stream and its socket, SASL mechanisms, STUN/TURN/ICE,
logging, async task types and utilities. No connection policy lives here — that is
`src/client` (`QXmppOutgoingClient`, `QXmppClient`) or `src/server`.

## Public API (main entry points)

- Stanzas: `QXmppStanza`, `QXmppMessage`, `QXmppPresence`, `QXmppIq` and the many
  `QXmpp*Iq` payload classes (`QXmppVersionIq`, `QXmppRosterIq`, `QXmppPubSubIq`, …);
  `QXmppNonza` is the base of everything that can be serialised onto the stream.
- Stream: `QXmppStream` (`QXmppStream.h`) — owns the `QSslSocket`, frames the XML
  (`processData()`), writes it (`sendData()`), and holds the XEP-0198 `QXmppStreamManager`
  (`QXmppStreamManagement_p.h`).
- Logging: `QXmppLogger`, `QXmppLoggable` (`QXmppLogger.h`).
- Async: `QXmppTask<T>`, `QXmppPromise<T>` (`QXmppTask.h`, `QXmppPromise.h`), `QXmppError`.
- SASL: `QXmppSaslClient*` / `QXmppSaslServer*` and the `QXmppSaslAuth` / `Challenge` /
  `Response` nonzas (private, `QXmppSasl_p.h`); legacy auth in `QXmppNonSASLAuthIq`.
- ICE: `QXmppIceConnection`, `QXmppStunMessage` (`QXmppStun.h`).
- Utilities: `QXmppUtils` (JID helpers, date/time; `helperToXmlAdd*` exported for Win64 by
  DisplayNote).
- `compat/` keeps the deprecated `QXmppPubSubIq` / `QXmppPubSubItem` API compiling.

## Dependencies

Upstream: Qt Core, Network, Xml (and QCA when `WITH_QCA`). Downstream: `src/client`,
`src/server`, `src/omemo`, tests.

## Testing in isolation

Most payload classes have a parse/serialise round-trip test using `parsePacket()` /
`serializePacket()` from `tests/util.h`, e.g. `tests/qxmppversioniq/`,
`tests/qxmppmessage/`, `tests/qxmppstunmessage/`, `tests/qxmppnonsaslauthiq/`,
`tests/qxmppregisteriq/`. Private classes (SASL) are tested in `tests/qxmppsasl/`, built only
with `-DBUILD_INTERNAL_TESTS=ON`.

## Typical changes

- New XEP payload: add `QXmpp<Name>Iq.{h,cpp}` implementing `parseElementFromChild()` and
  `toXmlElementFromChild()` (pattern: `QXmppVersionIq.cpp`), list both files in
  `src/CMakeLists.txt`, add a `tests/qxmpp<name>iq/` round-trip test.
- Anything touching `QXmppStream::sendData()` / `processData()` affects every byte that is
  logged as `SENT` / `RECEIVED`; see [../runbooks/debugging-with-ai.md](../runbooks/debugging-with-ai.md).
