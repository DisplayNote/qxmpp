# Module: server (`src/server`)

## Purpose and boundaries

A small embeddable XMPP server, compiled into the same library as the client. It accepts
client-to-server (`QXmppIncomingClient`) and server-to-server (`QXmppIncomingServer`,
`QXmppOutgoingServer`, dialback in `QXmppDialback`) streams and routes stanzas to
`QXmppServerExtension`s. Nothing in this repository shows DisplayNote using it, and it has no
DisplayNote changes.

## Public API

- `QXmppServer` (`QXmppServer.h`): `setDomain()`, `setPasswordChecker()`,
  `addExtension()`, `listenForClients()`, `listenForServers()`, `setLogger()`.
- `QXmppPasswordChecker` (`QXmppPasswordChecker.h`): override `checkPassword()` /
  `getPassword()` to authenticate users.
- `QXmppServerExtension`, `QXmppServerPlugin`: extension and plugin interfaces.

## Dependencies

Upstream: `src/base` (stream, SASL server mechanisms, logger). Downstream: none in
DisplayNote code visible here; `examples/example_8_server`.

## Testing in isolation

`tests/qxmppserver/tst_qxmppserver.cpp` starts a `QXmppServer` on localhost and connects a
`QXmppClient` to it (stdout logging is commented out there).

## Typical changes

Rare for DisplayNote. Server-side stanza handling goes in a `QXmppServerExtension`
subclass; authentication in a `QXmppPasswordChecker` subclass. Its `info()`/`warning()`
lines log user names, JIDs and peer addresses (`QXmppIncomingClient.cpp`).
