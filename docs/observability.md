# Observability

Hansard is meant to run where nobody can look at the audio and nobody may see the transcript —
including whoever operates the service. This page describes the two things it does emit, logs and
metrics, and the rules that keep meeting content out of both.

## Sovereignty guarantee

* **No meeting content is ever logged.** Fields named `text`, `transcript`, `body` and `quote` are
  replaced with a character count before anything is rendered. This is a processor in the logging
  pipeline, not a convention that each call site has to remember.
* **No credential is ever logged.** Every `pydantic.SecretStr` and every field whose name looks like
  a credential becomes `***`, at any depth of nesting.
* **No metric carries an identity.** Metric labels may not name a meeting, a participant, a user, a
  tenant, a URL, a subject or a path; `metrics.py` raises `UnsafeLabelError` at import time if a
  metric is declared with one.
* **Nothing is sent anywhere.** Logs go to stdout, metrics are exposed for a scraper you run
  yourself. There is no telemetry, and `HANSARD_RUNTIME__TELEMETRY_ENABLED=true` is refused by the
  configuration layer.

## Logging

### Configuration

Two settings, both under `HANSARD_RUNTIME__`:

| Variable | Values | Default | Meaning |
| --- | --- | --- | --- |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` | Applied to Hansard *and* to every third-party library. An unknown name falls back to `INFO`. |
| `LOG_FORMAT` | `json`, `console` | `json` | One JSON object per line, or one aligned human-readable line. |

`configure_logging(settings.runtime)` is called once, from `create_app()` for the API and from
`main()` for the CLI. It configures [structlog](https://www.structlog.org) and installs a single
handler on the stdlib root logger, so `uvicorn`, `httpx`, `botocore` and `faster_whisper` are
rendered in exactly the same format as Hansard's own events.

Until it is called, Hansard's own loggers are silent below `WARNING`: the library binds stdlib
loggers, which have no handler of their own. Importing Hansard never prints anything.

### What a line looks like

```json
{"meeting": "9f2c1e...", "stage": "recognise", "duration_seconds": 5.28, "utterances": 1.0,
 "words": 17.0, "event": "stage.completed", "level": "info",
 "logger": "hansard.application.pipeline", "timestamp": "2026-08-25T16:56:42.172424Z"}
```

`console` renders the same event as:

```
2026-08-25T16:56:42.172424Z [info  ] stage.completed  [hansard.application.pipeline] duration_seconds=5.28 stage=recognise
```

### Redaction

The processor chain ends with two processors that run on every event, whichever renderer is
selected.

`redact_secrets` replaces a value with `***` when:

* the value is a `pydantic.SecretStr` or `SecretBytes`, anywhere — top level, inside a dictionary,
  inside a list or tuple, up to four levels deep; or
* the field name matches `password`, `passphrase`, `secret`, `token`, `credential`, `authorization`
  / `authorisation`, `cookie`, `bearer`, `signature`, or `key` / `keys` as a whole word (so
  `api_key`, `access-key` and `secret_key` match; `monkey` and `keyword` do not).

```python
logger.info("delivery.attempted", channel="email", smtp_password=SecretStr("hunter2"))
```

```json
{"channel": "email", "smtp_password": "***", "event": "delivery.attempted", "level": "info", ...}
```

Because `key` is treated as a credential name, artefact keys are logged as `artifact` instead.

### Content elision

`text`, `transcript`, `body` and `quote` are the field names that carry meeting content in this
codebase. The elision processor replaces each of them with its length:

```python
logger.info("minutes.composed", body="Relevé de décisions du comité")
```

```json
{"body": "<elided 29 characters>", "event": "minutes.composed", ...}
```

The default preview length is zero — the content is **dropped**, not shortened. An operator who
needs a prefix for debugging can pass one explicitly
(`configure_logging(settings.runtime, content_preview_characters=40)`), which renders
`"Relevé de décisions du comité"` as a 40-character prefix followed by the total length. There is no
environment variable for it, on purpose: turning content logging on has to be a deliberate change in
a deployment's code path, not a variable somebody flips in a hurry.

The rule the code follows is that the event name and the field names are constants, never
interpolated content, and that only measurements and identifiers accompany them. Exceptions are
logged by type (`error: "TimeoutError"`), never by message, because exception messages from third
parties can contain a recipient address or a fragment of a document.

### Stage events

Every pipeline boundary emits `stage.started` at `DEBUG` and one of `stage.completed` /
`stage.failed` at `INFO` / `WARNING`, always with `stage`, `duration_seconds` and the meeting
identifier.

| Stage | Emitted by | Extra measurements |
| --- | --- | --- |
| `capture` | `MeetingService` | `audio_seconds` |
| `transcribe` | `MeetingService` | `words`, `speakers` |
| `minutes` | `MeetingService` | `composed` |
| `render` | `MeetingService` | `artifacts` |
| `persist` | `MeetingService` | `store`, `artifacts` |
| `enhance` | `TranscriptionPipeline` | |
| `voice_activity` | `TranscriptionPipeline` | `speech_spans` |
| `recognise` | `TranscriptionPipeline` | `utterances`, `words` |
| `language_drift` | `TranscriptionPipeline` | `redecoded`, `words` |
| `identify_language` | `TranscriptionPipeline` | `languages`, `code_switched` |
| `diarise` | `TranscriptionPipeline` | `speakers` |
| `refine` | `TranscriptionPipeline` | |
| `attribute` | `TranscriptionPipeline` | |
| `resolve_names` | `TranscriptionPipeline` | `named_speakers` |

`language_drift` is absent when `HANSARD_ASR__LANGUAGE_DRIFT_GUARD=false`. Its `redecoded` field is
`1.0` when the recogniser was found to have settled on the wrong language and the audio was decoded
again on shorter segments; on that path the stage also emits `recognition.language_drift` at WARNING
with the two disagreeing language tags, then either `recognition.language_recovered` at INFO with the
segment ceiling that fixed it, or `recognition.language_unrecovered` at WARNING when no rung reached
the required share. A meeting that emits `language_unrecovered` should be treated as suspect output.

`identify_language` is absent when `HANSARD_ASR__IDENTIFY_LANGUAGE=false`. Its `languages` field
counts the languages that passed the minority threshold and `code_switched` is `1.0` when more
than one did — so a dashboard can tell a bilingual meeting from a monolingual one without reading
the transcript. Neither field carries any text.

### Capture events

A live Teams capture emits two events of its own, from `TeamsBrowserCapture`. Neither carries any
meeting content.

| Event | Level | Fields | Meaning |
| --- | --- | --- | --- |
| `capture.meeting_state` | INFO | `state`, `saw_roster` | The notetaker's reading of the page changed |
| `capture.meeting_state_lost` | WARNING | `state` | The page stopped looking like a live meeting, and the capture ended |
| `capture.roster_panel_unavailable` | WARNING | | The participants panel could not be opened |

`capture.meeting_state` is emitted on transitions only, not on every poll, so a healthy meeting
produces one line at admission and one when it ends. It is the first thing to read when a bot stays
in a call that is visibly over: `in_meeting` means Teams is still presenting an active call to the
page, `unknown` means the page is showing something Hansard does not recognise.

`capture.meeting_state_lost` is the backstop for a page Hansard cannot read: any state other than
`in_meeting` that survives `HANSARD_CAPTURE__STATE_TIMEOUT_SECONDS` ends the capture with
`stop_reason=state_lost`. It is a WARNING rather than an INFO because the meeting ended without
Hansard recognising how — the recording itself is finalised and transcribed normally, and the
`state` field says what the page was showing so the missing text or selector can be added.

`saw_roster` reports whether any roster has been observed yet. It matters because
`HANSARD_CAPTURE__ALONE_TIMEOUT_SECONDS` arms only once a roster has been seen — a notetaker that
cannot see who else is in the meeting cannot conclude it is alone. Roster observations come from the
participants panel, which Hansard opens after joining; `capture.roster_panel_unavailable` says that
open failed, and that the alone timeout is therefore disarmed for this meeting. The silence and
duration timeouts are unaffected.

Delivery adds `delivery.completed` and `delivery.failed` with the channel and the duration — never
the recipient.

## Metrics

### Enabling the endpoint

```bash
pip install 'hansard[observability]'     # prometheus-client
HANSARD_API__METRICS_ENABLED=true        # the default
```

With both in place, `hansard serve` exposes `GET /metrics` in the Prometheus text format. The route
is unauthenticated, like `/healthz` and `/readyz`, so a scraper does not need the API key; put the
port behind your network policy rather than behind a header. Set `METRICS_ENABLED=false` and the
route is not registered at all — a request for it returns `404`.

If `prometheus-client` is not installed, every metric call in Hansard is a no-op and the route is
also absent. Nothing else changes: measurement is optional, and its absence is not an error.

For a process that does not serve the API, `hansard.observability.metrics.start_metrics_server()`
starts a standalone exporter over the same registry, on `HANSARD_API__PORT` (default `9095`).

### What is exposed

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `hansard_build_info` | info | — | Version, component, ASR engine, model, compute type, configured language. |
| `hansard_meetings_scheduled_total` | counter | — | Meetings accepted by the API. |
| `hansard_job_state_transitions_total` | counter | `state` | Job lifecycle, counted by the state entered (`pending`, `transcribing`, `completed`, `failed`). |
| `hansard_queue_pending` | gauge | `stream`, `group` | Jobs waiting in the in-process queue. |
| `hansard_asr_transcribe_duration_seconds` | histogram | `model`, `compute`, `language` | Wall-clock seconds spent recognising one meeting. |
| `hansard_asr_realtime_factor` | histogram | `model`, `compute`, `language` | Processing seconds ÷ audio seconds. Below 1 is faster than real time. |
| `hansard_asr_failures_total` | counter | `reason` | Recognition failures, by exception type. |
| `hansard_diarization_speakers` | histogram | — | Distinct speakers found per diarised meeting. |
| `hansard_minutes_generated_total` | counter | — | Minutes documents composed. |
| `hansard_delivery_attempts_total` | counter | `channel`, `result` | Delivery attempts, `success` or `failure`. |
| `hansard_object_storage_reachable` | gauge | — | `1` when the artifact store accepted the last write. |
| `hansard_bot_join_attempts_total`, `hansard_bot_join_duration_seconds`, `hansard_bot_active` | counter, histogram, gauge | `result` | Meeting-join outcomes for the browser capture bot. |

The `language` label is bounded: it is normalised to a two-letter code from a known list, and
anything else becomes `unknown`. A meeting in an unexpected language can therefore never create a
new time series.

### What is deliberately absent

There is no per-meeting, per-user or per-recipient metric, and there never will be: those labels are
in `FORBIDDEN_LABEL_NAMES` and declaring one raises at import time. If you need to trace a single
meeting, use the logs — they carry the meeting identifier, which is a random UUID with no meaning
outside your own job store.

## Related reading

- [Configuration](configuration.md) — the `runtime`, `api` and `storage` sections
- [Metrics](metrics.md) — the quality metrics (WER, cpWER, DER), which are a different thing entirely
- [Deployment](deployment.md) — `ServiceMonitor`, `PrometheusRule` and the Grafana dashboard
- [Sovereignty](sovereignty.md) — the guarantees this page implements
