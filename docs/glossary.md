# Glossary

| Term | Meaning in this repo |
|---|---|
| XMPP | Extensible Messaging and Presence Protocol (RFC 6120/6121); an XML stream over TCP/TLS |
| JID | Jabber ID, `user@domain/resource`; bare JID omits `/resource`. Helpers in `QXmppUtils` |
| Stanza | Top-level `<message/>`, `<presence/>` or `<iq/>` element (`QXmppStanza` and subclasses) |
| Nonza | Stream-level element that is not a stanza (SASL, stream management, STARTTLS); `QXmppNonza` |
| IQ | Info/Query request–response stanza (`QXmppIq`); `get`/`set`/`result`/`error` |
| XEP | XMPP Extension Protocol; supported XEPs are listed in `doc/doap.xml` |
| SASL | Authentication layer (RFC 6120 §6); mechanisms in `src/base/QXmppSasl.cpp` |
| Non-SASL auth | Legacy `jabber:iq:auth` login (XEP-0078), `QXmppNonSASLAuthIq`; digest by default, plaintext when the server only offers it or `NonSASLPlain` is configured |
| Stream management (SM) | XEP-0198 acks and resumption; `QXmppStreamManager`, `QXmppStreamManagement*` nonzas |
| Resume host | `location` announced by the server in SM `<enabled/>`; DisplayNote's `1.6` ignores it when reconnecting |
| Extension / manager | `QXmppClientExtension` subclass implementing a feature (e.g. `QXmppRosterManager`) |
| MUC | Group chat, XEP-0045 (`QXmppMucManager`) |
| PubSub / PEP | XEP-0060 publish-subscribe / personal eventing (`QXmppPubSubManager`) |
| MAM | XEP-0313 message archive (`QXmppMamManager`) |
| Jingle / JMI | Call signalling (XEP-0166/0167; Message Initiation XEP-0353) — `QXmppCallManager`, `QXmppJingleMessageInitiationManager` |
| ICE / STUN / TURN | NAT traversal for Jingle and transfers, `QXmppStun.cpp` |
| OMEMO | End-to-end encryption, `src/omemo` |
| ATM | Automatic Trust Management (XEP-0450), `QXmppAtmManager` |
| QXmppTask / QXmppPromise | QXmpp's own future/promise pair for async results |
| `QXmppLogger` message types | `DEBUG`, `INFO`, `WARNING`, `RECEIVED`, `SENT` (`src/base/QXmppLogger.cpp`) |
| `@dn/stable`, `@dn/develop` | DisplayNote Conan user/channels used in the `README.md` packaging examples |
| qt-conan-ci | `DisplayNote/qt-conan-ci`, the Azure Pipelines template repository used by `ci/azure-pipelines.yml` (pinned to tag `2.4.0`) |
| AB#nnnnn | Azure Boards work item referenced in DisplayNote commit messages |
