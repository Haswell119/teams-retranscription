# Delivery

Hansard produces minutes locally and then hands them to one or more *delivery channels*. This
document explains every channel, how to configure it, what Microsoft Entra ID / Microsoft Teams
really allows an application-only bot to do in 2026, and how to debug the usual failures.

## Sovereignty guarantee

The delivery adapters contact **only the hosts you configure yourself**:

* No adapter has a default remote endpoint. `filesystem` writes to your disk, `email` needs an SMTP
  host you set, `webhook` needs a URL you set, `teams_chat` needs credentials and a target address
  you set. If nothing is configured, nothing leaves the machine.
* There is no telemetry, no analytics, no crash reporting, no "phone home" of any kind.
  `HANSARD_RUNTIME__TELEMETRY_ENABLED=true` is rejected by the configuration layer on purpose.
* Every outbound call is made through an HTTP client that the caller can inject, so an operator (or
  the test suite) can see, wrap or block all traffic.
* Secrets are held as `pydantic.SecretStr`, are never written to logs, and never appear in error
  messages — the error text names the *setting* to check, not its value.

## Installing the extras

```bash
pip install -e '.[delivery]'          # aiosmtplib, for the email channel
pip install -e '.[delivery,delivery-msal]'   # optional: use MSAL for Entra ID tokens
```

`httpx` is a core dependency, so the Teams and webhook channels need no extra. MSAL is **optional**:
if `msal` is importable, Hansard uses it for client-credentials tokens (it handles regional
endpoints, retries and clock skew); otherwise it falls back to a small, fully tested `httpx`
implementation of the same OAuth 2.0 flow. Both sit behind one internal `TokenSource` interface.

## Choosing channels

A meeting request carries `DeliveryTarget(channel, address, formats)` values. The channel is one of
`filesystem`, `email`, `webhook`, `teams_chat`. The address means something different per channel:

| Channel | Address format | Example |
| --- | --- | --- |
| `filesystem` | directory relative to the artefact root; empty means the root itself | `2026/august/board` |
| `email` | one or more recipients, comma/semicolon/space separated | `clerk@council.example; mayor@council.example` |
| `webhook` | absolute URL (or empty to use `HANSARD_DELIVERY__WEBHOOK_URL`) | `https://intranet.example/hooks/minutes` |
| `teams_chat` | `chat:{chat-id}` | `chat:19:2da4c29f6d7041eca70b638b43d45437@thread.v2` |
| `teams_chat` | `channel:{team-id}/{channel-id}` | `channel:fbe2bf47-…/19:4a95f7…@thread.tacv2` |
| `teams_chat` | `bot:{serviceUrl}#{conversationId}` | `bot:https://smba.trafficmanager.net/emea/#19:meeting_…@thread.v2` |
| `teams_chat` | Power Automate Workflows URL | `https://prod-12.westeurope.logic.azure.com/workflows/…` |

Defaults come from settings:

```bash
export HANSARD_DELIVERY__DEFAULT_CHANNELS='["filesystem"]'   # JSON list, pydantic-settings syntax
export HANSARD_DELIVERY__OUTPUT_DIR=/var/lib/hansard/artifacts
```

A meeting that carries no target of its own is delivered to those default channels with an **empty**
address, which for `filesystem` is `OUTPUT_DIR` itself. It has to be empty: the publisher is already
rooted at `OUTPUT_DIR`, so passing that same path as the address once resolved to `artifacts/artifacts`
with the relative default, and was refused outright as an absolute address with the value every
container and the Helm chart set.

All targets are published **concurrently** by `DeliveryDispatcher`, each with its own timeout. One
failing channel never prevents the others: the dispatcher returns a `DeliveryReport` with a
per-target success/failure outcome and the duration of each attempt.

## 1. Filesystem channel (default)

Writes the minutes body plus every attachment into a directory derived from the target address.
Parent directories are created. This is the channel that always works and the one every other
channel refers to when a message has to be truncated.

```bash
export HANSARD_DELIVERY__OUTPUT_DIR=/var/lib/hansard/artifacts
```

Safety rules (all enforced and unit-tested):

* The address is treated as a path **relative to the artefact root**. `..` segments are refused with
  a `DeliveryError`, and the resolved directory must still be inside the root after symlink
  resolution.
* Absolute addresses (`/etc`, `C:\Windows`, `\\server\share`) are refused unless the publisher is
  built with `allow_absolute_paths=True`.
* Attachment filenames are sanitised, never interpreted as paths: directory components are dropped
  (`../../etc/passwd` becomes `passwd`), control characters, NUL and `<>:"/\|?*` become `_`, leading
  and trailing dots and spaces are stripped, Windows device names (`CON`, `LPT1`, …) are prefixed
  with `_`, and names are capped at 180 characters.
* Colliding names never overwrite each other: the second `notes.txt` is written as `notes-1.txt`.

The body file is named after the subject with an extension chosen from the payload format
(`markdown` → `.md`, `html` → `.html`, otherwise `.txt`).

## 2. Email channel

Builds a `multipart/alternative` message (plain-text fallback first, HTML second) with attachments
in their declared MIME types, and sends it with `aiosmtplib`.

```bash
export HANSARD_DELIVERY__SMTP__HOST=smtp.council.example
export HANSARD_DELIVERY__SMTP__PORT=587
export HANSARD_DELIVERY__SMTP__USERNAME=hansard
export HANSARD_DELIVERY__SMTP__PASSWORD='…'
export HANSARD_DELIVERY__SMTP__START_TLS=true     # STARTTLS on a plain port (default)
export HANSARD_DELIVERY__SMTP__USE_TLS=false      # true for implicit TLS, usually port 465
export HANSARD_DELIVERY__SMTP__SENDER='Hansard <hansard@council.example>'
```

* **Plain SMTP**: `USE_TLS=false`, `START_TLS=false` (port 25 on a trusted internal relay).
* **STARTTLS**: `USE_TLS=false`, `START_TLS=true` (port 587). This is the default.
* **Implicit TLS**: `USE_TLS=true` (port 465). `START_TLS` is then ignored.
* **Authentication** is optional: leave `USERNAME`/`PASSWORD` unset for an anonymous internal relay.

Multiple recipients may be separated by commas, semicolons or whitespace; duplicates are removed and
malformed addresses are rejected before anything is sent. Markdown bodies are converted to HTML for
the rich part and kept as-is for the plain-text part; HTML bodies are converted to text for the
fallback part.

The SMTP transport is injected (`EmailPublisher(message_sender=…)`), so the whole channel is testable
offline with a stub sender — that is exactly what `tests/delivery/test_smtp.py` does.

## 3. Teams channel — what actually works

This is the part where the documentation and reality diverge, so here is the truth as of 2026.

### The Microsoft Graph app-only limitation (verified)

`POST /chats/{chat-id}/messages` and `POST /teams/{team-id}/channels/{channel-id}/messages` list
these permissions on learn.microsoft.com:

| Permission type | Least privileged | Higher privileged |
| --- | --- | --- |
| Delegated (work or school) | `ChatMessage.Send` / `ChannelMessage.Send` | `Chat.ReadWrite`, `Group.ReadWrite.All` |
| Delegated (personal account) | Not supported | Not supported |
| **Application** | **`Teamwork.Migrate.All`** | **Not available** |

And the explicit note: *"Application permissions are only supported for
[migration](https://learn.microsoft.com/microsoftteams/platform/graph-api/import-messages/import-external-messages-to-teams)."*
Migration means the target chat/channel must have been **created in migration mode**; a normal,
live chat rejects the call. `ChatMessage.Send` and `ChannelMessage.Send` simply do not exist as
application permissions in the Entra portal.

The resource-specific consent (RSC) permission `ChannelMessage.Send.Group` *is* listed in the Teams
RSC table as an application permission ("Send messages to this team's channels"), but it does not
unlock the Graph endpoint: real requests come back

```
403 Forbidden — Missing role permissions on the request.
API requires one of 'Teamwork.Migrate.All'. Roles on the request 'Group.Selected'.
```

This is a long-standing, still-open documentation bug
(`MicrosoftDocs/msteams-docs` issue 14043). There is no RSC equivalent for chats at all
(`ChatMessage.Send.Chat` does not exist; the chat RSC table only offers `ChatMessage.Read.Chat`).

**Conclusion: a daemon with only a client secret cannot post an ordinary Teams message through
Microsoft Graph.** Anyone who tells you otherwise has either delegated credentials or a migration
tenant.

### What Hansard implements

`TeamsChatPublisher` (address `chat:` / `channel:`) implements the Graph path correctly — client
credentials against `{authority}/{tenant}/oauth2/v2.0/token` with scope
`https://graph.microsoft.com/.default`, cached until 60 s before expiry, HTML `chatMessage` bodies,
chunking, `Retry-After`-aware retries. It is the right adapter for the two cases where the Graph
path genuinely works:

1. **Migration mode** — you hold `Teamwork.Migrate.All` and the chat/channel is in migration state.
2. **Delegated tokens** — you supply a token provider that performs a delegated flow (the
   `TokenSource` interface is the extension point; nothing else changes).

If Graph answers `401`/`403`, the resulting `DeliveryError` states the limitation and names the
alternatives instead of leaving you guessing.

Because that path is not available to most tenants, Hansard also ships the two paths that **do**
work app-only:

* **`bot:` — Bot Framework proactive message** (`TeamsBotPublisher`). If you register an Azure Bot
  and install its Teams app in the chat/team, the bot may post at any time by `POST`ing an activity
  to `{serviceUrl}/v3/conversations/{conversationId}/activities` with a token from
  `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` (single-tenant bot) or
  `https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token` (multi-tenant bot), scope
  `https://api.botframework.com/.default`. This is the supported "notification-only bot" pattern and
  needs **no Graph application permission at all**. Capture `serviceUrl` and `conversationId` from
  any activity your bot receives (or from the Graph `chats`/`teams` ids used at install time) and
  build the address `bot:{serviceUrl}#{conversationId}`.
* **Power Automate Workflows webhook** — see the `webhook` channel below. Classic Office 365
  connector webhooks (`*.webhook.office.com`) were retired in Teams in May 2026; the replacement is
  a Workflows flow ("Post to a channel when a webhook request is received"), whose URL accepts a
  MessageCard or an Adaptive Card payload. Hansard produces both shapes.

A `teams_chat` target is routed by its address scheme, so a single configured channel can use
whichever path your tenant permits.

### Entra ID app registration (step by step)

Only needed for the `chat:`, `channel:` and `bot:` addresses.

1. Sign in to the **Microsoft Entra admin center** → **Identity** → **Applications** → **App
   registrations** → **New registration**.
2. Name it (e.g. *Hansard Minutes*), choose **Accounts in this organizational directory only**
   (single tenant) unless you are building a multi-tenant bot, and register.
3. Copy **Application (client) ID** and **Directory (tenant) ID** from the Overview page.
4. **Certificates & secrets** → **New client secret** → copy the *Value* immediately.
5. Permissions, depending on the path you chose:
   * *Graph migration path*: **API permissions** → **Add a permission** → **Microsoft Graph** →
     **Application permissions** → `Teamwork.Migrate.All` → **Grant admin consent**. Then create the
     team/channel or chat in migration mode
     (`POST /teams` with `"@microsoft.graph.teamCreationMode": "migration"`) and complete the
     migration when you are done. Microsoft states it may charge for imported data volume.
   * *Bot path*: create an **Azure Bot** resource that uses this app registration, enable the
     **Microsoft Teams** channel on it, package a Teams app manifest with the bot id
     (`"isNotificationOnly": true` is enough) and install it in the target team or chat. No Graph
     application permission is required.
   * *Workflows path*: no app registration at all.
6. Configure Hansard:

```bash
export HANSARD_DELIVERY__GRAPH__TENANT_ID=contoso.onmicrosoft.com
export HANSARD_DELIVERY__GRAPH__CLIENT_ID=11111111-2222-3333-4444-555555555555
export HANSARD_DELIVERY__GRAPH__CLIENT_SECRET='…'
export HANSARD_DELIVERY__GRAPH__AUTHORITY=https://login.microsoftonline.com   # sovereign clouds differ
export HANSARD_DELIVERY__GRAPH__SCOPE=https://graph.microsoft.com/.default
export HANSARD_DELIVERY__GRAPH__BASE_URL=https://graph.microsoft.com/v1.0
export HANSARD_DELIVERY__BOT_TENANT_ID=botframework.com   # only for a multi-tenant bot
```

For sovereign clouds set the authority and base URL accordingly (for example
`https://login.microsoftonline.us` and `https://graph.microsoft.us/v1.0`).

### Finding chat, team and channel ids

* Chat id: the `19:…@thread.v2` value in the Teams deep link, or `GET /me/chats`.
* Team id: the `groupId` query parameter of a channel link, or `GET /me/joinedTeams`.
* Channel id: the `19:…@thread.tacv2` value in the channel link, or `GET /teams/{id}/channels`.

### Message size and chunking

Teams caps a post at roughly **100 KB** and Microsoft recommends staying under **80 KB**; Bot
Framework activities are stricter still. Hansard therefore splits the rendered HTML at block
boundaries into chunks of at most 28 000 characters (configurable per publisher), posts them in
order, and prefixes each one with `Part n of m`. If the minutes need more than four chunks
(configurable), the last chunk is marked **Truncated** and carries a link to the full artefact
(`artifact_reference`) or, when no link is configured, points at the filesystem artefact directory.
Attachments are never uploaded to Teams — Graph would require driveItem or hostedContent uploads —
they are listed by name in the message and delivered in full by the filesystem/email channels.

### Throttling

Graph and the Bot Connector answer `429` (and occasionally `503`) under load. Hansard retries
`408/425/429/500/502/503/504`, honours the `Retry-After` header exactly (numeric seconds or an HTTP
date), and otherwise backs off exponentially (1 s, 2 s, 4 s …, capped at 30 s, four attempts by
default). The same retry helper is used by the webhook channel.

## 4. Webhook channel

Posts a JSON document to any URL: a Power Automate Workflows webhook, a Teams incoming webhook that
still exists, an internal ticketing system, a message bus bridge.

```bash
export HANSARD_DELIVERY__WEBHOOK_URL=https://prod-12.westeurope.logic.azure.com/workflows/…
export HANSARD_DELIVERY__WEBHOOK_FORMAT=json          # json | message_card | adaptive_card
export HANSARD_DELIVERY__WEBHOOK_SECRET='…'           # optional HMAC key
```

`HANSARD_DELIVERY__WEBHOOK_URL` is the fallback used when a target address is empty; an address on
the target always wins and may be written as `https://…`, `webhook:https://…` or `workflow:https://…`.

Body formats:

* `json` — Hansard's own document:

  ```json
  {"attachments":[{"filename":"minutes.pdf","media_type":"application/pdf","size_bytes":1234}],
   "body":"# Minutes…","body_format":"markdown","generated_at":"2026-08-25T09:00:00+00:00",
   "source":"hansard","subject":"Board meeting"}
  ```

  Attachment bytes are omitted by default; build the publisher with
  `include_attachment_content=True` to add a `content_base64` field per attachment.
* `message_card` — legacy Teams MessageCard (`@type: MessageCard`), still accepted by Workflows
  webhooks migrated from Office 365 connectors.
* `adaptive_card` — `{"type":"message","attachments":[{"contentType":
  "application/vnd.microsoft.card.adaptive","content":{…}}]}`, the shape Teams and Workflows expect
  today. This is the default when the `teams_chat` channel routes to a webhook URL.

### Signing scheme

When a secret is configured, every request carries two headers:

```
X-Hansard-Timestamp: 1756100000
X-Hansard-Signature: sha256=<hex digest>
```

The digest is computed as

```
HMAC-SHA256(key = secret bytes (UTF-8),
            message = ascii(timestamp) + "." + raw request body bytes)
```

where the raw body is exactly the bytes on the wire: compact JSON (`,`/`:` separators, keys sorted,
non-ASCII kept as UTF-8). Verify it like this:

```python
import hashlib, hmac, time

def verify(secret: str, request_headers, raw_body: bytes, max_age_seconds: int = 300) -> bool:
    timestamp = int(request_headers["X-Hansard-Timestamp"])
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()
    fresh = abs(time.time() - timestamp) <= max_age_seconds
    return fresh and hmac.compare_digest(expected, request_headers["X-Hansard-Signature"])
```

Always compare with a constant-time function and reject stale timestamps to prevent replay. Without
a secret, neither header is sent (Workflows and Teams ignore them anyway).

## Failure handling

Every adapter raises `hansard.domain.errors.DeliveryError` with a message naming the endpoint, the
target and the setting to fix. `ConfigurationError` is raised for an unknown channel or an unknown
webhook body format. The dispatcher converts both into per-target outcomes, so a broken SMTP relay
never costs you the Teams post or the on-disk artefact.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `403 … API requires one of 'Teamwork.Migrate.All'` | Expected: app-only Graph posting is migration-only. Use a `bot:` address or a Workflows webhook. |
| `401 … InvalidAuthenticationToken` | Wrong scope or authority. The scope must be `https://graph.microsoft.com/.default` (or `https://api.botframework.com/.default` for `bot:`); tokens are not interchangeable. |
| `AADSTS7000215: Invalid client secret` | The secret expired or the *Secret ID* was copied instead of the *Value*. Create a new secret. |
| `AADSTS700016: Application … not found in the directory` | Wrong tenant id, or the app registration lives in another tenant. |
| `404` on a chat or channel post | The chat/channel id is wrong or the app cannot see it. Verify with `GET /chats/{id}` using the same token. |
| `403 BotNotInConversationRoster` | The Teams app that carries the bot is not installed in that chat/team, or the conversation id is stale. |
| Bot posts fail with `401` right after a tenant move | `serviceUrl` is regional (`smba.trafficmanager.net/emea/`, `/amer/`, …) and can change. Refresh it from a recent activity. |
| Teams message appears truncated | The minutes exceeded the chunk budget. Raise `max_chunks`, or configure an `artifact_reference` link to the full document. |
| `webhook … answered 400` from Workflows | The flow expects an Adaptive Card. Set `HANSARD_DELIVERY__WEBHOOK_FORMAT=adaptive_card`. |
| SMTP `535` / authentication rejected | Check `HANSARD_DELIVERY__SMTP__USERNAME` / `…__PASSWORD`; some relays require the sender to match the account. |
| SMTP hangs on port 465 | Implicit TLS: set `USE_TLS=true` (STARTTLS is then disabled automatically). |
| `absolute delivery directory '…' is refused` | Filesystem addresses are relative to `HANSARD_DELIVERY__OUTPUT_DIR` by design. Leave the address empty to mean that directory itself. |
| Nothing is delivered at all | `HANSARD_DELIVERY__DEFAULT_CHANNELS` is a JSON list, e.g. `'["filesystem","email"]'`. |

## Extending

`build_publisher(channel, settings)` resolves a channel through a registry identical in shape to the
ASR one; `register_publisher(name, factory)` adds your own channel, and `available_channels()` lists
what is installed. Any object with a `channel` property and an `async def publish(target, payload)`
method satisfies the `MinutesPublisher` port — no inheritance required.
