# Output formats

Hansard turns a `Transcript` and a `Minutes` into the files a user actually receives. Everything in
`hansard.rendering` is pure, local and dependency-free at runtime: no network call, no CDN, no web font,
no telemetry. An HTML minutes file opens correctly on a laptop that has never been connected to the
internet, which is the whole point of a sovereign transcription stack.

Complete, real examples of every format live in [`examples/`](examples/) and are produced by the same code
paths the tests assert against.

## At a glance

| Format | `name` | Extension | Media type | Transcript | Minutes | Use it for |
| --- | --- | --- | --- | --- | --- | --- |
| Markdown | `markdown` | `.md` | `text/markdown; charset=utf-8` | yes | yes | Wikis, Teams/chat messages, pull requests, e-mail bodies |
| HTML | `html` | `.html` | `text/html; charset=utf-8` | yes | yes | The document you send to attendees; prints to PDF cleanly |
| JSON | `json` | `.json` | `application/json` | yes | yes | Machine-to-machine exchange, archiving, downstream analytics |
| WebVTT | `vtt` | `.vtt` | `text/vtt` | yes | no | Captions for the recording; drop-in replacement for a Teams transcript export |
| SubRip | `srt` | `.srt` | `application/x-subrip` | yes | no | Legacy players and editing suites that do not read WebVTT |
| Plain text | `text` | `.txt` | `text/plain; charset=utf-8` | yes | no | grep, diff, ticketing systems, anything that hates markup |

Formats that cannot produce minutes simply do not implement the minutes protocol — asking for one raises a
`ConfigurationError` instead of returning a half-empty file.

## Rendering something

```python
from datetime import UTC, datetime

from hansard.rendering import ModelProvenance, RenderContext, minutes_renderer_for, transcript_renderer_for

context = RenderContext(
    title="Weekly platform sync",
    started_at=datetime(2026, 6, 3, 9, 30, tzinfo=UTC),
    duration_seconds=1500.0,
    participants=roster.participants,
    language="en",
    timezone="Europe/Paris",
    provenance=(
        ModelProvenance(component="asr", engine="parakeet", model_id="nemo-parakeet-tdt-0.6b-v3"),
        ModelProvenance(component="minutes", engine="qwen3", model_id="qwen3-8b-instruct"),
    ),
)

renderer = minutes_renderer_for("html")
(output_dir / f"minutes{renderer.file_extension}").write_text(renderer.render_minutes(minutes, context))

captions = transcript_renderer_for("vtt")
(output_dir / f"captions{captions.file_extension}").write_text(captions.render_transcript(transcript, context))
```

`available_formats()`, `transcript_formats()` and `minutes_formats()` list what is registered.
`renderer_for(name)` returns the renderer without asserting a capability.

### The render context

| Field | Meaning |
| --- | --- |
| `title` | Meeting title used in headers, the `<title>` element and the WebVTT signature line |
| `started_at` | Timezone-aware (or naive) start; naive values are read as already being in `timezone` |
| `duration_seconds` | Meeting duration; falls back to `Transcript.audio_duration` for transcripts |
| `participants` | `Participant` tuple; `Minutes.participants` wins when it is populated |
| `language` | **Output** language, i.e. the language of headings and labels (`en`, `fr`, …) |
| `timezone` | IANA name (`Europe/Paris`); unknown names degrade to UTC rather than failing |
| `provenance` | `ModelProvenance` entries naming every model that touched the meeting |
| `generator` | Product name printed in the sovereignty footer, `Hansard` by default |

The *content* language (what people actually said) comes from `Transcript.language` / `Minutes.language` and
is shown in the header block. The *output* language comes from `RenderContext.language`. They are usually the
same, but a French meeting can be delivered with English headings by setting `language="en"`.

## Internationalisation

Every user-visible string is translated through `hansard.rendering.i18n`. English and French ship in the box;
an unknown or missing language falls back to English, and a partially translated catalogue falls back phrase
by phrase. Locale typography is respected: French uses `Actions à mener`, a space before the colon
(`Durée :`), a decimal comma and a space before `%` (`35,1 %`).

```
## Relevé de décisions

1. **La version 4.2 est livrée le 12 juin sans la locale allemande.** [00:00:23]
   - Justification : Les chaînes de facturation ne sont ni traduites ni relues.
```

Adding a language means adding one dictionary to `CATALOGUES`; no template or renderer changes.

## Markdown — `markdown`

Full examples: [`minutes.en.md`](examples/minutes.en.md), [`transcript.en.md`](examples/transcript.en.md),
[`minutes.fr.md`](examples/minutes.fr.md), [`transcript.fr.md`](examples/transcript.fr.md).

Use it when the destination renders Markdown: a wiki page, a chat message, a commit, an issue. It is also the
most reviewable format in a diff.

The transcript opens with a header block, then one speaker-grouped paragraph per turn. Consecutive turns from
the same speaker less than 1.5 s apart are merged, so the document reads like minutes rather than like a
caption file.

```markdown
# Weekly platform sync — Transcript

- **Date:** 3 June 2026 at 09:30 (UTC)
- **Duration:** 25 min
- **Participants:** Amara Okafor, Léa Fontaine, Jonas Weber
- **Language:** English (en)
- **Produced with:** parakeet (nemo-parakeet-tdt-0.6b-v3), sherpa (nemo_en_titanet_small.onnx), local (qwen3-8b-instruct)

---

**Amara Okafor** [00:00:08]

Good morning everyone, let us start with the release four point two readiness.
```

The minutes follow a fixed structure: executive summary, key decisions (each with its citation timecodes),
action items **as a table**, discussion by topic, open questions, speaking time, and a footer that states
where the processing happened.

```markdown
## Action items

| Owner | Action | Due | Source |
| --- | --- | --- | --- |
| Léa Fontaine | Disable the German locale in the 4.2 release branch and open a translation ticket. | 2026-06-10 | 00:06:20 |
| Unassigned | Draft the procurement request for the two GPU nodes. | — | — |

## Speaking time

| Speaker | Duration | Share |
| --- | --- | --- |
| Amara Okafor | 10 min 12 s | 40.8% |
| Léa Fontaine | 8 min 18 s | 33.2% |
```

Empty sections are never dropped silently: they render an italic line (`_No decision was recorded._`) so a
reader can tell the difference between "nothing was decided" and "the section is missing". Pipe characters in
cell text are escaped, so a decision about `on-premises | cloud` cannot break the table.

## HTML — `html`

Full examples: [`minutes.en.html`](examples/minutes.en.html),
[`transcript.en.html`](examples/transcript.en.html), [`minutes.fr.html`](examples/minutes.fr.html).

Use it as the artefact you actually hand to attendees, and as the print/PDF master. One file, nothing else
required.

- **Self-contained.** All CSS is inline. No script, no external stylesheet, no remote font, no tracking pixel.
- **Accessible.** Semantic `header`/`nav`/`main`/`section`/`article`/`footer`, a skip link, `scope` on every
  table header, `aria-labelledby` on sections and tables, a real `<time datetime="…">` for the meeting date,
  and speaking-time bars marked `aria-hidden` with the number always available as text.
- **Light and dark.** Colours are CSS custom properties switched by `prefers-color-scheme`.
- **Responsive.** Fluid type, a metadata grid that reflows, and tables that scroll inside their own container
  instead of breaking the page.
- **Printable.** A `@media print` block flattens colours, drops the navigation, and keeps sections, rows and
  list items from splitting across pages.

Templates live in `src/hansard/rendering/templates/` and are loaded with `jinja2.PackageLoader`, so they ship
inside the wheel. Autoescaping is on, and `StrictUndefined` turns a typo in a template into an error rather
than a blank in the delivered document.

## WebVTT — `vtt`

Full example: [`transcript.en.vtt`](examples/transcript.en.vtt).

Use it for captions on the recording, and wherever a Microsoft Teams transcript export was previously
consumed: the speaker convention is identical, so Hansard output is a drop-in replacement.

```vtt
WEBVTT - Weekly platform sync

NOTE
Transcribed locally by Hansard. No data left the organisation.

1
00:00:08.000 --> 00:00:14.600
<v Amara Okafor>Good morning everyone, let us start with
the release four point two readiness.</v>

2
00:00:15.200 --> 00:00:20.674
<v Léa Fontaine>The build is green on every runner, but
the German locale files still have forty</v>
```

Utterances without an identified speaker are emitted without a `<v>` tag rather than with a fabricated name.
`&`, `<` and `>` are escaped in both the cue text and the speaker name, and a title containing `-->` cannot
corrupt the signature line.

## SubRip — `srt`

Full example: [`transcript.en.srt`](examples/transcript.en.srt).

Same cues, comma decimal separators, and no `<v>` tag because SubRip has no speaker convention. The speaker
name is prefixed on the first line of a cue only when the speaker changes, which keeps the caption readable
without repeating a name on every screen.

```srt
1
00:00:08,000 --> 00:00:14,600
Amara Okafor: Good morning everyone, let us start with
the release four point two readiness.
```

### Cue layout rules

Both subtitle renderers share one cue builder (`hansard.rendering.composition.subtitle_cues`) configured by
`CueLayout`:

| Rule | Default | Behaviour |
| --- | --- | --- |
| `max_characters_per_line` | 42 | Greedy word wrap; a word longer than the limit keeps its own line rather than being cut |
| `max_lines` | 2 | Longer utterances are split into several consecutive cues |
| `minimum_duration` | 1.0 s | Very short utterances are stretched so they stay readable |
| `maximum_duration` | 7.0 s | Long cues are capped so captions do not linger |
| ordering | — | Cues are sorted, numbered from 1, and **never overlap**: a cue can only start once the previous one has ended |

When the ASR provides word timings and they line up with the text, cue boundaries use the real word times;
otherwise the utterance span is split proportionally to the characters in each cue.

## Plain text — `text`

Full example: [`transcript.en.txt`](examples/transcript.en.txt).

One line per turn, no markup, easy to grep and diff.

```text
[00:00:08] Amara Okafor: Good morning everyone, let us start with the release four point two readiness.
[00:00:25] Unidentified speaker: Sorry, could you repeat the last figure?
```

`PlainTextRenderer(include_header=True)` prepends the same metadata block as the other formats when the file
travels on its own.

## JSON — `json`

Full examples: [`transcript.en.json`](examples/transcript.en.json),
[`minutes.en.json`](examples/minutes.en.json).

This is the interchange format: stable field names, stable ordering, explicit `null`s, seconds as floats and a
human-readable timecode next to every span so a person can read the file too. Use it to archive a meeting, to
feed a search index, or to hand a meeting to another system. Text stays in the meeting's own language and
speaker labels are raw (`unknown` is not translated) — presentation belongs to the other formats.

### Versioning

Every document carries `schema_version`, currently **`1.1`**. Additive changes (new optional keys) bump the
minor version; removing or re-typing a field bumps the major version. Consumers should ignore unknown keys and
check the major version.

### Envelope

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | `"1.1"` |
| `kind` | string | `"transcript"` or `"minutes"`; the payload lives under a key of the same name |
| `generator.name` | string | `RenderContext.generator` |
| `generator.version` | string | Hansard version that produced the file |
| `meeting.title` | string | |
| `meeting.started_at` | string \| null | ISO 8601 |
| `meeting.timezone` | string | IANA name |
| `meeting.language` | string | Output language of the render context; `"mixed"` when the meeting was code-switched |
| `meeting.languages[]` | string | Languages actually spoken, most-spoken first; empty when only one was configured and none observed |
| `meeting.duration_seconds` | number | Seconds, 3 decimals |
| `meeting.participants[]` | object | `identifier`, `display_name`, `email`, `is_organizer`, `is_external` |
| `meeting.provenance[]` | object | `component`, `engine`, `model_id` |

### `transcript` payload

| Field | Type | Notes |
| --- | --- | --- |
| `language` | string \| null | Detected or configured language of the speech; `"mixed"` when both were spoken |
| `languages[]` | string | Every language observed above the minority threshold, most-spoken first |
| `language_shares` | object | Language tag to share of transcribed words, 4 decimals |
| `code_switched` | boolean | True when more than one language passed the minority threshold |
| `audio_duration_seconds` | number | |
| `word_count` | integer | |
| `speakers[]` | string | Labels in order of first appearance |
| `utterances[]` | object | See below |

Each utterance: `index` (integer, 0-based), `speaker` (string), `start`/`end` (numbers, seconds),
`timecode` (string, `hh:mm:ss.mmm` of `start`), `language` (string \| null), `confidence` (number 0–1),
`text` (string), and `words` — present **only** when word timings exist and `include_word_timings` is on.
Each word carries `text`, `start`, `end`, `confidence`, `speaker`.

```json
{
  "index": 0,
  "speaker": "Amara Okafor",
  "start": 8.0,
  "end": 14.6,
  "timecode": "00:00:08.000",
  "language": "en",
  "confidence": 0.94,
  "text": "Good morning everyone, let us start with the release four point two readiness.",
  "words": [{ "text": "Good", "start": 8.0, "end": 8.508, "confidence": 0.95, "speaker": "Amara Okafor" }]
}
```

### `minutes` payload

| Field | Type | Notes |
| --- | --- | --- |
| `title` | string | |
| `language` | string | Language the minutes were written in |
| `generated_at` | string | ISO 8601 |
| `abstract` | string | The executive summary |
| `participants[]` | object | Same shape as `meeting.participants` |
| `topics[]` | object | `title`, `summary`, `key_points[]`, `start`, `end`, `timecode` |
| `decisions[]` | object | `statement`, `rationale` (nullable), `citations[]` |
| `actions[]` | object | `description`, `owner` (nullable), `due_date` (nullable string), `citations[]` |
| `open_questions[]` | object | `question`, `raised_by` (nullable), `citations[]` |
| `speaking_time[]` | object | `speaker`, `seconds`, `share` (0–1, 4 decimals), sorted longest first |

A citation is `{ "speaker": …, "quote": …, "start": …, "end": …, "timecode": … }`.

```json
{
  "statement": "Release 4.2 ships on 12 June with the German locale disabled.",
  "rationale": "The billing strings are neither translated nor proof-read, and the release window is fixed.",
  "citations": [
    {
      "speaker": "Amara Okafor",
      "quote": "Then we ship four point two on the twelfth of June with the German locale disabled.",
      "start": 370.5,
      "end": 379.8,
      "timecode": "00:06:10.500"
    }
  ]
}
```

## The sovereignty footer

Markdown, HTML and plain-text headers state where the meeting was processed and which models were used, and
the WebVTT file repeats a short version in a `NOTE` block:

> Transcribed and summarised locally by Hansard using parakeet (nemo-parakeet-tdt-0.6b-v3), sherpa
> (nemo_en_titanet_small.onnx), local (qwen3-8b-instruct). No audio, transcript or minutes left the
> organisation.

The model list comes from `RenderContext.provenance`, so it is never a marketing claim: it is whatever
actually ran.

## Adding a format

A renderer is anything that satisfies `TranscriptRenderer` and/or `MinutesRenderer` — no base class to
inherit, no framework:

```python
from hansard.rendering import RenderContext, register_renderer


class CsvActionsRenderer:
    name = "csv-actions"
    media_type = "text/csv; charset=utf-8"
    file_extension = ".csv"

    def render_minutes(self, minutes, context: RenderContext) -> str:
        rows = ["owner,action,due"]
        rows += [f"{item.owner or ''},{item.description},{item.due_date or ''}" for item in minutes.actions]
        return "\n".join(rows) + "\n"


register_renderer(CsvActionsRenderer())
```

It is then returned by `available_formats()` and `minutes_renderer_for("csv-actions")`, and rejected by
`transcript_renderer_for("csv-actions")`. Reuse `hansard.rendering.composition` for speaker grouping,
speaking shares, cue splitting and metadata so a new format inherits the same behaviour as the built-in ones,
and `hansard.rendering.i18n` for anything a human will read.
