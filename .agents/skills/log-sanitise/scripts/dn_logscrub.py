#!/usr/bin/env python3
"""
dn_logscrub.py — DisplayNote log sanitiser for AI-assisted debugging.

AI Security Roadmap control 4.7 "Log sanitisation before external AI tools"
(register id `log-sanitisation-before-external-ai-tools`, mandatory L0→L1):
log content must be sanitised before being passed to an external AI tool,
because logs routinely contain session tokens, user identifiers and internal
paths.

Design goals
  * Standard library only (Python 3.8+), one file, runs anywhere: developer
    laptops, CI agents, the Zendesk MCP server, the OpenAI-API pipelines.
  * Consistent pseudonymisation: the same value always becomes the same
    placeholder within a run (`<EMAIL_1>`, `<IPV4_3>`, ...), across every file
    in that run, so correlation in the log survives and the scrubbed log is
    still useful for debugging.
  * Secrets are redacted, not pseudonymised (`<REDACTED:JWT>`): nothing that
    could be replayed is kept in any form.
  * Every scrubbed file starts with a marker header line so downstream tools
    (the Claude Code hook, `--check`) can tell scrubbed from raw.
  * The value→placeholder map can be written to a local sidecar (`--map`) for
    reverse lookup by the engineer. It stays on the engineer's machine and is
    never shared with an AI tool.

Usage
  python3 dn_logscrub.py app.log                      # -> app.scrubbed.log
  python3 dn_logscrub.py a.log b.log --map t.dnmap    # shared placeholders
  adb logcat -d | python3 dn_logscrub.py - > logcat.scrubbed.txt
  python3 dn_logscrub.py --check app.scrubbed.log     # exit 0 if scrubbed
  python3 dn_logscrub.py --selftest                   # built-in fixtures

Library
  from dn_logscrub import Scrubber
  s = Scrubber()
  clean = s.scrub_text(raw)          # keeps the map across calls
  clean = s.finalize(clean, "name")  # marker header + trailer, as the guard requires
  s.stats                            # {category: count}

Exit codes: 0 ok · 1 usage / IO error · 3 (--check) file is NOT scrubbed.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import io
import json
import base64 as _b64
import math
import os
import re
import sys
from typing import Callable, Dict, Iterable, List, Optional, Tuple

__version__ = "1.1.0"
MARKER = "dn_logscrub"
MARKER_RE = re.compile(r"^#\s*dn_logscrub\s+v\d+\.\d+")

# --------------------------------------------------------------------------- #
# Patterns. Order matters: secrets first (so a JWT inside a URL is caught as a
# JWT, not as a high-entropy token), then identifiers, then generic catch-alls.
# Each rule: (category, compiled regex, mode) where mode is
#   "redact"   -> <REDACTED:CATEGORY>            (secrets; never reversible)
#   "pseudo"   -> <CATEGORY_n>                    (identifiers; consistent)
#   "keyed"    -> key kept, value -> <CATEGORY_n> (regex has groups key/val)
# --------------------------------------------------------------------------- #

_SECRET_KEY_WORDS = (
    r"(?:api[_-]?key|apikey|access[_-]?key|secret(?:[_-]?key)?|client[_-]?secret|"
    r"password|passwd|pwd|token|auth[_-]?token|access[_-]?token|refresh[_-]?token|"
    r"id[_-]?token|session[_-]?token|bearer|authorization|x-api-key|sas|sig|signature|"
    r"private[_-]?key|account[_-]?key|shared[_-]?access[_-]?signature|license[_-]?key|licen[cs]e|"
    # any *_key / *.key / *-key field: encryption_key, db_key, signing-key.
    # The lookbehind keeps it a whole component, so `keyboard`, `hotkey` and
    # `keyCode` — where `key` is glued to the rest of the word — do not match.
    r"(?<=[._-])key|"
    # Session cookies and bare session tokens are replayable, so they are
    # redacted irreversibly rather than pseudonymised. `session_id` keeps its
    # separator and stays an identifier, so following a session through the log
    # still works — that is the documented benefit and it is not a credential
    # on its own.
    r"session(?![_-]?id\b)|sessionid|jsessionid|phpsessid|sid|cookie|set[_-]?cookie)"
)

# A key that DESCRIBES a secret (`token_count`, `session_timeout`) rather than
# holding one. Shared by the one-line rule and the multi-line one below.
_DESCRIBES_SECRET = (r"(?![._-](?:counts?|types?|expires?(?:[._-]?(?:in|at))?|expiry|exp|ttl|timeout|"
                     r"length|len|size|algorithm|alg|version|ver|enabled|required|valid|status|age|"
                     r"lifetime|duration|limit|used|remaining|refreshed|issued(?:[._-]?at)?)\b)")

# A secret key whose value is NOT on its line: pretty-printed JSON
# (`"token":` then the value), YAML (`password:` then an indented value, or a
# block scalar `password: |`), a folded `Authorization: Bearer` header. The
# line is scrubbed one at a time, so the key is remembered for the next one.
_PENDING_SECRET_RE = re.compile(
    r"(?i)(?:^|[\s{,\"'])(?:[A-Za-z0-9]+[._-])*" + _SECRET_KEY_WORDS + _DESCRIBES_SECRET +
    r"(?:[._-][A-Za-z0-9]+)*[\"']?\s*[=:]\s*(?:(?:bearer|basic|digest|negotiate|ntlm|token)\s*)?"
    r"([|>][+-]?\d?)?\s*$")
# A line that is itself a key (`policy: strict`, `"user": …`): the earlier key
# held a nested mapping, not a value.
_NESTED_KEY_RE = re.compile(r"^\s*(?:[\"'][^\"'\n]+[\"']|[\w.-]+)\s*:(?:\s|$)")
_NEXT_VALUE_RE = re.compile(r"^(\s*)(\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|[^\s,;]+)")

# One word of a Windows profile name: letters, digits, `.`, `-`, an apostrophe
# inside a word (`O'Connor`) or a bracketed suffix (`(School)`).
_PROFILE_WORD = r"(?:(?:[\w.-]|(?<=\w)'(?=\w))+|\([\w .'-]{1,40}\))"

# Windows' own principals, matched without regard to case.
_WIN_SYSTEM_DOMAINS = (r"(?i:NT|AUTHORITY|BUILTIN|SERVICE|APPPOOL|MANAGER|HOST|SYSTEM|HKLM|HKCU|HKCR|HKU|HKCC|"
                       r"SOFTWARE|HARDWARE|SAM|SECURITY|NT AUTHORITY|NT SERVICE|IIS APPPOOL)")
_WIN_SYSTEM_USERS = r"(?i:SYSTEM|LOCAL SERVICE|NETWORK SERVICE|Administrators|Users|Guests)"

RULES: List[Tuple[str, "re.Pattern[str]", str]] = [
    # --- secrets (redact) ---------------------------------------------------
    # No per-segment floor: `{}` encodes to `e30`, so a valid signed token can
    # have a three-character payload and was slipping past.
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "redact"),
    # No length floor: a short credential is still a credential, and leaving
    # "Bearer abc" verbatim let the later key/value rule strip only the scheme.
    # Any scheme, not a fixed list: Negotiate and NTLM headers were sailing
    # through. The optional quote lets `Authorization: "Bearer abc"` match too.
    # The credential may be quoted after the scheme, and a quoted value can
    # contain spaces and escaped quotes: `Bearer "secret phrase"` used to match
    # only through `"secret` and leave `phrase"` behind.
    # Prose after the colon is not a credential: `Authorization: failed for
    # request 42` lost the word `failed` and kept nothing worth hiding. Only
    # when a SENTENCE follows, though — a credential may be any word, so
    # `Authorization: expired` alone is still redacted.
    ("AUTH_HEADER", re.compile(r"(?i)\b(authorization\s*[:=]\s*)"
                               r"(?!(?:failed|denied|required|missing|invalid|error|errors|header|ok|success|"
                               r"succeeded|granted|pending|none|null|not|is|was|has|expired)\b(?=[ \t]+(?-i:[a-z])))"
                               r"(?:[A-Za-z][A-Za-z0-9._-]*\s+)?"
                               r"(?:\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'"
                               r"|[^\s\"',;<>]+)"), "keyed_redact"),
    # `<` and `>` stay out of the unquoted alphabet so the rule cannot swallow
    # a placeholder an earlier rule already wrote.
    ("BEARER", re.compile(r"(?i)\bbearer\s+"
                          # `bearer token expired`: a word of prose, not the token —
                          # recognised only with the sentence that follows it, so a
                          # credential that IS one of these words (`Bearer expired`
                          # on its own) is still redacted.
                          r"(?!(?:token|tokens|auth|authentication|header|is|was|expired|missing|invalid|"
                          r"required|scheme|format|value|not|none|null|and|or)\b(?=[ \t]+(?-i:[a-z])))"
                          r"(?:\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'"
                          r"|[^\s\"',;<>]+)"), "redact"),
    ("URL_CREDENTIALS", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@"), "url_creds"),
    # A DER key pasted without its PEM wrapper reached HIGH_ENTROPY and became
    # a reversible <TOKEN_n>, which put the key itself in the .dnmap. A secret
    # must be redacted irreversibly, so it is matched here, before that rule.
    ("PRIVATE_KEY", re.compile(r"\bMII[A-Za-z0-9+/]{24,}={0,2}"), "redact"),
    # OAuth and OIDC values in a query string or fragment are short-lived but
    # replayable while they live: an authorisation code exchanges for a token.
    ("OAUTH", re.compile(r"(?i)([?&#](?:code|state|nonce|code_verifier|code_challenge|id_token_hint|"
                         r"session_state)=)([^&#\s\"'<>]+)"), "keyed_redact"),
    ("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[A-Z0-9]{16}\b"), "redact"),
    ("GITHUB_TOKEN", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "redact"),
    ("SLACK_TOKEN", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "redact"),
    ("OPENAI_KEY", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}\b"), "redact"),
    ("GOOGLE_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "redact"),
    ("AZURE_CONN", re.compile(r"(?i)\b((?:AccountKey|SharedAccessSignature|SharedAccessKey|Password|Pwd|sig)\s*=\s*)([^;&\s]{8,})"), "keyed_redact"),
    # No length floor either: `token=x` and `password=abc` are exactly the
    # values the documented guarantee promises to remove.
    # A quoted value is taken whole: stopping at whitespace left the tail of
    # `password="secret phrase"` in the output.
    # The secret word may be one component of a qualified key: DB_PASSWORD,
    # API_TOKEN, AWS_SECRET_ACCESS_KEY, MY_API_KEY. It must be a whole
    # component, separated by . _ or -, so `design=grid` does not match `sig`.
    # A quoted value may contain an escaped quote: stopping at the first one
    # left the tail of `"sec\"ret"` in the output.
    # A key that DESCRIBES the secret rather than holding it — `token_count`,
    # `session_timeout`, `token_expires_in`, `signature_algorithm` — carries
    # exactly the number needed to debug an expiry, and no credential.
    ("SECRET_KV", re.compile(r"(?i)\b((?:[A-Za-z0-9]+[._-])*" + _SECRET_KEY_WORDS + _DESCRIBES_SECRET +
                             r"(?:[._-][A-Za-z0-9]+)*\s*[\"']?\s*[=:]\s*)"
                             r"(?:\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'"
                             r"|[^\s\"'&;,]+)"), "keyed_redact"),
    # --- identifiers (pseudonymise, consistent) -----------------------------
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "pseudo"),
    # key=value / key: value forms; unquoted values may continue with Capitalised words ("Jane Doe")
    ("NAME", re.compile(
        r"(?i)\b((?:display[_-]?name|user[_-]?name|username|full[_-]?name|first[_-]?name|last[_-]?name|"
        r"attendee|participant|presenter|moderator|owner|organi[sz]er|host[_-]?name(?!\s*resolution)|device[_-]?name|"
        r"room[_-]?name|tenant[_-]?name|company|customer|school|account[_-]?name|"
        # Windows names the machine with a space in the key (`Computer name:`)
        r"computer[_ -]?name|machine[_ -]?name|pc[_ -]?name|workstation(?:[_ -]?name)?)\s*[\"']?\s*[=:]\s*)"
        # (?-i:[A-Z]) — the whole rule is case-insensitive, so a plain [A-Z]
        # here also matched lowercase and the "continue over Capitalised words"
        # heuristic swallowed the next key: `user_name=<Jane Roe> device_id`
        # came out as one NAME match, taking `device_id` with it.
        r"(\"[^\"\n]{2,80}\"|'[^'\n]{2,80}'|<[^>\n]{1,80}>|"
        r"[^\s,;|=:]{2,80}(?:[ ](?-i:[A-Z])[^\s,;|=:]{1,40}){0,3})"), "keyed"),
    # quoted name right after a role word: user "Jane Doe" joined
    ("NAME", re.compile(
        # Not mid-token: `jabber:client` and `react-client` are not role words,
        # and matching inside them made the rule start in the MIDDLE of an XML
        # attribute value.
        r"(?i)(?<![\w:.-])"
        r"((?:user|attendee|participant|presenter|moderator|owner|organi[sz]er|teacher|student|guest|"
        r"client|device|peer|sender|receiver|source|caller|from|by)"
        # A real separator is required: `=`, `:` or whitespace. Allowing none
        # made `client"` match the NEXT attribute in a stanza.
        r"(?:\s*[=:]\s*|\s+))"
        # Booleans and numbers are flags, not names (`teacher="true"`). The
        # separator and the lookbehind above are what keep this rule out of XML
        # attributes; excluding `=` and `@` from the value as well broke real
        # ones — `user_name="A=B"` stopped matching here and the unquoted
        # branch of the rule above then matched the fragment `"A`.
        r"(?![\"'](?i:true|false|yes|no|on|off|null|nil|none|undefined|-?\d+(?:\.\d+)?)[\"'])"
        # Nor are file names and code identifiers: `loading from "settings.xml"`
        # and `loaded by "MontageCorePlugin"` name a file and a class. A person's
        # name has a space or is a single word; it does not end in an extension
        # or read as two or more glued CamelCase words.
        # Real extensions only: `"maria.garcia"` is a login, not a file.
        r"(?![\"'][^\"'\n\s]*\.(?:xml|json|ya?ml|txt|log|cfg|conf|ini|config|properties|plist|dll|so|dylib|"
        r"exe|jar|apk|aab|js|mjs|ts|tsx|py|kt|java|cs|cpp|h|hpp|qml|png|jpe?g|gif|svg|mp4|db|sqlite|"
        r"lock|zip|html?|css|md|csv|pdf|bin|dat|proto)[\"'])"
        r"(?![\"'](?-i:[A-Z][a-z0-9]+){2,}[\"'])"
        r"(\"[^\"\n]{2,80}\"|'[^'\n]{2,80}')"), "keyed"),
    # Wi-Fi network names identify the school or the office they belong to.
    # Unquoted, an SSID may contain spaces (`ssid=St Marys Staff`): the value
    # runs to the next `key=`, a list separator or the end of the line, so no
    # word of the name is left behind.
    ("SSID", re.compile(r"(?i)\b((?:ssid|wifi[_-]?(?:name|ssid)|network[_-]?name)\s*[\"']?\s*[=:]\s*)"
                        r"(\"[^\"\n]{1,64}\"|'[^'\n]{1,64}'"
                        r"|[^\s,;|\"'][^,;|\"'\n]{0,63}?(?=\s+[\w.-]+\s*[=:]|\s*[,;|)\]]|\s*$))"), "keyed"),
    ("SSID", re.compile(r"(?i)\b(ssid\s+)(\"[^\"\n]{1,64}\"|'[^'\n]{1,64}')"), "keyed"),
    # Omni-family discovery logs a peer's display name as bare free text —
    # `Peer discovered: Room 3 (<id>) at …` and `Peer Room 3 at <ip> stopped
    # answering keep-alive` — so neither rule above sees it. Both shapes are
    # anchored on the text that follows the name, never on the name itself: a
    # free-text name has no alphabet to match, only a known end. A quoted or
    # already-placeholdered name is left to the rule above.
    ("NAME", re.compile(
        r"(?i)\b(peer\s+discovered:\s+)([^\s\"'<(][^\n\"(]{0,79}?)(?=\s+\()"), "keyed"),
    ("NAME", re.compile(
        r"(?i)\b(peer\s+)([^\s\"'<(][^\n\"(]{0,79}?)(?=\s+at\s+\S+\s+stopped\s+answering\b)"), "keyed"),
    # A short value under one of these keys is not a counter, it is the whole
    # secret: `roomPin=123` was emitted verbatim under the trust marker, while
    # the skill and the runbook both promise room PINs are pseudonymised. The
    # general ID rule below needs four characters and the keyed handler exempts
    # one-to-three digits, so a short PIN cleared both. Same ID category, so a
    # PIN keeps one placeholder however often it appears.
    ("ID", re.compile(
        r"(?i)\b((?:(?:room[_-]?(?:pin|code)|pin(?:[_-]?code)?|passcode|pass[_-]?code|pairing[_-]?code|activation[_-]?code|access[_-]?code|join[_-]?code|invite[_-]?code|otp|one[_-]?time[_-]?(?:code|password)))\s*[\"']?\s*[=:]\s*)"
        r"(\"[^\"\n]{1,80}\"|'[^'\n]{1,80}'|<[^>\n]{1,80}>|[A-Za-z0-9][A-Za-z0-9:._-]{0,80})"), "keyed"),
    # Android `getprop`, which every bugreport carries: `[ro.serialno]: [R58M…]`.
    # The key is bracketed, so the `key: value` rules below never see it.
    ("ID", re.compile(
        r"(?i)(\[(?:ro\.(?:boot\.|vendor\.boot\.)?serialno|ril\.serialnumber|sys\.serialnumber|"
        r"persist\.sys\.device_name|net\.hostname|ro\.boot\.(?:wifi|bt)macaddr|"
        r"persist\.(?:vendor\.)?(?:bluetooth|bt)\.(?:name|address))\]:\s*\[)([^\]\n]{1,80})(?=\])"), "keyed"),
    # A serial number in free text (`device serial R58M123ABCD connected`):
    # only a token that has a digit in it, so `serial port` stays prose.
    # Also the keyed spelling with a space in the key: `Serial number: R58M…`.
    ("ID", re.compile(r"(?i)\b(serial(?:[ _-]?(?:no|number|#))?\s*(?:[:=]\s*|\s))"
                      r"((?=[A-Za-z0-9-]*\d)[A-Za-z0-9][A-Za-z0-9-]{5,40})\b"),
     "keyed"),
    ("ID", re.compile(
        r"(?i)\b((?:serial(?:[_-]?n(?:o|umber))?|device[_-]?id|android[_-]?id|hw[_-]?id|hardware[_-]?id|imei|udid|uuid|"
        r"machine[_-]?id|installation[_-]?id|install[_-]?id|client[_-]?id|user[_-]?id|uid|account[_-]?id|tenant[_-]?id|"
        r"session(?:[_-]?id)?|meeting[_-]?id|room[_-]?(?:code|id|pin)|pin(?:[_-]?code)?|pairing[_-]?code|"
        r"licen[cs]e[_-]?id|activation[_-]?(?:code|id)|mac(?:[_-]?address)?)\s*[\"']?\s*[=:]\s*)"
        # `<…>` is accepted as a value shape too: it is ordinary log syntax, and
        # only our own placeholders are then left alone by PLACEHOLDER_RE.
        r"(\"[^\"\n]{3,80}\"|'[^'\n]{3,80}'|<[^>\n]{1,80}>|[A-Za-z0-9][A-Za-z0-9:._-]{3,80})"), "keyed"),
    ("MAC", re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), "pseudo"),
    # IPv6: full 8-group form, or any compressed form containing "::" (timestamps never match)
    ("IPV6", re.compile(
        r"(?<![:\w.])(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){1,7}:(?![:\w])|"
        r"(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}|"
        r"(?:[0-9a-fA-F]{1,4}:){1,4}(?::[0-9a-fA-F]{1,4}){1,3}|(?:[0-9a-fA-F]{1,4}:){1,3}(?::[0-9a-fA-F]{1,4}){1,4}|"
        r"(?:[0-9a-fA-F]{1,4}:){1,2}(?::[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:(?::[0-9a-fA-F]{1,4}){1,6}|"
        r":(?::[0-9a-fA-F]{1,4}){1,7})(?![:\w.])"), "pseudo"),
    ("IPV4", re.compile(r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?::\d{1,5})?(?![\w.])"), "ipv4"),
    ("UUID", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "pseudo"),
    ("PHONE", re.compile(r"(?<![\w.])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?![\w.])"), "pseudo"),
    # The user-home component of a path, in every spelling a log uses: either
    # slash after the drive (`C:/Users/x`, `C:\Users\x`), JSON-escaped
    # (`C:\\Users\\x`), as a URL (`file:///C:/Users/x`), through WSL
    # (`/mnt/c/Users/x`), after any separator a logger puts in front
    # (`path:/home/x`), and a Windows account name with spaces in it.
    # The well-known shared profiles are not anyone's name.
    ("USER", re.compile(
        r"(?i)((?<![\w.-])(?:file:/{2,3})?(?:[a-z]:)?(?:\\\\|\\|/)(?:users|home|documents and settings)(?:\\\\|\\|/)"
        r"|(?<![\w.-])/mnt/[a-z]/(?:users|home)/)"
        r"(?!(?:public|default|default user|all users|shared)(?:[\\/\"'\s]|$))"
        # A name with spaces ends at the next separator, at the closing quote
        # of a complete quoted path (`path="C:\\Users\\Fran Lopez"`), or at
        # the end of the line (`home=C:\Users\Fran Lopez`). Over-matching a
        # trailing word here costs readability; under-matching leaks a name.
        # A profile name may carry an apostrophe (`O'Connor`) or a suffix in
        # brackets (`Jane Doe (School)`): the whole component goes.
        r"((?:" + _PROFILE_WORD + r" ){1,3}" + _PROFILE_WORD + r"(?=[\\/]|[\"'](?!\w)|[ \t]*$)"
        r"|(?:[^\\/\s\"'<>|:*?]|(?<=\w)'(?=\w))+)"), "keyed"),
    # A Windows account, `DOMAIN\user` (JSON-escaped too). NT AUTHORITY,
    # BUILTIN and the service accounts are the system, not a person; those
    # exclusions ignore case, as Windows does.
    # In free text the domain must be upper case: a lower-case `word\word` is
    # far more often an escape inside a JSON string (`"failed\nretrying"`)
    # than an account, and matching it would mangle every such message.
    ("USER", re.compile(
        r"(?<![\w\\/.:-])((?!" + _WIN_SYSTEM_DOMAINS + r"\\)"
        r"[A-Z][A-Z0-9-]{1,14}\\{1,2})"
        r"(?!" + _WIN_SYSTEM_USERS + r"\b)([A-Za-z][\w.$-]{1,63})(?![\w\\])"),
     "keyed"),
    # …and in any case when a key says it is an account: `user=acme\jsmith`,
    # `Logon user acme\jsmith`, `"account": "acme\\jsmith"`.
    ("USER", re.compile(
        r"(?i)\b((?:user(?:[_ -]?name)?|account(?:[_ -]?name)?|login|logon(?:\s+user)?|principal|identity|"
        r"run\s*as|owner|upn|sam(?:[_ -]?account(?:[_ -]?name)?)?)\s*[\"']?\s*[=:]?\s*[\"']?)"
        r"((?!" + _WIN_SYSTEM_DOMAINS + r"\\)[a-z][a-z0-9-]{1,14}\\{1,2}"
        r"(?!" + _WIN_SYSTEM_USERS + r"\b)[a-z][\w.$-]{1,63})(?![\w\\])"), "keyed"),
    # A UNC share names the file server: `\\FILESRV01\teachers$`.
    # Only where a path can START: after a JSON-escaped path component
    # (`…\\<USER_1>\\AppData\\`) the same backslashes are a separator.
    ("INTERNAL_HOST", re.compile(r"(?:^|(?<=[\s\"'=(\[,]))((?:\\\\){1,2})([A-Za-z0-9][A-Za-z0-9-]{0,62})(?=\\)"),
     "keyed"),
    # Windows' generated machine names, which reach logs without any key.
    ("INTERNAL_HOST", re.compile(r"\b(?:DESKTOP|LAPTOP|WIN|PC)-[A-Z0-9]{5,15}\b"), "pseudo"),
    # Not a package or a file that merely contains the word: every Android
    # crash carries `com.android.internal.os`, JVM traces `jdk.internal` and
    # `kotlinx.coroutines.internal`, and .NET loads `appsettings.Local.json`.
    # A host inside a real domain (`db.internal.acme.com`) still matches.
    ("INTERNAL_HOST", re.compile(
        r"(?i)(?<![\w.-])(?!(?:com|org|net|java|javax|jdk|kotlin|kotlinx|android|androidx|dalvik|sun|io|dev|libcore)\.)"
        r"[a-z0-9](?:[a-z0-9-]{0,62}\.)+(?:local|lan|internal|corp|intranet|home|localdomain)\b"
        r"(?!\.(?:json|xml|ya?ml|config|conf|ini|txt|props|properties|cs|js|ts|kt|java|py)\b|[($]|\s*=)"), "pseudo"),
    ("LONG_HEX", re.compile(r"\b(?:0x)?[0-9a-fA-F]{32,}\b"), "pseudo"),
    # The value may follow a key delimiter (`opaque=<value>`); the lookbehind
    # used to swallow `opaque=` into the match and replace the key along with
    # the value, which destroyed the line for debugging.
    # `=` is a key delimiter far more often than it is base64 padding, so it is
    # allowed before the value and only as trailing padding inside it. Before,
    # the whole `opaque=<value>` ran as one match and the key was replaced too,
    # which destroyed the line for debugging.
    ("HIGH_ENTROPY", re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/=_-])"), "entropy"),
]

# Categories that redact credentials outright. The marker header is a trust
# signal — the raw-log guard lets a marked file through — so a run must never
# be able to stamp it on output from which secret rules were switched off.
UNDISABLEABLE = {"JWT", "AUTH_HEADER", "BEARER", "URL_CREDENTIALS", "AWS_KEY", "GITHUB_TOKEN",
                 "SLACK_TOKEN", "OPENAI_KEY", "GOOGLE_KEY", "AZURE_CONN", "SECRET_KV", "PRIVATE_KEY", "OAUTH"}

# IPs that are never sensitive and are useful verbatim while debugging.
_IPV4_KEEP = re.compile(r"^(?:0\.0\.0\.0|127\.\d+\.\d+\.\d+|255\.255\.255\.255|224\.0\.0\.\d+|239\.255\.255\.250)(?::\d+)?$")
_AUTH_PROSE_RE = re.compile(r"(?i)failed|denied|required|missing|invalid|error|errors|header|ok|success|"
                            r"succeeded|granted|pending|none|null|not|is|was|has|expired")
# The IPv6 loopback and the unspecified address, as promised for IPv4.
_IPV6_KEEP = {"::1", "::"}
# A .NET assembly or NuGet package name before a four-part version:
# `Loaded Microsoft.Extensions.Logging 6.0.0.0` is a version, not an address.
# Only with the words that say an assembly or package is meant: a dotted
# PascalCase name alone proves nothing (`Connected to School.Service
# 10.1.2.3` is an address after a service name).
_PASCAL_NS_CTX = re.compile(
    r"(?i:\b(?:load(?:s|ed|ing)?|assembl(?:y|ies)|package|nuget|referenc\w*|dependenc\w*|install\w*|"
    r"restor\w*|resolv\w*|upgrad\w*|updat\w*)\b)[^\n]{0,80}?[\s'\"(]"
    r"(?:[A-Z][A-Za-z0-9]*\.)+[A-Z][A-Za-z0-9]*[,\s]+(?:Version=|v)?$")
# A dotted quad right after one of these words is a version number, not an address.
_VERSION_CTX = re.compile(
    r"(?i)(?:\bv(?:er(?:sion)?)?\.?\s*[=:]?\s*|\b(?:build|release|firmware|fw|sdk|app|client|"
    r"montage|launcher|omni|broadcast|central\s*management|qt|android|ios|windows|macos|chrome(?:os)?|electron|"
    r"webos|tizen|tvos)\s*[=:]?\s*)$")
# What this tool emits: <TAG_1> and <REDACTED:CATEGORY>. Nothing else counts as
# "already scrubbed", or a log writing `password=<secret>` would exempt itself.
_SHORT_CODE_KEY_RE = re.compile(r"(?i)^\s*(?:room[_-]?(?:pin|code)|pin(?:[_-]?code)?|passcode|pass[_-]?code|pairing[_-]?code|activation[_-]?code|access[_-]?code|join[_-]?code|invite[_-]?code|otp|one[_-]?time[_-]?(?:code|password))\b")

# What may follow one of our placeholders and still count as the same value:
# a JID resource, a port, a path segment, an extension. No whitespace, because
# a space is where a second value starts.
_DECORATION_ONLY_RE = re.compile(r"[/:._\-][^\s\"']*|")

PLACEHOLDER_RE = re.compile(r"<(?:[A-Z][A-Z0-9_]*_\d+|REDACTED:[A-Z][A-Z0-9_]*)>")

# File hashes: kept in hex or base64 after an explicit hash label.
_HASH_CTX = re.compile(r"(?i)(?:sha-?\d*|md5|hash|checksum|digest|fingerprint|etag)\W{0,4}$")
# A git object id is no more personal than a file hash, and a CI log is
# useless without it: `commit 4f2a…`, `revision=…`, `parent …`. These labels
# vouch for HEX ids only — `object=<opaque token>` is still a token.
_GIT_OID_CTX = re.compile(r"(?i)(?:commit|revision|rev|parent|tree|object)\W{0,4}$")
# Code identifiers long enough to look like tokens: JNI symbols in tombstones
# (`Java_com_displaynote_montage_receiver_NativeDecoder_initDecoder`) and
# source paths (`/src/main/java/com/displaynote/montage/MainActivity`). Every
# component has to read as a word, so an opaque value never fits.
# A component reads as a word: lowercase, or CamelCase whose humps are real
# words (3+ lowercase letters each) — `MainActivity`, `initDecoder`. A run of
# one-letter humps (`QwErTy…`) is the shape of a random token, not a name.
_WORD = r"[A-Za-z][a-z]{2,}(?:[A-Z][a-z]{2,})*[0-9]*"
_IDENT_JNI_RE = re.compile(r"^(?:" + _WORD + r"_){3,}" + _WORD + r"(?:\+\d+)?$")  # `+124`: offset in a frame
_IDENT_PATH_RE = re.compile(r"^/?(?:(?:[a-z][a-z0-9_-]{0,23}|" + _WORD + r")/){2,}" + _WORD + r"(?:\.[a-z0-9]{1,6})?$")


def _is_code_identifier(s: str) -> bool:
    """A JNI symbol or a source path, not a token that happens to be long.

    Shape alone was not enough: `/api/v1/session/<token>` has a path's shape,
    and a token in its last component went out verbatim. So every component
    must also be short and read like a word (low entropy): a 32-character
    token is neither, and a random 16-character one fails the entropy test.
    """
    if not (_IDENT_JNI_RE.match(s) or _IDENT_PATH_RE.match(s)):
        return False
    parts = [p for p in re.split(r"[/_]", s.split("+", 1)[0]) if p]
    return all(len(p) <= 24 and _shannon(p) < 3.6 for p in parts)


def _is_path_prefix(head: str) -> bool:
    """`/api/v1/session`: short, word-like components a route is made of."""
    parts = [p for p in head.split("/") if p]
    return bool(parts) and all(re.fullmatch(r"[A-Za-z0-9_-]{1,24}", p) and _shannon(p) < 3.6 for p in parts)


# Cheap tests that a line COULD match a category, checked before its rules
# run. Every one is a superset of what the rules themselves need — a missed
# prefilter would be a leak, so each is the rule's own unavoidable anchor (an
# `@` for an e-mail, the key word followed by `=`/`:` for a keyed rule). The
# keyed rules scan every word boundary of every line, and on ordinary log
# lines nothing they need is there: this is most of the speed-up.
def _has(*needles):
    return lambda line, low: any(n in line for n in needles)


def _has_low(*needles):
    return lambda line, low: any(n in low for n in needles)


def _rx(pattern):
    r = re.compile(pattern)
    return lambda line, low: r.search(line) is not None


def _keyed(*words):
    """A key word somewhere, and a `=` or `:` for it to be the key of."""
    return lambda line, low: ("=" in line or ":" in line) and any(w in low for w in words)


_PRE = {
    "JWT": _has("eyJ"),
    "AUTH_HEADER": _has_low("authoriz"),
    "BEARER": _has_low("bearer"),
    "URL_CREDENTIALS": lambda line, low: "://" in line and "@" in line,
    "PRIVATE_KEY": _has("MII"),
    "OAUTH": _rx(r"(?i)[?&#](?:code|state|nonce|id_token_hint|session_state)"),
    "AWS_KEY": _has("AKIA", "ASIA", "AGPA", "AIDA", "AROA", "ANPA"),
    "GITHUB_TOKEN": _has("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"),
    "SLACK_TOKEN": _has("xox"),
    "OPENAI_KEY": _has("sk-"),
    "GOOGLE_KEY": _has("AIza"),
    "AZURE_CONN": lambda line, low: "=" in line and any(
        w in low for w in ("accountkey", "sharedaccess", "password", "pwd", "sig")),
    "SECRET_KV": _keyed("key", "secret", "pass", "pwd", "token", "bearer", "authoriz", "sas", "sig",
                        "licen", "session", "sessid", "sid", "cookie"),
    "EMAIL": _has("@"),
    "NAME": lambda line, low: '"' in line or "'" in line or "peer" in low or _keyed(
        "name", "attendee", "participant", "presenter", "moderator", "owner", "organi", "company",
        "customer", "school", "workstation")(line, low),
    "SSID": _has_low("ssid", "wifi", "network"),
    "ID": lambda line, low: "serial" in low or "]: [" in line or _keyed(
        "pin", "code", "otp", "password", "id", "imei", "uuid", "session", "mac", "address")(line, low),
    "MAC": _rx(r"[0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-]"),
    "IPV6": lambda line, low: "::" in line or line.count(":") >= 7,
    "IPV4": _rx(r"\d\.\d{1,3}\.\d"),
    "UUID": _rx(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"),
    "PHONE": _has("+"),
    "USER": lambda line, low: "\\" in line or "users" in low or "home" in low or "documents and" in low,
    "INTERNAL_HOST": _has_low(".local", ".lan", ".internal", ".corp", ".intranet", ".home", "\\\\",
                              "desktop-", "laptop-", "win-", "pc-"),
    "LONG_HEX": _rx(r"[0-9a-fA-F]{32}"),
    "HIGH_ENTROPY": _rx(r"[A-Za-z0-9+/_-]{32}"),
}

_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")

# Common words/tokens that pass the entropy test but are not secrets.
_ENTROPY_MIN_BITS = 4.0
_B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
# A whole line that is nothing but base64: the continuation of a wrapped key.
_B64_LINE_RE = re.compile(r"^\s*[A-Za-z0-9+/]{16,}={0,2}\s*$")
# Only shapes a human actually writes. The previous `[A-Za-z]+` exempted ANY
# run of letters, and `(?:[A-Z][a-z]+){2,}` accepted one-letter "words", so a
# 32+ character opaque credential like `QwErTyUiOpAsDf…` skipped the entropy
# check entirely and went out under a trusted marker. Identifiers keep their
# exemption: lowercase runs, digits, and CamelCase whose words are real ones
# (2+ lowercase letters each), so `AbstractSingletonProxyFactoryBean` survives.
# The bare `[a-z]+` exemption also covered a 32-character random lowercase
# token, which is what an API or session key usually looks like. Dropped: a
# genuine run-on of words has low enough entropy that the Shannon check keeps
# it anyway, so nothing that reads as English is lost.
_ENTROPY_SKIP = re.compile(r"^(?:[0-9]+|(?:[A-Z][a-z]{2,}){2,})$")


def _looks_like_der(s: str) -> bool:
    """True when a base64 run decodes to a plausible DER key or certificate.

    Matching prefixes (`MII`, `MHc`, `MIGH`, …) is a guessing game; every DER
    structure opens with an ASN.1 SEQUENCE tag, so decode a little and look.
    """
    if len(s) < 40 or not _B64_RE.match(s):
        return False
    try:
        raw = _b64.b64decode(s + "=" * (-len(s) % 4), validate=False)
    except Exception:
        return False
    return len(raw) >= 48 and raw[:1] == b"\x30"


def _shannon(s: str) -> float:
    if not s:
        return 0.0
    freq: Dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = float(len(s))
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


class Scrubber:
    """Stateful scrubber: placeholder numbering and the value map persist for
    the lifetime of the instance, so several files scrubbed by one instance
    share placeholders."""

    def __init__(self, keep_paths: bool = False, extra_domains: Iterable[str] = (),
                 disable: Iterable[str] = ()):
        self.map: Dict[str, Dict[str, str]] = {}      # category -> {value: placeholder}
        # Output ranges produced by a substitution in the line being scrubbed.
        # Reset per line by scrub_line().
        self._spans: List[Tuple[int, int]] = []
        self.stats: Dict[str, int] = {}
        self.keep_paths = keep_paths
        requested = {d.upper() for d in disable}
        refused = requested & UNDISABLEABLE
        if refused:
            raise ValueError(
                "these categories redact credentials and cannot be disabled: "
                + ", ".join(sorted(refused))
                + ". Disabling them would emit live secrets into a file that still "
                  "carries the dn_logscrub marker, which downstream tooling trusts.")
        self.disabled = requested
        self._in_pem = False
        self._in_der = False
        # (kind, indent) of a secret key whose value is on a later line.
        self._pending: Optional[Tuple[str, int]] = None
        self.rules = list(RULES)
        self._pre = dict(_PRE)
        # Per call, not per instance: what the last scrub_text() redacted, for
        # the trailer finalize() writes.
        self.last_stats: Dict[str, int] = {}
        raw_doms = [d.strip().lower() for d in extra_domains if d.strip()]
        doms = [re.escape(d) for d in raw_doms]
        if doms:
            self._pre["DOMAIN"] = lambda line, low, ds=tuple(raw_doms): any(d in low for d in ds)
            # Customer / DisplayNote-internal domains (and every sub-domain of them)
            rx = re.compile(r"(?i)\b(?:[a-z0-9-]+\.)*(?:" + "|".join(doms) + r")\b")
            # Insert before INTERNAL_HOST so it wins over generic matches.
            idx = next(i for i, r in enumerate(self.rules) if r[0] == "INTERNAL_HOST")
            self.rules.insert(idx, ("DOMAIN", rx, "pseudo"))

    # -- placeholder bookkeeping -------------------------------------------
    def _count(self, cat: str) -> None:
        self.stats[cat] = self.stats.get(cat, 0) + 1

    def _pseudo(self, cat: str, value: str) -> str:
        bucket = self.map.setdefault(cat, {})
        key = value.lower() if cat in ("EMAIL", "INTERNAL_HOST", "DOMAIN", "MAC", "UUID", "LONG_HEX") else value
        ph = bucket.get(key)
        if ph is None:
            ph = f"<{cat}_{len(bucket) + 1}>"
            bucket[key] = ph
        self._count(cat)
        return ph

    def _redact(self, cat: str) -> str:
        self._count(cat)
        return f"<REDACTED:{cat}>"

    # -- per-rule substitution ---------------------------------------------
    def _apply(self, text: str, cat: str, rx: "re.Pattern[str]", mode: str) -> str:
        if cat in self.disabled:
            return text
        if cat == "USER" and self.keep_paths:
            return text
        # Nothing to rewrite: the text and the recorded spans both stand.
        if rx.search(text) is None:
            return text

        def sub(m: "re.Match[str]") -> str:
            whole = m.group(0)
            if PLACEHOLDER_RE.fullmatch(whole):
                return whole  # already one of ours
            if mode == "redact":
                return self._redact(cat)
            if mode == "keyed_redact":
                val = m.group(2) if m.lastindex and m.lastindex >= 2 else whole[len(m.group(1)):]
                if re.fullmatch(r"(?i)<REDACTED:[A-Z_]+>", val):
                    return whole  # already redacted by an earlier rule
                # A bare scheme word is only meaningful under an authorization
                # key, and that is the one place it is not a credential. Keyed
                # on the key, not on the rule: shared with every SECRET_KV key
                # it made `token=token` and `password=basic` look like schemes
                # and left a live credential in the output.
                if re.match(r"(?i)\s*(?:authorization|bearer)\b", m.group(1)) and re.fullmatch(
                        r"(?i)(?:bearer|basic|digest|token|negotiate|ntlm)", val):
                    return whole
                # …and under the same keys a word of prose is not one either:
                # `Authorization: failed for request 42`.
                if (re.match(r"(?i)\s*(?:authorization|bearer)\b", m.group(1)) and _AUTH_PROSE_RE.fullmatch(val)
                        and re.match(r"[ \t]+[a-z]", text[m.end():])):
                    return whole  # …but only with the sentence that follows it
                return m.group(1) + self._redact(cat)
            if mode == "url_creds":
                self._count(cat)
                return f"{m.group(1)}<REDACTED:URL_CREDENTIALS>@"
            if mode == "keyed":
                key, val = m.group(1), m.group(2)
                quote = ""
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    quote, val = val[0], val[1:-1]
                # `match`, not `fullmatch`: a value that BEGINS with one of
                # our placeholders is a decorated form of a value some earlier
                # rule already handled — a JID with its resource
                # (`<EMAIL_1>/web`), a host with a port, a URL with a path.
                # Re-labelling it minted a SECOND placeholder for the same
                # original, so the same JID came out as <NAME_1> inside a
                # from="…" and as <EMAIL_1> everywhere else, breaking the one
                # guarantee the tool makes: one value, one placeholder.
                # Anchored at the start on purpose — `name="Jane Doe <EMAIL_1>"`
                # still carries a real name of its own and must be redacted.
                # Does this value BEGIN with characters this run produced?
                # `self._spans` holds the output ranges of every substitution
                # made in this line so far, so the question is answered by
                # position rather than by what the text looks like.
                vstart = m.start(2) + (1 if quote else 0)
                # Inside a span, not starting one: a keyed rule replaces the
                # KEY along with the value, so the span begins at the key.
                if any(a <= vstart < b for a, b in self._spans):
                    return whole  # already one of ours
                # Angle brackets are ordinary log syntax — `user=<unknown>`,
                # `name=<Jane Doe>` — so anything that is not one of our own
                # placeholders is a real value and gets pseudonymised.
                # `session_id=3` is a counter and stays readable; `roomPin=3`
                # is a credential. The exemption is scoped by the KEY, not by
                # the shape of the value.
                if (cat == "ID" and not _SHORT_CODE_KEY_RE.match(key)
                        and re.fullmatch(r"(?i)(?:true|false|null|none|nil|n/a|\d{1,3})", val)):
                    return whole  # not an identifier
                return f"{key}{quote}{self._pseudo(cat, val)}{quote}"
            if mode == "ipv4":
                host, _, port = whole.partition(":")
                if _IPV4_KEEP.match(whole):
                    return whole
                if _VERSION_CTX.search(text[max(0, m.start() - 12):m.start()]):
                    return whole  # "version 3.4.1.12" is not an IP
                if _PASCAL_NS_CTX.search(text[max(0, m.start() - 200):m.start()]):
                    return whole  # "Microsoft.Extensions.Logging 6.0.0.0" is not either
                ph = self._pseudo(cat, host)
                return f"{ph}:{port}" if port else ph
            if mode == "entropy":
                # Key material must never become a reversible placeholder: that
                # writes the key itself into the .dnmap. DER blobs start with an
                # ASN.1 SEQUENCE (0x30) whatever their base64 prefix — MII, MIG,
                # MHc, MFk — so decode rather than guess at prefixes.
                if _looks_like_der(whole):
                    self._count("PRIVATE_KEY")
                    return "<REDACTED:PRIVATE_KEY>"
                if _ENTROPY_SKIP.match(whole) or _is_code_identifier(whole):
                    return whole
                # A token at the end of an ordinary path (`/api/v1/session/<t>`):
                # only the token goes, so the route stays readable.
                head, sep, tail = whole.rpartition("/")
                if sep and tail and _is_path_prefix(head):
                    if len(tail) < 8 or _ENTROPY_SKIP.match(tail) or _shannon(tail) < 3.0:
                        return whole
                    return head + "/" + self._pseudo("TOKEN", tail)
                if _shannon(whole) < _ENTROPY_MIN_BITS:
                    return whole
                if _HASH_CTX.search(text[max(0, m.start() - 24):m.start()]):
                    return whole  # a base64 sha256= / etag= is a file hash, like the hex form
                return self._pseudo("TOKEN", whole)
            if cat == "LONG_HEX" and _HASH_CTX.search(text[max(0, m.start() - 24):m.start()]):
                return whole  # sha256=/md5= file hashes are not identifiers
            if (cat == "LONG_HEX" and re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", whole)
                    and _GIT_OID_CTX.search(text[max(0, m.start() - 24):m.start()])):
                return whole  # a full SHA-1 / SHA-256 git object id after a git label
            if cat == "IPV6" and whole in _IPV6_KEEP:
                return whole
            return self._pseudo(cat, whole)

        # Rewritten by hand instead of `rx.sub` so the output positions this
        # rule produced can be recorded. Asking whether a value "is" a
        # placeholder, or whether that string was emitted earlier, are both
        # guesses: a raw log can contain the text `<EMAIL_1>`, and a name can
        # follow one without any whitespace. Position cannot be forged —
        # either these characters came out of a substitution in this line or
        # they were in the input.
        out, spans, outlen, pos = [], [], 0, 0

        def carry(lo: int, hi: int, at: int) -> None:
            for a, b in self._spans:
                if a >= lo and b <= hi:
                    spans.append((a - lo + at, b - lo + at))

        for m in rx.finditer(text):
            chunk = text[pos:m.start()]
            out.append(chunk)
            carry(pos, m.start(), outlen)
            outlen += len(chunk)
            rep = sub(m)
            if rep == m.group(0):
                carry(m.start(), m.end(), outlen)
            else:
                spans.append((outlen, outlen + len(rep)))
            out.append(rep)
            outlen += len(rep)
            pos = m.end()
        out.append(text[pos:])
        carry(pos, len(text), outlen)
        self._spans = spans
        return "".join(out)

    # -- public API ----------------------------------------------------------
    def scrub_line(self, line: str) -> str:
        # Positions are per line: a placeholder produced on an earlier line
        # says nothing about the same text appearing raw on this one.
        self._spans = []
        # An unwrapped DER key is often pasted wrapped across lines: only the
        # first carries a recognisable prefix, and the continuations are plain
        # base64 that fell through to the entropy rule and were pseudonymised —
        # writing the rest of the key into the .dnmap.
        if self._in_der:
            if _B64_LINE_RE.match(line):
                self._count("PRIVATE_KEY")
                nl = "\n" if line.endswith("\n") else ""
                return "<REDACTED:PRIVATE_KEY>" + nl
            self._in_der = False
        # Multi-line PEM private keys: drop everything between BEGIN/END.
        if self._in_pem:
            if _PEM_END.search(line):
                self._in_pem = False
            return ""
        if _PEM_BEGIN.search(line):
            self._count("PRIVATE_KEY")
            self._in_pem = not bool(_PEM_END.search(line))
            nl = "\n" if line.endswith("\n") else ""
            return "<REDACTED:PRIVATE_KEY>" + nl
        original = line
        # The value of a secret key left at the end of an earlier line.
        if self._pending is not None:
            kind, key_indent = self._pending
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" \t"))
            nl = "\n" if line.endswith("\n") else ""
            if not stripped:
                return line  # blank lines keep the key pending
            if kind == "block" and indent > key_indent:
                self._count("SECRET_KV")  # every line of a YAML block scalar
                return line[:indent] + "<REDACTED:SECRET_KV>" + nl
            self._pending = None
            # Only a value that CONTINUES the key: indented, or a quoted JSON
            # value. A new log line starts at column 0 with its timestamp and
            # is left alone, and so is a nested key (`policy: strict`).
            if kind == "next" and (indent > 0 or stripped[:1] in "\"'") and not _NESTED_KEY_RE.match(line):
                m = _NEXT_VALUE_RE.match(line)
                if m and not PLACEHOLDER_RE.fullmatch(m.group(2)):
                    self._count("SECRET_KV")
                    line = m.group(1) + "<REDACTED:SECRET_KV>" + line[m.end():]
        before_key = self.stats.get("PRIVATE_KEY", 0)
        low = line.lower()
        pre = self._pre
        # Once per category per line: several rules share a category, and a
        # substitution only ever replaces text with a placeholder, which can
        # remove an anchor but never add one.
        verdict: Dict[str, bool] = {}
        for cat, rx, mode in self.rules:
            ok = verdict.get(cat)
            if ok is None:
                check = pre.get(cat)
                ok = verdict[cat] = check is None or check(line, low)
            if not ok:
                continue
            new = self._apply(line, cat, rx, mode)
            if new is not line:
                line, low = new, new.lower()
        if self.stats.get("PRIVATE_KEY", 0) > before_key:
            self._in_der = True  # continuations of the same wrapped key follow
        # A secret key with its value still to come. Judged on the line as it
        # came in: the one-line rule may already have taken a YAML block
        # indicator (`password: |`) for the value. Cheap test first: such a
        # line ends in a separator, a block indicator or a scheme word.
        tail = original.rstrip()
        if tail and (tail[-1] in ":=|>-+" or tail[-1:].isalpha()):
            m = _PENDING_SECRET_RE.search(tail)
            if m:
                self._pending = ("block" if m.group(1) else "next", len(line) - len(line.lstrip(" \t")))
        return line

    def scrub_text(self, text: str) -> str:
        """Scrub a self-contained block of text.

        Mid-line state does not cross the call in either direction: an earlier
        input that ended inside an unterminated PEM block must not swallow this
        one (library callers reuse one Scrubber across files), and scrubbing a
        filename for the header must not leave the body being dropped. The
        placeholder maps are untouched, so `<EMAIL_1>` stays the same person
        across every call.
        """
        saved = (self._in_pem, self._in_der, self._pending)
        self._in_pem, self._in_der, self._pending = False, False, None
        before = dict(self.stats)
        try:
            return "".join(self.scrub_line(l) for l in io.StringIO(text))
        finally:
            self._in_pem, self._in_der, self._pending = saved
            self.last_stats = {k: v - before.get(k, 0) for k, v in self.stats.items() if v - before.get(k, 0)}

    def reset_line_state(self) -> None:
        """Forget mid-file state between inputs, keeping the placeholder maps.

        A file ending inside a PEM block used to swallow every later file in the
        same run — they still got a valid marker and trailer, so the loss was
        silent.
        """
        self._in_pem = False
        self._in_der = False
        self._pending = None

    def scrub_stream(self, src: Iterable[str], dst: Callable[[str], None]) -> None:
        for line in src:
            out = self.scrub_line(line)
            if out:
                dst(out)

    def _reductions(self) -> str:
        bits = sorted(self.disabled)
        if self.keep_paths:
            bits.append("keep-paths")
        return ",".join(bits)

    def _complete(self) -> bool:
        """True when every rule ran, which is what the marker asserts."""
        return not self.disabled and not self.keep_paths

    def trailer(self, file_stats: dict, interrupted: bool = False) -> str:
        # `interrupted`: the source stopped early (Ctrl-C, a timeout, a stream
        # that never ends). Every line written was scrubbed before it was, so
        # the file is clean — it is only incomplete, and says so.
        total = sum(file_stats.values())
        cats = ",".join(f"{k}={v}" for k, v in sorted(file_stats.items()))
        return f"# {MARKER} end | redactions={total} | {cats or 'none'}" + (" | interrupted" if interrupted else "") + "\n"

    def header(self, source_name: str, streaming: bool = False) -> str:
        # The filename itself can carry an e-mail, a customer or a ticket
        # holder's name; it goes through the same rules as the body so the
        # marker cannot reintroduce what the body just had removed.
        source_name = safe_label(self, source_name)
        total = sum(self.stats.values())
        cats = ",".join(f"{k}={v}" for k, v in sorted(self.stats.items()))
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # A run with rules switched off is NOT a fully scrubbed file, and the
        # guard trusts the marker on sight. Give it a different one so the
        # guard refuses it: --disable EMAIL/ID or --keep-paths leave personal
        # identifiers and user-home paths in place.
        marker = MARKER if self._complete() else f"{MARKER}-partial"
        return (f"# {marker} v{__version__} | source={source_name} | scrubbed={ts} | "
                + ("redactions=counted-in-trailer" if streaming else f"redactions={total} | {cats or 'none'}")
                + ("" if self._complete() else f" | PARTIAL: reduced={self._reductions()}")
                + "\n"
                f"# Placeholders are consistent within this run: the same original value always maps to the same <TAG_n>.\n")

    def finalize(self, scrubbed_text: str, source_name: str, stats: Optional[dict] = None) -> str:
        """Header + text + trailer: what the guard and `--check` accept.

        Without the trailer a library caller's output was refused by both, so
        every automated flow that wrote its result to a `.scrubbed.` file
        produced something nobody could open. `stats` defaults to what the
        last scrub_text() call redacted.
        """
        body = scrubbed_text if not scrubbed_text or scrubbed_text.endswith("\n") else scrubbed_text + "\n"
        # Taken first: header() scrubs the file name, which is a scrub_text() call too.
        counts = dict(self.last_stats if stats is None else stats)
        return self.header(source_name) + body + self.trailer(counts)

    def map_as_json(self) -> str:
        # placeholder -> original, per category (local reverse-lookup only)
        inv = {cat: {ph: val for val, ph in bucket.items()} for cat, bucket in self.map.items()}
        return json.dumps({"dn_logscrub": __version__, "WARNING": "contains original identifiers — never share",
                           "map": inv}, indent=2)


# --------------------------------------------------------------------------- #
# CLI helpers
# --------------------------------------------------------------------------- #

# The trailer the sanitiser writes as its LAST line. Checking only the header
# accepted a legitimately scrubbed file with raw content appended after it —
# `cat raw >> clean.scrubbed.log`, two files concatenated, a tool still
# writing. The header says the file STARTED clean; only the trailer says it
# still is, and that it is complete.
# The WHOLE trailer, not its prefix: `…| EMAIL=1` and `…| EMAIL=1token=sk-…`
# both start the same way, so matching the opening accepted raw data appended
# onto the trailer line itself, with no newline in front of it.
TRAILER_RE = re.compile(
    r"^#\s*dn_logscrub\s+end\s*\|\s*redactions=\d+\s*\|\s*"
    r"(?:none|[A-Z][A-Z0-9_]*=\d+(?:,[A-Z][A-Z0-9_]*=\d+)*)(?:\s*\|\s*interrupted)?\s*$")


def _ends_with_trailer(path: str, tail_bytes: int = 8192) -> bool:
    """Is the last non-empty line the sanitiser's trailer?

    Reads only the tail, so a multi-gigabyte scrubbed log costs nothing. Any
    error is False: this is a trust check, and an unreadable end is not proof
    of a good one.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - tail_bytes))
            chunk = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    for line in reversed(chunk.splitlines()):
        if line.strip():
            return bool(TRAILER_RE.match(line))
    return False


def is_scrubbed(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            # First line only, exactly like the raw-log guard: accepting the
            # marker further down would call a file scrubbed when line 1 is
            # still raw.
            if not MARKER_RE.match(fh.readline()):
                return False
    except OSError:
        return False
    # ...and the trailer must still be the end of it.
    return _ends_with_trailer(path)


def _is_system_link(owner: Optional[int], euid: Optional[int]) -> bool:
    """Can only the system have made a link owned by `owner`?

    Root ownership says so only to a process that is NOT root: run as root
    (a dev container, CI), every link a checkout creates is root's too, so
    ownership proves nothing and the link is refused like any other.
    """
    return euid is not None and euid != 0 and owner == 0


def _refuse_linked_parents(path: str, what: str) -> None:
    """Refuse if ANY existing parent component is a symlink.

    Checking only the immediate parent left `link/sub/out.log` open: `dirname`
    is `link/sub`, which is an ordinary directory, while `link` redirects the
    whole write somewhere else.
    """
    # abspath() always yields an absolute path, so the accumulator has to start
    # at the separator whatever the caller passed. Starting it empty for a
    # relative destination checked `repo/out` against the working directory
    # instead of `/repo/out`, and missed a symlinked relative parent.
    # splitdrive so `C:\\repo\\link\\out.log` starts at `C:\\` rather than at a
    # bare separator, which checked `\\repo\\link` — a path that does not exist.
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    acc = drive + os.path.sep
    # A link only root can create is the system's own layout, not a planted
    # redirect: macOS's /tmp, /var and /etc all point into /private, and
    # refusing them made every log under /tmp or $TMPDIR on a Mac impossible
    # to sanitise. Any other link is still refused — including one a cloned
    # repository brings with it, which belongs to the user. POSIX only
    # (Windows reports st_uid 0 for everything), and not when running as root.
    euid = os.geteuid() if hasattr(os, "geteuid") else None
    for part in rest.split(os.path.sep)[1:-1]:
        acc = os.path.join(acc, part)
        if os.path.islink(acc):
            try:
                owner = os.lstat(acc).st_uid
            except OSError:
                owner = None
            if _is_system_link(owner, euid):
                continue
            raise SystemExit(f"dn_logscrub: {acc} is a symlink; refusing to write the {what} "
                             f"through it.")


def _open_new(path: str, what: str):
    """Create a destination without following a link that is already there.

    Opening with "w" follows a pre-existing symlink, so a planted
    `app.scrubbed.log -> ~/.ssh/id_rsa` would have this tool overwrite that
    file. Nothing here appends to an existing destination, so removing a link
    first and creating the file fresh loses nothing.
    """
    _refuse_linked_parents(path, what)
    try:
        st = os.lstat(path)
        if not os.path.islink(path) and st.st_nlink > 1:
            # O_NOFOLLOW only stops symlinks. A hard link shares the inode, so
            # truncating here would rewrite whatever else points at it.
            raise SystemExit(
                f"dn_logscrub: {path} has {st.st_nlink} hard links; refusing to write the {what} "
                f"through it, since that would overwrite the other name too.")
    except FileNotFoundError:
        pass
    try:
        if os.path.islink(path):
            os.unlink(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except OSError as exc:
        raise SystemExit(f"dn_logscrub: cannot create the {what} at {path}: {exc}")
    return os.fdopen(fd, "w", encoding="utf-8")


def default_output(path: str) -> str:
    base, ext = os.path.splitext(path)
    if ext.lower() in (".gz", ".zip"):
        base, ext = os.path.splitext(base)
    return f"{base}.scrubbed{ext or '.txt'}"


# Containers whose members would be read as text: the result would carry a
# trusted marker while nothing inside it had been scrubbed. `.gz` alone is a
# single compressed stream and is handled below.
# Binary artefacts: reading them as UTF-8 with replacement would stamp a marker
# on something none of the rules could ever have matched.
# Single-stream compression the standard library cannot open.
_UNSUPPORTED_COMPRESSION_RE = re.compile(r"(?i)\.(?:zst|zstd|lz4|br|lzo|sz)$")

_BINARY_RE = re.compile(r"(?i)\.(?:dmp|etl|evtx|trace|core|hprof|pcap|pcapng|bin|dat)$")

_ARCHIVE_RE = re.compile(r"(?i)(?:\.(?:zip|tar|tgz|tbz2?|txz|7z|rar|jar|war|apk|aab|iso)$"
                         r"|\.tar\.(?:gz|bz2|xz|zst)$)")


def _refuse_non_utf8_bytes(head: bytes, label: str) -> None:
    """Refuse bytes this tool cannot actually scan.

    Everything is decoded as UTF-8 with replacement, so UTF-16 text becomes
    NUL-separated characters that no rule matches — and the output would still
    carry the marker, claiming a scan that never happened. Checked on the
    DECOMPRESSED bytes, and on stdin too: checking the container instead was
    checking the wrong thing.
    """
    if not head:
        return
    boms = ((b"\xff\xfe\x00\x00", "UTF-32LE"), (b"\x00\x00\xfe\xff", "UTF-32BE"),
            (b"\xff\xfe", "UTF-16LE"), (b"\xfe\xff", "UTF-16BE"))
    for bom, name in boms:
        if head.startswith(bom):
            raise SystemExit(
                f"dn_logscrub: {label}: this looks like {name} text. Every rule here works on "
                f"UTF-8, so nothing would match and the output would still carry a marker. "
                f"Convert it first: iconv -f {name} -t UTF-8 <file> > file.utf8.log")
    if head.count(b"\x00") > len(head) // 8:
        raise SystemExit(
            f"dn_logscrub: {label}: this does not look like UTF-8 text (many NUL bytes). The rules "
            f"would match nothing while the output still carried a marker. Convert or extract the "
            f"readable text first.")


def _peek_decompressed(opener, path: str) -> bytes:
    try:
        with opener(path, "rb") as fh:
            return fh.read(4096)
    except OSError:
        return b""


def _refuse_non_utf8(path: str, real: str) -> None:
    """Refuse text this tool cannot actually scan.

    Everything is opened as UTF-8 with replacement, so a UTF-16 log becomes
    NUL-separated characters that no rule matches — and the output would still
    be stamped with the marker, claiming a scan that never happened.
    """
    try:
        with open(real, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return
    _refuse_non_utf8_bytes(head, path)


def _open_text(path: str):
    # Classify by what the path resolves to: `debug.txt -> crash.dmp` is a
    # binary dump however it is spelled, and reading it as text would put a
    # trusted marker on bytes no rule ever saw. The original path is still what
    # gets opened and reported.
    real = os.path.realpath(os.path.expanduser(path))
    if _BINARY_RE.search(real):
        raise SystemExit(
            f"dn_logscrub: {path}: binary crash and diagnostic formats are not scrubbed as text — "
            f"their bytes are not lines, so the rules never see them and the output would carry a "
            f"trusted marker regardless. Extract the readable parts first, or keep the file local.")
    if _ARCHIVE_RE.search(real):
        raise SystemExit(
            f"dn_logscrub: {path}: archives are not read directly — their members would be treated "
            f"as text and left unscrubbed while the output still got a trusted marker. Extract it "
            f"first, then sanitise the extracted files (they can all go in one invocation so "
            f"placeholders stay consistent).")
    low = real.lower()
    if low.endswith(".gz"):
        import gzip
        _refuse_non_utf8_bytes(_peek_decompressed(gzip.open, path), path)
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    if low.endswith(".bz2"):
        import bz2
        _refuse_non_utf8_bytes(_peek_decompressed(bz2.open, path), path)
        return io.TextIOWrapper(bz2.open(path, "rb"), encoding="utf-8", errors="replace")
    if low.endswith(".xz") or low.endswith(".lzma"):
        import lzma
        _refuse_non_utf8_bytes(_peek_decompressed(lzma.open, path), path)
        return io.TextIOWrapper(lzma.open(path, "rb"), encoding="utf-8", errors="replace")
    _refuse_non_utf8(path, real)
    if _UNSUPPORTED_COMPRESSION_RE.search(low):
        # No stdlib decoder, and this tool stays stdlib-only. Reading the
        # compressed bytes as text would scan nothing and still stamp a marker.
        raise SystemExit(
            f"dn_logscrub: {path}: no decoder for this compression is available (stdlib only). "
            f"Decompress it first, then sanitise the result.")
    return open(path, "r", encoding="utf-8", errors="replace")


def run_cli(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="dn_logscrub", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="log files ('-' = stdin). Several files share one placeholder map.")
    ap.add_argument("-o", "--output", help="output path (single input only; default: <name>.scrubbed.<ext>)")
    ap.add_argument("--out-dir", metavar="DIR",
                    help="write every <name>.scrubbed.<ext> into DIR instead of next to its input "
                         "(for read-only inputs, and to keep scrubbed copies out of a repository)")
    ap.add_argument("--stdout", action="store_true", help="write scrubbed content to stdout instead of files")
    ap.add_argument("--map", metavar="FILE", help="write placeholder→original map here (LOCAL ONLY, never share)")
    ap.add_argument("--report", metavar="FILE", help="write JSON stats report")
    ap.add_argument("--domain", action="append", default=[], metavar="DOMAIN",
                    help="extra domain to pseudonymise (customer or internal), repeatable")
    ap.add_argument("--keep-paths", action="store_true", help="do not pseudonymise user-home path components")
    ap.add_argument("--disable", action="append", default=[], metavar="CATEGORY",
                    help="disable a category (e.g. IPV4, UUID), repeatable")
    ap.add_argument("--check", action="store_true", help="exit 0 if every input carries the dn_logscrub marker, 3 otherwise")
    ap.add_argument("--selftest", action="store_true", help="run built-in fixtures")
    ap.add_argument("--version", action="version", version=f"dn_logscrub {__version__}")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.inputs:
        ap.print_usage(sys.stderr)
        print("error: no input given (use '-' for stdin)", file=sys.stderr)
        return 1
    if args.check:
        # A placeholder map is never "scrubbed", whatever header it carries:
        # it is the table of original values.
        def _is_map(q: str) -> bool:
            if q.lower().endswith(".dnmap"):
                return True
            try:  # an alias resolving to a map is still the map
                return os.path.realpath(os.path.expanduser(q)).lower().endswith(".dnmap")
            except OSError:
                return False

        bad = [p for p in args.inputs if p == "-" or _is_map(p) or not is_scrubbed(p)]
        for p in bad:
            print(f"NOT SCRUBBED: {p}", file=sys.stderr)
        return 3 if bad else 0
    if args.output and len(args.inputs) != 1:
        print("error: -o/--output only valid with a single input (use --out-dir for several)", file=sys.stderr)
        return 1
    if args.output and args.out_dir:
        print("error: -o/--output and --out-dir are alternatives; pass one of them", file=sys.stderr)
        return 1
    if args.out_dir:
        try:
            _refuse_linked_parents(os.path.join(args.out_dir, "x"), "output directory")
            os.makedirs(os.path.expanduser(args.out_dir), exist_ok=True)
        except OSError as exc:
            print(f"error: cannot use --out-dir {args.out_dir}: {exc}", file=sys.stderr)
            return 1

    def _dest(src: str) -> str:
        if args.output:
            return args.output
        if args.out_dir:
            return os.path.join(os.path.expanduser(args.out_dir), os.path.basename(default_output(src)))
        return default_output(src)
    # The map is the one output that still holds the originals, so it must land
    # in a real file of its own — never on a stream the agent is reading
    # (`--map /dev/stdout` appended it to the scrubbed output; `/dev/stderr`
    # put it straight in the transcript) and never over an input or the output.
    if args.map:
        mp = os.path.realpath(os.path.expanduser(args.map))
        if args.map == "-" or mp.startswith("/dev/") or mp.startswith("/proc/"):
            print(f"error: --map {args.map} is a stream or special file. The map holds the original "
                  f"values and must be written to a private file on disk.", file=sys.stderr)
            return 1
        if os.path.exists(mp) and not os.path.isfile(mp):
            print(f"error: --map {args.map} is not a regular file.", file=sys.stderr)
            return 1

    # A .dnmap is a placeholder map, not a log: scrubbing it would stamp a
    # trusted marker on a table of the original values.
    for src in args.inputs:
        resolved = os.path.realpath(os.path.expanduser(src)) if src != "-" else src
        if src.lower().endswith(".dnmap") or resolved.lower().endswith(".dnmap"):
            print(f"error: {src} is a dn_logscrub placeholder map, not a log. It holds the original "
                  f"values and must never be scrubbed, shared or read by an agent.", file=sys.stderr)
            return 1

    try:
        scrubber = Scrubber(keep_paths=args.keep_paths, extra_domains=args.domain, disable=args.disable)
    except ValueError as exc:
        print(f"dn_logscrub: {exc}", file=sys.stderr)
        return 2
    # Every destination is resolved and checked before anything is opened.
    # Streaming opens each output before reading its input, so any destination
    # that lands on an input destroys the log it was meant to sanitise, and two
    # destinations that coincide silently drop one result.
    def _real(q: str) -> str:
        # normcase so a case-insensitive filesystem (Windows, macOS by default)
        # does not let `-o APP.LOG` look like a different file from `app.log`
        # and truncate the input.
        return os.path.normcase(os.path.realpath(os.path.expanduser(q)))

    inputs_real = {_real(q): q for q in args.inputs if q != "-" and os.path.exists(q)}

    def _ident(q: str):
        """Filesystem identity, so a hard link to an input is recognised."""
        try:
            st = os.stat(os.path.expanduser(q))
            return (st.st_dev, st.st_ino)
        except OSError:
            return None

    inputs_ident = {}
    for q in args.inputs:
        if q == "-":
            continue
        ident = _ident(q)
        if ident:
            inputs_ident[ident] = q
    destinations: dict = {}   # resolved path -> human description

    def _claim(dst: str, what: str) -> Optional[str]:
        """Register a destination, or return the error that forbids it."""
        key = _real(dst)
        if key in inputs_real:
            return (f"error: {what} would be written to {dst}, which is the input "
                    f"{inputs_real[key]}. Refusing: that truncates the log before it is read.")
        # A hard link has its own pathname and the same inode, so comparing
        # canonical paths alone would miss it and the input would be truncated.
        ident = _ident(dst)
        if ident and ident in inputs_ident:
            return (f"error: {what} would be written to {dst}, which is the same file as the input "
                    f"{inputs_ident[ident]} (hard link). Refusing: that truncates the log before it "
                    f"is read.")
        if key in destinations:
            return (f"error: {what} and {destinations[key]} would both be written to {dst}. "
                    f"Refusing: one result would silently overwrite the other.")
        destinations[key] = what
        return None

    if not args.stdout:
        for src_path in args.inputs:
            if src_path == "-" and not args.output:
                continue
            dst = _dest(src_path)
            err = _claim(dst, f"the scrubbed output of {src_path}")
            if err:
                print(err + " Sanitise them in separate runs, or pass -o for each — but note "
                            "placeholders are only consistent within one run.", file=sys.stderr)
                return 1

    if args.map:
        # A map that is not named .dnmap escapes both the raw-log guard and the
        # `*.dnmap` gitignore, so it could be read or committed by accident.
        # Lowercase exactly: `.gitignore` is case-sensitive on a case-sensitive
        # filesystem, so `ticket.DNMAP` would be committable despite the suffix
        # being what keeps the map out of commits.
        if not args.map.endswith(".dnmap"):
            print(f"error: --map {args.map} must end in .dnmap. That suffix is what the raw-log "
                  f"guard refuses to open and what .gitignore keeps out of commits; the map holds "
                  f"the original values.", file=sys.stderr)
            return 1
        err = _claim(args.map, "the placeholder map")
        if err:
            print(err, file=sys.stderr)
            return 1
        # An exclude rule cannot help a file git already tracks: the next
        # `git add -A` would stage the originals written into it.
        tracked = _is_tracked(args.map)
        if tracked:
            print(f"error: --map {args.map} is tracked by git. Writing the original values into it would "
                  f"put them in the next commit. Choose a path outside the repository (e.g. "
                  f"~/dn-tickets/<id>/ticket.dnmap), and remove this file from the repository.",
                  file=sys.stderr)
            return 1
        if tracked is None:
            print(f"error: --map {args.map} is inside a git working tree, and git could not say whether it "
                  f"tracks that file. Refusing to write the original values there; choose a path outside "
                  f"the repository (e.g. ~/dn-tickets/<id>/ticket.dnmap).", file=sys.stderr)
            return 1

    if args.report:
        err = _claim(args.report, "the JSON report")
        if err:
            print(err, file=sys.stderr)
            return 1

    # A raw log inside a working tree blocks the searches that would read it
    # in Claude Code (the guard sees it) and is one `git add -A` away from a
    # commit. Said once, up front, with what to do instead.
    in_repo = [q for q in args.inputs if q != "-" and _worktree_of(q)]
    if in_repo:
        print(f"dn_logscrub: note: {safe_label(scrubber, in_repo[0])}"
              + (f" and {len(in_repo) - 1} more" if len(in_repo) > 1 else "")
              + " sit inside a git working tree. Raw logs there block the searches that would read them and can "
                "be committed by accident; keep ticket logs outside it (e.g. ~/dn-tickets/<id>/) and "
                "use --out-dir.", file=sys.stderr)

    # SIGTERM (a tool timeout, `kill`) is handled like Ctrl-C: the file being
    # written gets an `interrupted` trailer instead of being left without one,
    # which made a run cut short unreadable and had to be started again.
    try:
        import signal as _signal
        if hasattr(_signal, "SIGTERM"):
            _signal.signal(_signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    except (ValueError, OSError):
        pass  # not the main thread (library use): leave signals alone

    written: List[str] = []
    leaked_names: List[tuple] = []
    interrupted = False
    for src_path in args.inputs:
        name = "stdin" if src_path == "-" else os.path.basename(src_path)
        before = dict(scrubber.stats)
        scrubber.reset_line_state()  # a PEM left open must not swallow the next file
        try:
            if src_path == "-":
                raw = sys.stdin.buffer if hasattr(sys.stdin, "buffer") else None
                if raw is not None:
                    head = raw.peek(4096)[:4096] if hasattr(raw, "peek") else b""
                    _refuse_non_utf8_bytes(head, "stdin")
                src = sys.stdin
            else:
                src = _open_text(src_path)
        except OSError as e:
            print(f"error: cannot read {src_path}: {e}", file=sys.stderr)
            return 1

        to_stdout = args.stdout or (src_path == "-" and not args.output)
        dst_path = None if to_stdout else _dest(src_path)
        out_fh = sys.stdout if to_stdout else _open_new(dst_path, what="output")

        # Written line by line rather than buffered whole: a live stream
        # (`adb logcat | dn_logscrub -`) used to produce nothing until EOF and
        # grow without bound, and a large CI or customer log could exhaust
        # memory. The marker still goes out first, which is what the guard
        # checks; the per-category counts can only be known at the end, so
        # they follow as a trailer.
        # A live stream must appear as it arrives, and stdout is block-buffered
        # when piped, so flush per line while reading stdin. For a regular file
        # the default buffering is left alone.
        if src is sys.stdin:
            def write(chunk: str) -> None:
                out_fh.write(chunk)
                out_fh.flush()
        else:
            write = out_fh.write

        try:
            write(scrubber.header(name, streaming=True))
            try:
                scrubber.scrub_stream(src, write)
            except KeyboardInterrupt:
                interrupted = True
            file_stats = {k: v - before.get(k, 0) for k, v in scrubber.stats.items() if v - before.get(k, 0)}
            # A line cut off mid-write must not swallow the trailer onto it.
            write(("\n" if interrupted else "") + scrubber.trailer(file_stats, interrupted=interrupted))
        except BrokenPipeError:
            # The reader went away (`… | head`). Nothing more can be written,
            # and the partial stream it read was scrubbed line by line.
            try:
                sys.stdout = open(os.devnull, "w")
            except OSError:
                pass
            return 1
        finally:
            if src is not sys.stdin:
                src.close()
            if out_fh is not sys.stdout:
                out_fh.close()
        if dst_path:
            written.append(dst_path)
        total = sum(file_stats.values())
        detail = ", ".join(f"{k}={v}" for k, v in sorted(file_stats.items()))
        # This line is written for the agent to read, so the input name goes
        # through the same rules as the body: a log named after a customer or
        # an e-mail would otherwise put that value in the transcript, which is
        # exactly what header() was fixed not to do.
        label = safe_label(scrubber, name)
        if label != name:
            leaked_names.append((name, label))
        print(f"dn_logscrub: {label}: {total} redactions" + (f" ({detail})" if detail else "")
              + (" — INTERRUPTED: the scrubbed copy is clean but incomplete" if interrupted else ""),
              file=sys.stderr)
        if interrupted:
            break  # the remaining inputs were never started

    if args.map:
        # Holds the original values: owner-only, and created that way rather
        # than chmod-ed afterwards so it is never briefly world-readable.
        # (validated before any processing, see _validate_map_destination)
        # The mode passed to os.open only applies when the file is created, so
        # an existing group- or world-readable map would have kept its mode
        # while the originals were written into it. Removing it first means the
        # file is always created here, which is portable — os.fchmod does not
        # exist on Windows — and leaves no window where it is readable.
        _refuse_linked_parents(args.map, "placeholder map")
        try:
            if os.path.lexists(args.map):
                os.unlink(args.map)
            fd = os.open(args.map, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            print(f"error: cannot create {args.map} privately ({exc}); refusing to write the "
                  f"placeholder map, which holds the original values.", file=sys.stderr)
            return 1
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(scrubber.map_as_json())
        try:  # best effort; on Windows POSIX modes are largely advisory
            os.chmod(args.map, 0o600)
        except OSError:
            print(f"dn_logscrub: warning: could not set owner-only permissions on {args.map}. "
                  f"It holds the original values — keep it in a private directory.", file=sys.stderr)
        print(f"dn_logscrub: placeholder map written to {args.map} — keep local, never share", file=sys.stderr)
        _keep_map_out_of_commits(args.map)
    if args.report:
        with _open_new(args.report, what="report") as fh:
            # The paths carry whatever the filenames carry, and a report is
            # exactly the kind of artefact that gets attached to an
            # investigation. Same treatment as the header and the summary:
            # display names only, scrubbed, control characters removed.
            json.dump({"dn_logscrub": __version__,
                       "note": "Display names are scrubbed; full paths are deliberately omitted. "
                               "Local artefact — safe to attach, but it describes a run, not its data.",
                       "inputs": [safe_label(scrubber, q) for q in args.inputs],
                       "outputs": [safe_label(scrubber, w) for w in written],
                       "stats": scrubber.stats, "total": sum(scrubber.stats.values())}, fh, indent=2)
    for w in written:
        # The path stays verbatim: whoever reads this has to be able to open
        # the file. If the name itself carried an identifier, say so rather
        # than hiding it — the fix is to rename the input, not to obscure the
        # path of a file the agent must now read.
        print(f"dn_logscrub: wrote {w}", file=sys.stderr)
    if leaked_names:
        print(f"dn_logscrub: warning: {len(leaked_names)} input filename(s) contain identifiers "
              f"(reported above as {', '.join(l for _, l in leaked_names[:3])}). The scrubbed copies "
              f"are named after them, so the value travels with the path. Rename the inputs before "
              f"handing the paths to an AI tool.", file=sys.stderr)
    return 130 if interrupted else 0


def _worktree_of(path: str) -> Optional[str]:
    """The git working tree containing `path`, found without running git."""
    d = os.path.dirname(os.path.abspath(os.path.expanduser(path)))
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _is_tracked(path: str) -> Optional[bool]:
    """Is `path` a file git already tracks?

    False outside a repository and for git's own "did not match" answer
    (exit 1); None when git could not answer at all — missing, timed out, a
    broken repository — so the caller can refuse rather than guess.
    """
    top = _worktree_of(path)
    if not top:
        return False
    import subprocess
    try:
        rc = subprocess.run(["git", "-C", top, "ls-files", "--error-unmatch", "--", os.path.abspath(path)],
                            capture_output=True, timeout=5).returncode
    except (OSError, subprocess.SubprocessError):
        return None
    return True if rc == 0 else False if rc == 1 else None


def _keep_map_out_of_commits(map_path: str) -> None:
    """A map written inside a working tree is excluded from commits locally.

    `*.dnmap` reaches `.gitignore` only through /sync-skill; a repository
    without it would commit the table of originals on the next `git add -A`.
    `.git/info/exclude` is local to this clone, so nothing in the repo changes.
    """
    top = _worktree_of(map_path)
    if not top:
        return
    import subprocess
    try:
        ignored = subprocess.run(["git", "-C", top, "check-ignore", "-q", os.path.abspath(map_path)],
                                 capture_output=True, timeout=5).returncode == 0
        if ignored:
            return
        p = subprocess.run(["git", "-C", top, "rev-parse", "--git-path", "info/exclude"],
                           capture_output=True, text=True, timeout=5)
        exclude = p.stdout.strip()
        if p.returncode != 0 or not exclude:
            raise OSError("no exclude file")
        if not os.path.isabs(exclude):
            exclude = os.path.join(top, exclude)
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        with open(exclude, "a", encoding="utf-8") as fh:
            fh.write("\n# dn_logscrub placeholder maps hold original values\n*.dnmap\n")
        print(f"dn_logscrub: {map_path} is inside a git working tree; added `*.dnmap` to {exclude} "
              f"so it cannot be committed. Better still, keep maps outside the repository.", file=sys.stderr)
    except (OSError, subprocess.SubprocessError):
        print(f"dn_logscrub: warning: {map_path} is inside a git working tree and is not ignored. It holds "
              f"the original values: move it out, or add `*.dnmap` to .gitignore.", file=sys.stderr)


def safe_label(scrubber: "Scrubber", name: str) -> str:
    """A filename fit to print: scrubbed, and with no control characters.

    Both halves matter. The scrubbing keeps a customer or an e-mail out of the
    text; stripping control characters stops a crafted name injecting extra
    lines — into the header, whose first line the raw-log guard trusts, and
    equally into the stderr summary, which lands in the agent transcript.
    """
    return re.sub(r"[\x00-\x1f\x7f]", "?", scrubber.scrub_text(os.path.basename(name)))


# --------------------------------------------------------------------------- #
# Self-test fixtures
# --------------------------------------------------------------------------- #
# The fixtures are NOT bundled with this script. To test a sanitiser you need a
# fixture full of realistic credentials, and such a file is rejected by the
# secret-scanning pre-commit hook of AI Security Roadmap 4.1 — which would make
# this skill unsyncable into any repo that enforces 4.1, i.e. all of them. So
# they live in the plugin checkout, at tests/log_sanitise_fixtures.py, and only
# --selftest needs them. Everything a `.scrubbed` copy depends on is here.

_FIXTURES_REL = ("..", "..", "..", "tests", "log_sanitise_fixtures.py")


def _load_fixtures():
    """Import the fixture module from the plugin checkout, or return None."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), *_FIXTURES_REL)
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("dn_logscrub_fixtures", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def selftest() -> int:
    fx = _load_fixtures()
    if fx is None:
        print(
            "--selftest needs tests/log_sanitise_fixtures.py, which ships only with\n"
            "the plugin checkout: the fixture is a file full of sample credentials and\n"
            "bundling it here would trip the secret-scanning hook of AI Security\n"
            "Roadmap 4.1 in every repo this skill is synced into.\n"
            "Run --selftest from the displaynote-engineering-plugin checkout.",
            file=sys.stderr,
        )
        return 2
    s = Scrubber()
    out = s.scrub_text(fx._FIXTURE)
    failures = []
    for needle in fx._MUST_BE_ABSENT:
        if needle in out:
            failures.append(f"LEAK    still present: {needle!r}")
    for needle in fx._MUST_BE_PRESENT:
        if needle not in out:
            failures.append(f"MISSING expected:      {needle!r}")
    # consistency: the same email / IP must map to the same placeholder
    if out.count("<EMAIL_1>") < 2:
        failures.append("CONSISTENCY: repeated email did not map to the same placeholder")
    if out.count("<IPV4_1>") < 2:
        failures.append("CONSISTENCY: repeated IP did not map to the same placeholder")
    # One value, one placeholder — whichever attribute carries it. The same JID
    # used to come out as <NAME_n> inside from="…" and <EMAIL_n> everywhere
    # else, because a keyed rule re-labelled a value that already contained one
    # of our own placeholders.
    jid = re.search(r'from="([^"]*)"\s+to="([^"]*)"', out)
    if not jid:
        failures.append("CONSISTENCY: the from=/to= fixture line disappeared")
    elif jid.group(1) != jid.group(2):
        failures.append(f"CONSISTENCY: same JID mapped to {jid.group(1)!r} and {jid.group(2)!r}")
    # marker / check round-trip
    hdr = s.header("fixture")
    if not MARKER_RE.match(hdr):
        failures.append("MARKER: header does not match MARKER_RE")
    print(out)
    print("stats:", json.dumps(s.stats, sort_keys=True))
    if failures:
        print("\nSELFTEST FAILED:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    # is_scrubbed() is a trust gate, so it gets its own cases: the header alone
    # accepted a scrubbed file with raw content appended after it.
    import tempfile as _tf
    HDR = "# dn_logscrub v1.0.0 | source=x | scrubbed=2026-09-14T00:00:00Z | redactions=counted\n"
    TRL = "# dn_logscrub end | redactions=1 | EMAIL=1\n"
    with _tf.TemporaryDirectory() as td:
        for name, body, want, label in [
                ("ok.txt", HDR + "user <EMAIL_1>\n" + TRL, True, "header and trailer"),
                ("appended.txt", HDR + "user <EMAIL_1>\n" + TRL + "RAW token=sk-proj-abcdefghij\n",
                 False, "raw appended after the trailer"),
                ("forged.txt", HDR + "RAW token=sk-proj-abcdefghij\n", False, "header forged, no trailer"),
                ("partial.txt", HDR + "user <EMAIL_1>\n", False, "still being written"),
                ("glued.txt", HDR + "user <EMAIL_1>\n" + TRL.rstrip("\n") + "token=sk-proj-abcdefghij\n",
                 False, "raw glued onto the trailer line"),
                ("nocounts.txt", HDR + "user <EMAIL_1>\n# dn_logscrub end | whatever\n",
                 False, "trailer without the counts"),
                ("none.txt", HDR + "nothing\n# dn_logscrub end | redactions=0 | none\n",
                 True, "a run that redacted nothing")]:
            fp = os.path.join(td, name)
            with open(fp, "w") as fh:
                fh.write(body)
            if is_scrubbed(fp) != want:
                failures.append(f"TRUST: is_scrubbed({label!r}) should be {want}")
    if failures:
        print("\nSELFTEST FAILED:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    print(f"\nSELFTEST PASSED — {sum(s.stats.values())} redactions across {len(s.stats)} categories")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
