# Debugging with AI — log sanitisation (control 4.7)

> Generated from the `log-sanitise` template (displaynote-engineering plugin) by
> `docs-update`. The "Mandatory step" and "Rules" sections are kept verbatim.

## Where this repo's logs live

| Source | Location / command | Typical sensitive content |
|---|---|---|
| Application log | Two channels, both ending up in the host application's logs. (1) `QXmppLogger` (`src/base/QXmppLogger.cpp`): classes derived from `QXmppLoggable` emit `debug()`/`info()`/`warning()`/`logSent()`/`logReceived()`, which reach the logger set on the `QXmppClient` — by default the process-wide `QXmppLogger::getLogger()` (`src/client/QXmppClient.cpp:259`). Its `loggingType` defaults to `NoLogging` (`QXmppLogger.cpp:99`), so nothing is written unless the host changes it. `FileLogging` appends lines `<QDateTime::currentDateTime().toString()> <DEBUG\|INFO\|WARNING\|RECEIVED\|SENT> <text>` to `QXmppClientLog.log`, a relative path resolved against the process working directory, unless `setLogFilePath()` is called; `SignalLogging` emits `QXmppLogger::message(type, text)` and the host decides where it goes. How Montage configures the logger is not visible in this repo; whatever Montage forwards ends up in Montage's log files. (2) Plain Qt messages, independent of `QXmppLogger`, go to the host's Qt message handler (in Montage, Montage's logs): the DisplayNote reconnection `qDebug()` lines (`src/client/QXmppClient.cpp:94–95`, try count and delay, and `:971`), upstream `qWarning()` lines in `src/base` and `src/client` (e.g. `src/base/QXmppJingleData.cpp:121, 837, 850, 906, 915, 1783` print unparsable SDP / candidate lines; `QXmppDataForm.cpp:801`, `QXmppRosterIq.cpp:333, 354`, `QXmppSocks.cpp`, `src/client/QXmppClient.cpp:315, 337`, `QXmppMucManager.cpp:198`, `QXmppTransferManager.cpp:792`), a `qDebug()` in `src/client/QXmppInvokable.cpp:74` (RPC method name) and `qFatal()` on programming errors. There is no `Q_LOGGING_CATEGORY`, no `qInstallMessageHandler` and no file logger other than `FileLogging` in `src/` | `SENT`/`RECEIVED` entries are the raw XML stream: JIDs and resources, presence and status text, message bodies, roster/vCard data (names, e-mails, phone numbers, photos), MUC room names, server hostnames; SASL `<auth>`/`<response>` payloads (base64, reversible — PLAIN and X-OAUTH2 carry the user name and the password or access token, X-MESSENGER-OAUTH2 and X-FACEBOOK-PLATFORM an access token; SCRAM and DIGEST-MD5 carry nonces, salt and proofs), the plaintext `<password>` of legacy `jabber:iq:auth` (plaintext mode only) and of `jabber:iq:register` (password change / registration), HTTP-upload slot URLs and `Authorization`/`Cookie` header values. `DEBUG`/`INFO`/`WARNING` entries carry the server host and port, the peer IP (`Socket connected to …`), the XMPP domain, STUN/TURN dumps (IPs, ports, `USERNAME`, `REALM`, `NONCE`), SOCKS5 stream-host JIDs and hosts, local file paths (file transfer), call peer JIDs (GStreamer builds only) and, in the OMEMO and server modules, JIDs, device IDs and user names. The `qWarning` SDP lines carry candidate IP addresses and ports |
| Live stream | No logcat tag, journal unit or OS log of its own. `StdoutLogging` writes the same line format with `std::cout` (`QXmppLogger.cpp:183`) to the process's stdout. The `qDebug`/`qWarning` lines follow the host's Qt message handler; with Qt's default handler they go to the platform's default sink (stderr or debugger output on desktop, logcat on Android — dump it with `adb logcat -d` piped through `dn_logscrub.py -`, filtered to the host app's process). Most examples (`StdoutLogging` in `examples/example_0_connected`, `example_1_echoClient`, `example_3_transferHandling`, `example_5_rpcInterface`, `example_6_rpcClient`, `example_8_server`) and some tests (`tests/qxmppcallmanager/`, `tests/qxmppiceconnection/`) print the stream live; `ctest --output-on-failure` shows that output, plus `TestClient`'s `qDebug` lines (`tests/TestClient.h:82`) when its debug flag is on | Same as the application log |
| Crash reports | No crash reporter (Sentry or similar) is wired into this repo, and it writes no dump files. A `qFatal()` — GStreamer pipeline failures in `src/client/QXmppCall.cpp` / `QXmppCallStream.cpp` (only built with `WITH_GSTREAMER`), or API misuse in `src/client/QXmppHttpFileSharingProvider.cpp:87`, `QXmppEncryptedFileSharingProvider.cpp:66` (`WITH_QCA` only) and `src/omemo/QXmppOmemoManager.cpp:1237, 1242` — aborts the host process with its message in the host's Qt message handler. Crashes inside Montage are reported by Montage's own crash reporting, if it has any | stack frames, paths |
| CI logs | Azure Pipelines run logs (`displaynote-devops`) | internal paths, hostnames |
| Customer bundles | Zendesk ticket attachments — download them to a file and sanitise before reading; the Zendesk MCP bypasses the Claude Code guard, so never read attachments through it (see `.agents/skills/log-sanitise/SKILL.md`) | **Protected**: end-user identifiers (1.3 §4.2) |

## Mandatory step — sanitise before any AI tool sees the log

Before a log file, a log excerpt or a live log stream reaches Claude Code, Codex,
Copilot, Cursor, ChatGPT, Claude (Cowork) or any custom OpenAI-API integration,
run it through `dn_logscrub`:

```bash
# Work OUTSIDE the repository: a raw log inside it blocks the searches that would read it
mkdir -p ~/dn-tickets/22416 && cd ~/dn-tickets/22416

# Claude Code (plugin installed) — one call, all files, shared placeholders
/log-sanitise montage.log launcher.log --map ticket-22416.dnmap

# Any agent / shell — the portable copy synced into the repo
python3 <repo>/.agents/skills/log-sanitise/scripts/dn_logscrub.py montage.log launcher.log --map ticket-22416.dnmap

# Inputs in a read-only folder, or elsewhere: write the copies into one directory
python3 <repo>/.agents/skills/log-sanitise/scripts/dn_logscrub.py /var/log/omni/*.log --out-dir ~/dn-tickets/22416

# Live streams — pipe, never paste; use a command that ends (`-d`), not a live tail
adb logcat -d | python3 <repo>/.agents/skills/log-sanitise/scripts/dn_logscrub.py - > logcat.scrubbed.txt

# Customer logs — add the customer's domain(s) so their hostnames are pseudonymised too
python3 <repo>/.agents/skills/log-sanitise/scripts/dn_logscrub.py bundle/*.log --domain acme-school.org
```

A run that is cut short (Ctrl-C, a tool timeout) still writes a trailer marked
`interrupted`: the copy is clean but incomplete. The sanitiser processes a few
MB per second; run very large bundles from your own terminal.

The tool writes `<name>.scrubbed.<ext>` next to each input, prints one summary
line per file (`dn_logscrub: montage.log: 41 redactions (EMAIL=3, ID=12, …)`) and
starts every output with a `# dn_logscrub v…` marker header and ends it with a
`# dn_logscrub end | redactions=…` trailer carrying the per-category counts
(output is written as it is produced, so a live stream appears immediately
instead of waiting for the end). Only files that start with that header and
end with that trailer may be opened by, pasted into, or attached to an AI tool.
A file with the header but no trailer as its last non-empty line is raw:
something was appended after scrubbing (`cat raw >> x.scrubbed.log`,
concatenated files, a process still writing). A trailer ending in
`| interrupted` is accepted — the copy is clean, only incomplete. A
`# dn_logscrub-partial` header does not count: it means rules were switched off
for that run.

## Rules

1. Only `*.scrubbed.*` files (marker header on the first line and the
   `# dn_logscrub end` trailer as the last non-empty line) go to an AI tool.
   Raw logs never do — the Claude Code hook blocks them; for other tools the
   rule is on you.
2. Placeholders are stable within a run: `<EMAIL_1>` is the same person in every
   file of that run. Keep placeholders in PR descriptions, ticket comments and
   Slack messages; never expand them there.
3. The `--map` file (`*.dnmap`) holds the originals for your own reverse lookup.
   It stays on your machine; never attach it, commit it or paste from it.
4. Customer logs are **Protected** data by default (AI Governance Policy 1.3 §4.2).
   Sanitised customer logs may go to Green-List tools with a corporate account.
   Raw customer logs may go to an AI tool only with AI Lead + CEO approval
   (1.3 §4.1) — signal an approved exception with `DN_LOGSCRUB_ALLOW_RAW=1`.
5. Residual check: skim the scrubbed file for anything the patterns missed
   (a person's name in free text, a customer hostname without `--domain`, an
   unusual token format). Fix with `--domain`, or open an issue on
   `displaynote-engineering` with the *category and shape* of the miss — never
   with the value itself.
6. Automated flows (Sentry fixer, Release Management Agent, n8n) call the same
   library (`Scrubber().scrub_text(...)`) before every external model call. A
   flow that writes its result to a file uses `Scrubber().finalize(text, name)`,
   which adds the header and trailer the Claude Code hook and `--check` require.

## What is redacted vs. kept

Redacted irreversibly: private keys, JWTs, auth headers, URL credentials,
cloud/API keys, any `password= / token= / secret= / *_key=` value, OAuth
`code=`/`state=`/`nonce=` in URLs.
Pseudonymised consistently: e-mails, quoted/keyed names (people, devices,
computers), keyed ids (serial, deviceId, session, meetingId, roomPin, tenantId,
licence…), Android `getprop` serials, Wi-Fi SSIDs, IPv4/IPv6, MACs, UUIDs, phone
numbers, the user-home part of any path (Windows with either slash, JSON-escaped,
`file:///`, WSL), Windows `DOMAIN\user` accounts and UNC servers, `DESKTOP-…`
machine names, `.local/.lan/.internal` hosts, `--domain` domains, long hex and
high-entropy strings.
Kept: timestamps, version numbers, stack traces, package/class/method names and
JNI symbols, the rest of the path, file hashes and git commit ids, loopback
addresses, and keys that only describe a secret (`token_expires_in=3600`).
Not caught: a person's name in free text, a customer hostname without `--domain`.

Repo-specific note: `QXmppLogger` writes nothing until the host application sets a
logging type other than `NoLogging`; from then on nothing is filtered by build type.
The levels are runtime flags (`messageTypes`, default `AnyMessage` = all five types,
`src/base/QXmppLogger.cpp:99`), no logging call in `src/` sits behind a
`QT_NO_DEBUG`/`NDEBUG` guard, and neither `CMakeLists.txt`, `src/CMakeLists.txt`,
`ci/azure-pipelines.yml` nor `conanfile.py` defines `QT_NO_DEBUG_OUTPUT`
(`QXMPP_LOGGABLE_TRACE` only adds a class-name prefix and no build file defines it). So
the Release packages that DisplayNote CI builds log exactly what the Debug ones do,
including the DisplayNote `qDebug()` reconnection lines (`src/client/QXmppClient.cpp:94–95`,
`:971`; whether the host prints them depends on its Qt message handler and logging
rules). The main residual risk is credentials. `QXmppStream::sendData()`
(`src/base/QXmppStream.cpp:147`) logs every outbound byte as `SENT` before writing it,
so the log holds the SASL `<auth>` initial response (`QXmppSaslAuth::toXml()`,
`src/base/QXmppSasl.cpp:135`): for PLAIN the base64 of NUL + user name + NUL + password
(`QXmppSaslClientPlain::respond()`, line 547), for X-OAUTH2 the same with the Google
access token (line 524), for X-MESSENGER-OAUTH2 the Windows Live access token (line 636).
SASL `<response>` elements (`QXmppSaslResponse::toXml()`, line 225, sent from
`src/client/QXmppOutgoingClient.cpp:591`) carry the DIGEST-MD5 response, the SCRAM client
proof and, for X-FACEBOOK-PLATFORM, the `access_token` (line 492). The client takes the
first mechanism the server offers in the order SCRAM-SHA3-512 … SCRAM-SHA-1, DIGEST-MD5,
PLAIN (`QXmppSaslClient::availableMechanisms()`), unless
`QXmppConfiguration::setSaslAuthMechanism()` moves another one to the front, so PLAIN is
used when the server offers nothing stronger or the configuration asks for it; SCRAM
logins still log nonces, salt and proof. Legacy `jabber:iq:auth` (XEP-0078) sends a
plaintext `<password>` (`QXmppNonSASLAuthIq::toXmlElementFromChild()`,
`src/base/QXmppNonSASLAuth.cpp:120`, set at `QXmppOutgoingClient.cpp:879`) only when the
server offers plaintext non-SASL auth alone or the configuration selects `NonSASLPlain`
(the default `NonSASLDigest` sends a SHA-1 digest, line 881).
`QXmppRegistrationManager::changePassword()` (`src/client/QXmppRegistrationManager.cpp:70`)
and registration forms send the new password in clear (`src/base/QXmppRegisterIq.cpp:318`).
`RECEIVED` entries (`QXmppStream::processData()`, line 437) carry SASL challenges and
HTTP-upload slots with their `Authorization`/`Cookie` header values
(`src/base/QXmppHttpUploadIq.cpp:231–236`). The keyed `password=`/`token=` rules do not
match XML element content, and the high-entropy rule only catches runs of 32 or more
characters, so a short base64 SASL payload or a `<password>` element can survive
sanitisation: check for `<auth`, `<response`, `<password>` and upload `<header` elements
in the residual pass. The rest is personal data in free text that no pattern catches:
message bodies, presence status text, vCard and roster names; JIDs that look like e-mail
addresses are pseudonymised by the e-mail rule. Other identifying lines: server host and
port and peer IP (`QXmppOutgoingClient.cpp:130`, `QXmppStream.cpp:336`), the XMPP domain
(SRV lookup, `QXmppOutgoingClient.cpp:239`), the bound JID on a bind error (line 648),
STUN/TURN dumps with IPs, ports, `USERNAME`, `REALM` and `NONCE`
(`src/base/QXmppStun.cpp:1384, 1639, 1998, 2162, 2549`, fields printed by
`QXmppStunMessage::toString()`, lines 1087–1102), SOCKS5 stream hosts and local file
paths (`src/client/QXmppTransferManager.cpp:287, 490, 541, 567, 611, 1267`), candidate
IPs in the `qWarning` SDP lines (`src/base/QXmppJingleData.cpp`), which reach the host's
Qt message handler even when `QXmppLogger` is off, and — in code the DisplayNote package
does not build (`WITH_GSTREAMER` and `BUILD_OMEMO` are off) or that nothing in this repo
shows DisplayNote using (the server module) — call peer JIDs (`src/client/QXmppCall.cpp`), OMEMO JIDs and device IDs
(`src/omemo/QXmppOmemoManager_p.cpp`) and user names with peer addresses
(`src/server/QXmppIncomingClient.cpp`). `FileLogging` keeps all of this on disk in
`QXmppClientLog.log` in the working directory unless `setLogFilePath()` is used. CI writes
no QXmpp output: the Azure pipeline builds with `-DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF`,
and the upstream GitHub workflows (`.github/workflows/tests.yml`) are not registered on
`DisplayNote/qxmpp`. Locally, `ctest` output from `tests/qxmppiceconnection/` and
`tests/qxmppcallmanager/` (`StdoutLogging`) contains STUN dumps; with integration tests
enabled (`QXMPP_TESTS_INTEGRATION_ENABLED`, `QXMPP_TESTS_JID`, `QXMPP_TESTS_PASSWORD`)
`tests/qxmppomemomanager/tst_qxmppomemomanager.cpp` prints every `SENT`/`RECEIVED`
entry of a real login with `qDebug`, including that account's SASL exchange, and
`tests/qxmpphttpuploadmanager/tst_qxmpphttpuploadmanager.cpp:435` prints the upload URL;
`examples/example_0_connected`, `example_1_echoClient`, `example_3_transferHandling`,
`example_5_rpcInterface`, `example_6_rpcClient` and `example_8_server` print the whole stream
with `StdoutLogging`, and `examples/example_9_vCard` prints vCard names with `qDebug`. No repo-specific sanitiser patterns have been shipped yet; raise any needed as an issue on `displaynote-engineering` and list them here once shipped.
