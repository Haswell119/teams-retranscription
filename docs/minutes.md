# Meeting minutes

Hansard writes the minutes of a meeting from its transcript, entirely on your own machines. The module
lives in `hansard.adapters.summarization` and speaks to nothing except, optionally, an OpenAI-compatible
model server **that you run yourself**. There is no cloud call, no API key to a third party, no telemetry,
and no code path that can leak a transcript out of the organisation.

Two writers implement the same `MinutesWriter` port:

| Writer | Engine name | Needs a model server | What it does |
| --- | --- | --- | --- |
| `ExtractiveMinutesWriter` | `extractive` | no | Ranks and selects real sentences from the transcript. Every word in the minutes was actually said. |
| `LlmMinutesWriter` | `llm` | yes | Map-reduce over the transcript with a local LLM, then verifies every claim against the transcript before emitting it. |

The `auto` engine probes the endpoint once and picks the LLM writer if it answers, the extractive writer if
it does not. **The feature therefore always works, even with no model at all.**

## What the minutes contain

`Minutes` (see `hansard.domain.minutes`) carries:

- **Title, language, generation timestamp, participants, speaking time** — the frame of the document.
- **Abstract** — an executive summary for somebody who did not attend.
- **Topics** — auto-detected chapters, each with a time span, a title, a summary and key points. Topic
  boundaries are computed from the transcript itself, not asked from the model, so they are stable and
  reproducible.
- **Decisions** — a first-class register. A decision is something the group actually settled. Suggestions,
  conditionals and open proposals are deliberately kept out.
- **Actions** — description, owner, due date (ISO-8601 when the meeting date is known).
- **Open questions** — questions raised and left unanswered, i.e. the risk register of the meeting.
- **Citations** — *on every decision, every action and every open question*: a time span, a speaker and a
  verbatim quote. This is the part nobody else ships, and the reason the rest can be trusted.

## Quick start with no LLM at all

```python
from hansard.adapters.summarization import ExtractiveMinutesWriter

writer = ExtractiveMinutesWriter()
minutes = writer.compose(transcript, roster, request)
```

That call touches no network socket. It is the guaranteed-available path: use it on an air-gapped runner,
on a CPU-only box, in CI, or as a smoke test before you provision a GPU.

## Running a local model

The generator speaks the `/chat/completions` subset of the OpenAI API, which every serious local runtime
implements. Point `HANSARD_MINUTES__ENDPOINT` at the `/v1` root of whichever server you run.

### Which model

| Hardware | Model | Why |
| --- | --- | --- |
| 8–16 GB VRAM, or CPU with 16 GB RAM | **Qwen3-8B-Instruct** (Q4_K_M GGUF) | The default. Genuinely multilingual, writes clean French, follows JSON schemas, 32k context. |
| 24 GB+ VRAM | **Mistral-Small-3.2-24B-Instruct** | French-native quality, Apache-2.0, best minutes of the three. |
| 6 GB VRAM / laptop | **Qwen3-4B-Instruct** | Degrades gracefully; keep `HANSARD_MINUTES__CHUNK_TOKENS` around 4096. |

Avoid English-only models (Llama-3.x-8B, Phi-mini): French minutes come out anglicised and the decision /
suggestion distinction collapses.

### llama.cpp

```bash
llama-server \
  -hf Qwen/Qwen3-8B-GGUF:Q4_K_M \
  --host 127.0.0.1 --port 8080 \
  --ctx-size 32768 \
  --n-gpu-layers 999 \
  --jinja
export HANSARD_MINUTES__ENDPOINT=http://127.0.0.1:8080/v1
export HANSARD_MINUTES__MODEL_ID=qwen3-8b
```

`--jinja` matters: it enables the chat template and, on recent builds, grammar-constrained JSON, which is
what makes `response_format` work.

### Ollama

```bash
ollama pull qwen3:8b
OLLAMA_HOST=127.0.0.1:11434 ollama serve
export HANSARD_MINUTES__ENDPOINT=http://127.0.0.1:11434/v1
export HANSARD_MINUTES__MODEL_ID=qwen3:8b
export HANSARD_MINUTES__CONTEXT_TOKENS=32768
```

Ollama defaults to a short context window; set `num_ctx` in a Modelfile if long meetings get truncated.

### vLLM

```bash
vllm serve Qwen/Qwen3-8B \
  --served-model-name qwen3-8b-instruct \
  --max-model-len 32768 \
  --host 127.0.0.1 --port 8000
export HANSARD_MINUTES__ENDPOINT=http://127.0.0.1:8000/v1
```

vLLM supports `response_format={"type": "json_schema"}` natively, so structured extraction is exact.

### LM Studio / TGI

LM Studio: start the local server, then `HANSARD_MINUTES__ENDPOINT=http://127.0.0.1:1234/v1`.
Text Generation Inference: `text-generation-launcher --model-id Qwen/Qwen3-8B --port 8080`, then
`HANSARD_MINUTES__ENDPOINT=http://127.0.0.1:8080/v1`.

### Checking the endpoint

```bash
curl -s "$HANSARD_MINUTES__ENDPOINT/models" | head
```

If that returns nothing, the `auto` engine will silently pick the extractive writer, and the `llm` engine
will fail with an explicit message naming the endpoint. That message is the single most common operator
mistake, so it is spelled out rather than hidden in a stack trace.

## Configuration

Every field of `MinutesSettings` is settable through the environment, prefix `HANSARD_MINUTES__`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HANSARD_MINUTES__ENABLED` | `true` | `false` forces the extractive writer and guarantees no network call. |
| `HANSARD_MINUTES__ENGINE` | `auto` | `llm`, `extractive` or `auto`. `auto` probes the endpoint once and falls back to extraction when it does not answer. |
| `HANSARD_MINUTES__ENDPOINT` | `http://localhost:8080/v1` | `/v1` root of your local server. |
| `HANSARD_MINUTES__MODEL_ID` | `qwen3-8b-instruct` | Model name as the server advertises it. |
| `HANSARD_MINUTES__API_KEY` | unset | Sent as `Authorization: Bearer …`. Held in a `SecretStr`, never logged, never in a repr. |
| `HANSARD_MINUTES__CONTEXT_TOKENS` | `32768` | The server's context window. |
| `HANSARD_MINUTES__MAX_OUTPUT_TOKENS` | `4096` | Upper bound on any single completion. |
| `HANSARD_MINUTES__CHUNK_TOKENS` | `8192` | Transcript tokens per map step. |
| `HANSARD_MINUTES__TEMPERATURE` | `0.2` | Keep it low; minutes are not creative writing. |
| `HANSARD_MINUTES__LANGUAGE` | unset | Forces the minutes language; otherwise taken from the meeting request, then from the languages actually observed in the transcript. Leave it unset for a bilingual meeting: forcing a single tag here makes every sentence be analysed with that language's cue phrases, which is exactly how the other language's decisions and deadlines get dropped. |
| `HANSARD_MINUTES__INCLUDE_CITATIONS` | `true` | Turning this off removes the grounding evidence; do not. |
| `HANSARD_MINUTES__INCLUDE_SPEAKING_TIME` | `true` | Per-speaker totals in the minutes. |

```python
from hansard.adapters.summarization import build_minutes_writer
from hansard.config import load_settings

writer = build_minutes_writer(load_settings().minutes)
minutes = writer.compose(transcript, roster, request)
```

The effective chunk budget is `min(CHUNK_TOKENS, CONTEXT_TOKENS - MAX_OUTPUT_TOKENS - 1024)`, never below
512, so a misconfigured context window degrades instead of overflowing the server.

## How the transcript is prepared

Both writers share the same preparation, so the two paths never disagree about what was said.

**Sentence units.** Utterances are split into sentences. When word timings are available the sentence span
comes from the words themselves; otherwise it is interpolated over the utterance. Every citation, quote and
time code in the minutes comes from these units.

**Chunking** (`chunking.py`). Long meetings are cut into LLM-sized excerpts:

- A dependency-free token estimator: `max(characters / density, words × 1.15)`, with density 3.9 for
  English and 3.3 for French. Measured against common BPE tokenisers it lands within roughly ±15 % and is
  biased to *over*-estimate, so a chunk never overflows the context window. It is a budget, not a
  tokeniser — do not use it for billing.
- Splits happen at utterance boundaries only, never mid-sentence. Within the last 20 % of a chunk, a long
  pause (≥ 2.5 s) is preferred, then a speaker change, then the plain boundary.
- Each chunk repeats a small overlap (~8 % of the budget, at least one utterance) from the previous chunk,
  marked as context the model must not report from. Boundary decisions stop getting lost.
- An utterance that is on its own bigger than the budget — a fifteen-minute monologue — is split on
  sentence boundaries with spans preserved, so citations stay exact.
- Every chunk keeps its `TimeSpan` and every line is numbered `[n]`, which is how the model anchors its
  quotes.

**Topic segmentation** (`topics.py`) is deterministic and LLM-free: TextTiling-style lexical cohesion.
Content words are stemmed with a light FR/EN suffix stripper, grouped into pseudo-sentences, and the
vocabulary overlap between the two blocks around each gap is measured by cosine similarity, smoothed, then
scored for depth. Boundaries above the `μ − σ/2` cutoff are snapped to the nearest speaker change or pause,
subject to a minimum topic duration. Stopword lists for both languages ship in `stopwords.py`; nothing is
downloaded at import time. Parameters scale with the length of the meeting, so a five-minute stand-up gets
one or two topics and a three-hour steering committee gets up to twelve.

## The extractive writer

`ExtractiveMinutesWriter` produces real minutes without any model.

- **Abstract** — TextRank. A sentence-similarity graph is built from shared content words, PageRank is
  power-iterated in numpy, and the top sentences are selected *under a coverage constraint*: the highest
  ranked sentence of every topic is taken first, then the remaining slots are filled globally, with a
  near-duplicate filter. Greetings and closings are recognised and kept out.
- **Decisions** — cue phrases in both languages (`on part sur`, `on valide`, `il est décidé`, `on retient`,
  `we agreed`, `let's go with`, `the decision is`, …) filtered by modal and conditional blockers
  (`si on`, `on pourrait`, `il faudrait`, `je propose`, `if we`, `maybe`, `we should`, `I suggest`, …).
  Strong performative cues survive a blocker; weak ones do not; a question is never a decision. A causal
  clause (`parce que`, `pour …er`, `because`, `so that`) is split off as the rationale.
- **Actions** — cue phrases plus owner attribution, in this order: `@mention`, first person commitment
  (`je m'en occupe`, `I'll take`), vocative (`Sofia, peux-tu …`, `…, Tom?`), third person (`Marc va …`,
  `Elena will …`), a named counterpart, the only other participant, or an explicit commitment in the reply.
  **If none of these apply the owner is left empty rather than guessed.** A request and its acceptance
  (`peux-tu … ?` → `oui, je m'en occupe`) are merged into a single action carrying both citations.
- **Dates** — French and English, absolute and relative: `le 12 mars`, `12/06/2026`, `2026-06-12`,
  `demain`, `vendredi prochain`, `d'ici la fin du mois`, `dans trois semaines`, `March 12`, `next Tuesday`,
  `by EOW`, `in 2 weeks`, `end of the month`. They are normalised to ISO-8601 against the meeting date;
  with no meeting date the raw phrase is kept verbatim. Conventions: end of week = Friday; "next
  &lt;weekday&gt;" = that weekday of the following calendar week; a bare month already past rolls to next
  year.
- **Open questions** — interrogatives that no other speaker answers within the following window, measured
  by content-word overlap and by explicit answer markers.

Everything it emits is a real sentence with a real citation, so the extractive minutes are grounded by
construction. Its weakness is style: it quotes rather than paraphrases, which reads well for decisions and
questions and a little raw for the abstract. **Use it when** you have no GPU, when the endpoint is down,
when you need bit-for-bit reproducible output, or when policy forbids generative text entirely.

## The LLM writer

`LlmMinutesWriter` runs map-reduce over the chunks.

**Map.** For each excerpt the model receives the numbered lines and returns strict JSON: a summary, and
lists of decisions, actions, questions and entities, each item carrying a verbatim `quote` and the
`utterance` number it came from. The system prompt (French, English, or the bilingual pack, chosen by the
meeting language) forbids invention, requires verbatim quotes, requires an empty list over a plausible
guess, and spells out the decision-versus-suggestion distinction. The bilingual pack adds two rules a
monolingual prompt has no reason to state: never translate a quote, and report each item in the language
it was spoken in rather than collapsing the meeting into one. Its blocker examples are drawn from both
languages, and the abstract is written in the dominant language while quoted material is left untouched.

**Resolution.** Every item is re-anchored locally, before anything is believed:

- The cited line number is resolved back to the real utterance; if the number is wrong, the quote is
  matched against the chunk instead. **An item that cannot be anchored anywhere is dropped.**
- The quote is checked against the transcript text. If the model paraphrased, the real sentence is
  substituted. A citation never contains a sentence that was not spoken.
- The owner is resolved against the roster. An owner the roster does not know becomes empty.
- The due date is re-extracted **from the cited utterance**, not from the model's answer. A deadline the
  model heard nowhere does not survive.

**Reduce.** Items are deduplicated across chunks with a combined lexical and phonetic similarity (the same
`hansard.adapters.asr.phonetics.similarity` used for vocabulary biasing, so ASR spelling variants of the
same sentence merge), citations are unioned, and a final call produces the abstract and the per-topic
summaries over the fixed topic segmentation.

**Degradation.** If the endpoint is unreachable, if it returns garbage, or if every mapped item fails
verification, the writer falls back to the extractive minutes and says so in the report. If only the
consolidation call fails, the mapped decisions and actions are kept and the abstract is produced
extractively. The minutes are never empty when the transcript has content.

## Grounding

This is the differentiator, so it is enforced by code rather than by a prompt.

After generation, `GroundingVerifier` checks each claim — abstract sentence, topic summary, key point,
decision, rationale, action, question — against the transcript:

1. The cited time range is resolved and padded by 20 s.
2. The content words of the claim are matched against the vocabulary of that window: exact, then stem,
   then phonetic key, so inflections and ASR variants still count as support.
3. The same is measured against the whole transcript.
4. Numbers and capitalised entities in the claim are checked against the numbers and tokens actually
   present in the transcript (speaker names and roster names count as present).

| Verdict | Condition | Effect |
| --- | --- | --- |
| `supported` | ≥ 60 % of content words in the cited window, no unsupported number | kept |
| `weak` | supported by the transcript but not by the cited window, or carries a number nobody said | kept and flagged |
| `unsupported` | < 50 % support anywhere in the transcript | **dropped** |

`LlmMinutesWriter.compose_with_report` returns a `GroundingReport` next to the minutes (`compose` returns the minutes alone, to satisfy the port):

```python
outcome = writer.compose_with_report(transcript, roster, request)
report = outcome.report
report.engine              # "llm", or "extractive" when it degraded
report.fallback_reason     # why it degraded, or None
report.supported_ratio     # share of claims fully supported by their own citation
report.dropped             # ClaimCheck objects that never reached the reader
report.unsupported_numbers # figures the transcript does not contain
report.unsupported_entities# names the transcript does not contain
report.is_clean            # nothing dropped, nothing flagged
report.notes               # per-excerpt failures, fallbacks, consolidation problems
```

You can also run the verifier by hand on any `Minutes`, including extractive ones or minutes produced
elsewhere:

```python
from hansard.adapters.summarization import GroundingVerifier

verified, report = GroundingVerifier(language="fr").verify(minutes, transcript, engine="extractive")
```

How to read it: `is_clean` true with `supported_ratio` 1.0 is the normal state for extractive minutes and
the target for LLM minutes. A non-empty `dropped` list means the model tried to invent something and was
stopped — worth checking the model choice or the temperature. A `weak` verdict usually means the citation
points at the wrong moment rather than that the fact is wrong. `fallback_reason` set means no LLM was
involved at all in the document you are reading.

## How this compares with Microsoft Copilot's meeting recap

| Capability | Copilot recap | Hansard |
| --- | --- | --- |
| AI notes and chapters | yes | yes, chapters computed deterministically from lexical cohesion |
| Recommended tasks with owners | yes, and reported to attribute tasks to the wrong person | owner only from an explicit signal; otherwise left empty and marked unassigned |
| Speaker timeline | yes | yes, plus per-speaker speaking time |
| **Decisions register** | none | first-class, with a suggestion-versus-decision filter in both languages |
| **Open questions / risks register** | none | first-class, with the speaker who raised each one |
| **Per-claim evidence** | none — no timestamp or utterance backing an individual bullet | every decision, action and question carries time span + speaker + verbatim quote |
| Hallucination control | prompt-level only | deterministic post-generation verification; unsupported claims are dropped, not shipped |
| Deadlines | reported to be missed or misheard | re-extracted from the cited utterance and normalised to ISO-8601 |
| Empty recap ("we didn't find any notes") | documented failure mode | impossible by construction: extractive minutes always exist |
| Meetings over ~2 hours | degrades; Microsoft advises splitting the meeting | map-reduce with overlap; a four-hour meeting is just more chunks |
| A meeting held in two languages | one language per meeting; multilingual mode needs Teams Premium | each item extracted with the cues of the language it was spoken in, nothing translated |
| Where your data goes | Microsoft 365 cloud | your machines only |
| Works offline / air-gapped | no | yes, with or without a model |
| Languages | many, quality varies | French and English are first-class and equally tested |

## Extending

- `patterns.py` holds every cue phrase, one list per language and category. Adding
  `on grave dans le marbre` to the decisions of your organisation is a one-line change with a unit test.
  A `mixed` meeting uses the union of both cue sets, but that union is only a safety net: each sentence
  is normally matched with the cues of the language *it* was spoken in, carried on `SentenceUnit.language`.
  See [multilingual](multilingual.md).
- `stopwords.py` holds the FR/EN stopword lists used by segmentation and ranking.
- `prompts.py` holds the system and user templates and the JSON schemas, as data, separate from code.
- `register_minutes_writer(name, factory)` adds an engine to the registry, exactly like the ASR one.

## Testing

```bash
.venv/bin/python -m pytest tests/summarization -q
```

The suite is fully offline: the text generator is stubbed, the HTTP client is an `httpx.MockTransport`, and
both a French and an English synthetic meeting are asserted end to end — decisions, action owners,
deadlines, open questions, citation correctness, hallucination rejection, endpoint failure and the
never-empty guarantee.
