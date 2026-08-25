# Architecture

This page is for someone deciding whether to trust this code and whether they
could extend it. It describes the shape of the system, why it has that shape,
what actually runs during a meeting, and where the seams are.

## The shape: ports and adapters

`src/hansard/` is laid out as a hexagon.

| Package | Contains | Rule |
| --- | --- | --- |
| `domain/` | `AudioClip`, `TimeSpan`, `Word`, `Utterance`, `Transcript`, `SpeakerTurn`, `Diarization`, `Roster`, `Minutes`, the error hierarchy, and a Hungarian-algorithm assignment solver | Frozen dataclasses and pure functions. No I/O, no models, no third-party clients. `numpy` is the only external import. |
| `ports/` | `Protocol` interfaces: `SpeechRecognizer`, `Diarizer`, `SpeakerAttributor`, `SpeakerNamer`, `AudioEnhancer`, `VoiceActivityDetector`, `MeetingCapture`, `MinutesWriter`, `TextGenerator`, `MinutesPublisher`, `ArtifactStore` | Types and signatures only. Every one is `runtime_checkable`, so conformance is testable without inheritance. |
| `adapters/` | The implementations: ONNX, sherpa-onnx, ffmpeg, Playwright, SMTP, Microsoft Graph, an OpenAI-compatible HTTP client | Each subpackage carries its own registry and imports its heavy dependency **inside** the factory function, so an install without an extra still imports cleanly. |
| `application/` | `TranscriptionPipeline`, which sequences enhancement, detection, recognition, diarization, refinement, attribution and naming; `MeetingService`, which wraps it with capture, minutes and rendering; and `JobRecord`/`JobStore`/`JobQueue` | Depends on ports only. It has never heard of ONNX. |
| `interfaces/` | The Typer CLI (`version`, `doctor`, `transcribe`, `serve`, `join`) and the FastAPI application behind `serve` | Drivers. Both compose the same `MeetingService`. |
| `rendering/` | Markdown, HTML, JSON, WebVTT, SubRip and plain-text renderers, plus bilingual strings and a timecode module | Domain objects in, bytes out. |
| `evaluation/` | The quality harness, the text normalizers, the metric implementations, corpus preparation and reporting | Depends on `ports` and `domain`, never on `adapters`. |
| `observability/` | Prometheus metric definitions and the exporter | Optional; absent `prometheus-client`, the module degrades to no-ops. |

`factory.py` is the composition root for the pipeline. It is the one place that
reads `Settings` and decides which adapter each port gets, so nothing else in the
codebase knows both a setting and an implementation. The CLI and the API each add
a thin composition of their own — capture engine, minutes writer, delivery
dispatcher — and hand the result to the same `MeetingService`.

The two drivers differ only in how work arrives. `hansard join` runs one meeting
and exits. `hansard serve` accepts submissions on `/v1/meetings`, hands them to an
in-process `JobQueue` whose worker count is `runtime.max_concurrent_meetings`, and
exposes state and artefacts over `/v1/meetings/{id}`. The job store is in memory
and bounded, so state does not survive a restart; artefacts do, because they are
files under `runtime.workspace`.

### Why this shape

Two reasons, and neither is architectural taste.

**Every model is replaceable, and that is not hypothetical.** The choice of
speaker-embedding model moved speaker confusion from 47 % to 0.01 % on identical
audio ([benchmarks](benchmarks.md#5-engineering-findings-worth-knowing)). A
project that had welded one embedding model into its diarization code would have
had to rewrite that code to find that out. Here it is a filename in a setting.
The same applies to the recogniser, the summariser and the delivery channel: if
a better French ASR model ships next quarter, adopting it is a new adapter, not
a refactor.

**The quality harness depends only on the ports.**
`hansard.evaluation.harness` imports `hansard.ports.asr` and
`hansard.ports.diarization` and nothing from `adapters/`. It can therefore score
*any* implementation of those protocols — a candidate model, a competitor, a
stub, a deliberately broken one — with the same code that produces the published
numbers. Benchmarking is not a special mode of the application; it is a
different driver of the same ports.

## Ports and their implementations

Everything below is what is in the tree today.

| Port | Module | Implementations |
| --- | --- | --- |
| `SpeechRecognizer` | `ports/asr.py` | `OnnxRecognizer` (`adapters/asr/onnx_engine.py`), `NullRecognizer` (`adapters/asr/null_engine.py`) |
| `LanguageIdentifier` | `ports/asr.py` | None. Parakeet detects language internally, so nothing has needed it. |
| `Diarizer` | `ports/diarization.py` | `SherpaDiarizer` (`adapters/diarization/sherpa.py`), `NullDiarizer` |
| `SpeakerAttributor` | `ports/diarization.py` | `WordLevelAttributor` (`adapters/attribution/fusion.py`) |
| `SpeakerNamer` | `ports/diarization.py` | `RosterSpeakerNamer` (`adapters/attribution/naming.py`) |
| `AudioEnhancer` | `ports/enhancement.py` | `FfmpegEnhancer`, `PeakNormaliser` |
| `VoiceActivityDetector` | `ports/enhancement.py` | `SileroVoiceActivityDetector`, `EnergyVoiceActivityDetector` |
| `MeetingCapture` | `ports/capture.py` | `TeamsBrowserCapture` (`adapters/capture/teams.py`), `FileCapture`, `NullCapture` |
| `MinutesWriter` | `ports/summarization.py` | `LlmMinutesWriter`, `ExtractiveMinutesWriter` |
| `TextGenerator` | `ports/summarization.py` | `OpenAiCompatibleGenerator` |
| `MinutesPublisher` | `ports/delivery.py` | `FilesystemPublisher`, `EmailPublisher`, `WebhookPublisher`, `TeamsChatPublisher` (Graph), `TeamsBotPublisher` (Bot Framework), and `AddressRoutedPublisher`, which dispatches by address scheme |
| `ArtifactStore` | `ports/storage.py` | **None.** `adapters/storage/` is empty; the `storage` settings section is inert. Artefacts are written to `runtime.workspace` by `MeetingService` and to `delivery.output_dir` by `FilesystemPublisher`. |
| `JobStore` | `application/jobs.py` | `InMemoryJobStore`. Declared beside its use rather than in `ports/`, because it is an application concern rather than an external system. |

Rendering has its own two protocols in `rendering/ports.py`, `TranscriptRenderer`
and `MinutesRenderer`, implemented six and three times respectively. See
[output formats](output-formats.md).

`GraphTranscriptFallback` (`adapters/capture/graph_transcript.py`) sits apart
from the capture port: it pulls a transcript Teams already made. It is disabled
by default, raises if used without being explicitly enabled, and emits a
`NonSovereignFallbackWarning` when it is. It exists because some tenants will not
permit a bot, not because it is a good idea.

## Data flow, from join to delivery

```
join URL
   │
   ▼  MeetingCapture.capture()
┌──────────────────────────────────────────────────────────────────┐
│ PulseAudio null sink is created; Chromium starts under Xvfb and  │
│ plays into it. ffmpeg records the sink's monitor source to WAV.  │
│ In parallel the browser session reports roster changes and the   │
│ active-speaker signal, which a reducer folds into a timeline.    │
└──────────────────────────────────────────────────────────────────┘
   │  16 kHz mono WAV  +  Roster(participants, observations)
   ▼  TranscriptionPipeline.run(clip, request, roster)
   │
   ├── enhance ──────────► high pass + loudnorm ─────┐
   │                                                 ├─► RECOGNITION CHAIN
   ├── voice activity ───► Silero VAD ───────────────┘
   │                       │
   │                       └─► plan_segments(): merge, split at 30 s, pad 0.2 s
   │
   ├── recognise ────────► Parakeet TDT, batched, word timestamps
   │
   ├── enhance (again) ──► high pass only ───────────► DIARIZATION CHAIN
   │
   ├── diarise ──────────► pyannote segmentation + TitaNet embeddings,
   │                       then clustering
   │
   ├── refine ───────────► speech the VAD found but the diarizer left
   │                       uncovered is given to the nearest turn
   │
   ├── attribute ────────► word-level fusion (below)
   │
   └── resolve names ────► clusters matched to roster display names
                           │
                           ▼  Transcript
                           ├─► VocabularyBiaser: phonetic correction
                           │                     against your glossary
                           ├─► MinutesWriter: LLM map-reduce with grounding,
                           │                  or deterministic extraction
                           └─► renderers ─► DeliveryDispatcher ─► filesystem
                                                                  email
                                                                  webhook
                                                                  Teams
```

### The two audio chains

The single most consequential structural decision in the pipeline is that
**recognition and diarization receive different audio derived from the same
source**.

Look at `TranscriptionPipeline.run`. The enhanced clip — high pass, optional
denoise, EBU R128 loudness normalisation — goes to the voice-activity detector
and the recogniser. The diarizer receives a *separate* derivation taken from the
original `clip`, through a filter chain that is high pass only.

The reason is measured, not aesthetic. Applying loudness normalisation before
diarization produced five clusters for a three-speaker meeting and a 41.07 %
error rate, against 14.75 % with a plain high-pass filter. `loudnorm` is a
dynamic-range process: it applies time-varying gain, which alters the spectral
envelope over time. That envelope is precisely what a speaker-embedding model
encodes. Normalising it makes two speakers look more alike and one speaker look
like two at different points in the meeting.

Recognition wants the opposite treatment. An acoustic model trained on
loudness-normalised data does better on loudness-normalised input, and the
transcript does not care whether a speaker's timbre stayed constant.

So both are served, from one recording, at the cost of one extra ffmpeg pass.

### Word-level attribution

`WordLevelAttributor` turns two independent views of the meeting — a sequence of
words with timestamps, and a set of speaker turns — into a transcript where each
word carries a speaker. Both inputs are imperfect at exactly the same place: the
boundary between turns.

The algorithm has five parts, and each one exists because of a specific failure.

**1. Boundary dilation.** Each word's span is widened by
`attribution.boundary_tolerance_seconds` (0.30 s) before it is compared with any
turn. Word timestamps come from a transducer's frame alignment and turn
boundaries come from a segmentation model; they disagree by a few hundred
milliseconds as a matter of course. Without dilation, a word that starts 100 ms
before its speaker's turn officially begins overlaps *nothing* and falls to the
fallback path — which is the common case for the first word of every turn.

**2. Per-word overlap scoring.** For each dilated word span, every turn it
intersects contributes `overlap_seconds × turn_confidence` to that turn's
speaker. The result is a small score distribution over candidate speakers per
word. Confidence weighting matters because refined turns — spans invented by the
speech-coverage refiner rather than observed by the diarizer — carry a
confidence of 0.6, and absorbed micro-clusters carry half their original
confidence. Evidence is therefore weighted by how much of it is evidence.

**3. Dominance margin.** If the leading speaker's score is at least
`dominance_margin` (1.5×) the runner-up's, that word is decided outright. This
is the overwhelming majority of words: mid-turn, one speaker's turn covers the
whole dilated span and nothing else comes close. Words with no clear winner are
left to the smoothing pass.

**4. Viterbi smoothing over the word sequence.** The whole word sequence is run
through a hidden Markov model whose states are the speakers. Emissions are the
log of each word's normalised overlap distribution; transitions carry a
speaker-switch prior of 0.05 against staying with the same speaker.

This is the part that earns its keep. Overlap scoring alone is memoryless: at a
turn boundary, with crosstalk, or on a short function word whose span barely
extends past its own duration, the top-scoring speaker can flip for one word and
flip straight back. That produces a transcript in which *Aurélie* interrupts
*Jean-Luc* to say "et" and then falls silent. The switch prior makes a
single-word alternation cost more than it can gain from a marginal overlap
advantage, so isolated flips are absorbed into the surrounding turn while
genuine turn changes — which are supported by many consecutive words — survive
easily.

**5. Nearest-turn fallback.** A word that overlaps no turn even after dilation
looks for the closest turn within `nearest_turn_horizon` (2.0 s) and adopts its
speaker. Beyond that horizon it emits a flat distribution and lets the Viterbi
path decide, which in practice continues the current speaker. This covers speech
the diarizer missed entirely, so a missed segment costs a *possibly* wrong
speaker rather than a word marked `unknown`.

The final assignment takes the dominant speaker where there was one and the
smoothed path everywhere else. Words are then regrouped into utterances at every
speaker change, and adjacent utterances by the same speaker within one second are
merged back together, so the reader sees paragraphs rather than one line per
word.

When the recogniser produced no word timestamps, the same machinery runs over
utterance spans instead, treating each utterance as a single unit.

### Naming the clusters

Diarization yields `speaker_00`, `speaker_01`, … `RosterSpeakerNamer` maps those
onto real names using the active-speaker observations the browser collected. It
builds a matrix of overlap between each cluster's turns and each participant's
observed speaking spans, then solves it as a maximum-weight bipartite assignment
with the Hungarian algorithm in `domain/matching.py` — so it finds the globally
best one-to-one pairing rather than greedily assigning the loudest speaker first.

Each proposed pairing then has to clear two gates: `coverage`, the share of that
cluster's speaking time explained by the matched participant, must be at least
`attribution.min_observation_overlap`; and `margin`, the lead over the
second-best participant as a share of speaking time, must be at least 0.15. A
pairing that fails either gate keeps its `Speaker N` label. A confidently wrong
name is worse than an honest anonymous one.

## Threading, memory and concurrency

The division is deliberate and visible in the type signatures: **the inference
path is synchronous, the I/O path is `async`.**

| Stage | Nature | How it runs | Where the memory goes |
| --- | --- | --- | --- |
| Audio load and decode | CPU + subprocess | Synchronous, ffmpeg via `subprocess.run` | The whole clip is float32 in RAM: about 3.8 MB per minute at 16 kHz |
| Enhancement | Subprocess | Synchronous, samples piped through ffmpeg | A second copy of the clip during the pipe |
| Voice activity | CPU, ONNX | Synchronous | ~2 MB of model |
| Recognition | CPU or GPU, ONNX | Synchronous, batched by `asr.batch_size` | The dominant cost: about 1.4 GB resident for the INT8 model, plus activations proportional to batch size |
| Diarization | CPU or GPU, ONNX | Synchronous | 46 MB of models, plus one embedding per segment |
| Attribution and naming | Pure Python | Synchronous | Negligible |
| Capture (browser, PulseAudio, roster) | I/O bound | `async`, `asyncio` throughout | The recording streams to disk, not to memory |
| Delivery | Network | `async`, targets fanned out with `asyncio.gather` and a per-target timeout | Negligible |
| Minutes generation | Network, one request at a time | Synchronous `httpx` behind the `TextGenerator` port | The transcript plus one chunk of prompt |
| Job orchestration | Coordination | `async`; `MeetingService` pushes each blocking stage through `asyncio.to_thread` so the event loop keeps serving requests | The job store holds up to 512 records in memory |

Nothing in the inference path is threaded by Hansard. Parallelism inside
recognition and diarization belongs to ONNX Runtime, controlled by
`asr.intra_op_threads`, `asr.inter_op_threads` and `OMP_NUM_THREADS`. This is
deliberate: an application-level thread pool on top of a runtime that is already
saturating every core produces contention, not throughput. Running several
meetings at once is a matter of running several worker processes, which is what
the Helm chart does.

Running several meetings at once inside one `serve` process is governed by
`runtime.max_concurrent_meetings`; each concurrent job holds its own recogniser,
so that setting is a memory decision more than a throughput one.

Peak resident memory for the full CPU pipeline was measured at 2.9 GB, with
recognition alone at 1.4 GB. Time splits roughly 55 % recognition, 40 %
diarization, 5 % everything else. Both scale with cores. See
[benchmarks](benchmarks.md#4-efficiency).

`PipelineOutcome` records per-stage wall-clock time, and its `real_time_factor`
is the ratio of total processing time to audio duration — the figure the CLI
prints and writes into `metrics.json`.

## Extension points

### Adding an ASR engine

Three steps, no changes anywhere else.

**1. Implement the protocol.** In `src/hansard/adapters/asr/my_engine.py`:

```python
from dataclasses import dataclass

from hansard.domain.audio import AudioClip
from hansard.domain.transcript import Transcript, Utterance
from hansard.ports.asr import EngineProfile, RecognitionHints


@dataclass(slots=True)
class MyRecognizer:
    model_path: str

    @property
    def profile(self) -> EngineProfile:
        return EngineProfile(
            name="my-engine",
            languages=("fr", "en"),
            emits_word_timestamps=True,
            emits_punctuation=True,
            resident_memory_mb=900,
            license_identifier="apache-2.0",
        )

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        spans = hints.segments or (clip.span,)
        utterances = tuple(self._decode(clip.extract(span), span) for span in spans)
        return Transcript(
            utterances=utterances,
            language=hints.language,
            audio_duration=clip.duration,
        )
```

`EngineProfile` is not decoration. It is how the rest of the system knows whether
to expect word timestamps — without them, attribution falls back to
utterance-level assignment — and it is what appears in the provenance footer of
the rendered output.

Emit `Word` objects with real spans if you can. Word-level timestamps are what
make the attribution described above possible.

**2. Register it.** At the bottom of `adapters/asr/registry.py`:

```python
def _build_mine(settings: AsrSettings, models_dir: Path) -> SpeechRecognizer:
    from hansard.adapters.asr.my_engine import MyRecognizer

    return MyRecognizer(model_path=str(models_dir / settings.model_id))


register_recognizer("mine", _build_mine)
```

Import the heavy dependency *inside* the factory. Registration must stay cheap,
because the module is imported whether or not your engine is selected.

**3. Make it selectable.** Add `"mine"` to the `AsrEngine` literal in
`config.py`, then `HANSARD_ASR__ENGINE=mine`. An unknown name already fails
loudly: `ConfigurationError: unknown ASR engine 'mine', available: (...)`.

**Then measure it.** Because the harness talks to the port, your engine can be
scored by the same code that produced the published numbers:

```bash
make bench-asr        # French and English word error rate
make bench-meetings   # cpWER: transcription and attribution together
```

A recognition change with no benchmark run is not reviewable. See
[metrics](metrics.md).

### Adding a delivery channel

Implement `MinutesPublisher`:

```python
@dataclass(frozen=True, slots=True)
class SignalPublisher:
    endpoint: str

    @property
    def channel(self) -> DeliveryChannel:
        return DeliveryChannel.WEBHOOK

    async def publish(self, target: DeliveryTarget, payload: Payload) -> None:
        ...
```

`publish` is `async` and must raise on failure — `DeliveryDispatcher` catches the
exception, records it against that target, applies the per-target timeout, and
carries on with the others. One failing channel never blocks the rest.

Register a factory in `adapters/delivery/registry.py` with
`register_publisher(DeliveryChannel.X, build_x)`. If your channel accepts more
than one address form, follow the Teams pattern and wrap the variants in an
`AddressRoutedPublisher`, which selects by URI scheme and produces an actionable
error listing the schemes it does understand. Adding a genuinely new channel kind
also means a new member of the `DeliveryChannel` enum in `domain/meeting.py`.

Existing channels and their address formats are in [delivery](delivery.md).

## Design decisions, and why

**ONNX Runtime rather than PyTorch.** Parakeet is a NeMo model and the obvious
route would be `nemo-toolkit`, which brings PyTorch and CUDA libraries with it.
The INT8 ONNX export is about 600 MB on disk and roughly 1.4 GB resident; the
PyTorch path is several gigabytes of wheels before any weights are loaded, and it
puts a CUDA-shaped dependency into an image that has to run on CPU. The CPU
worker image asserts this: the build fails if `torch` appears in the virtualenv.
The cost of the choice is that model support is limited to what exports cleanly
to ONNX, which is a real constraint we accept.

**Not NVIDIA Sortformer as the default diarizer.** Sortformer is an excellent
end-to-end diarizer and was evaluated. It has a hard architectural cap of four
speakers, and its published error rate roughly doubles beyond that. Real meetings
routinely have six to ten participants. The sherpa-onnx path —
pyannote segmentation for turns, TitaNet embeddings, clustering — has no such
cap; it detected 3, 6 and 9 speakers exactly on our fixtures without being told
the count. A diarizer that is better on four speakers and unusable on nine is the
wrong default for a meeting tool. `HANSARD_DIARIZATION__ENGINE=sortformer` is
accepted as a name today but resolves to the same sherpa implementation.

**Not Whisper as the default recogniser.** Whisper is the reflexive choice and it
is the wrong one here for two reasons. Published French Common Voice word error
rate is **11.06 %** for `whisper-large-v3` against **6.35 %** for Parakeet TDT
0.6b v3 — and French is a first-class meeting language for this project, not an
afterthought. Second, Whisper is documented to hallucinate on silence, emitting
plausible sentences where nobody spoke. In a verbatim record, a fabricated
sentence attributed to a named person is a worse failure than a missing one.
Parakeet also emits word-level timestamps natively, which the attribution
algorithm depends on. The `whisper` engine name is reserved and the extra exists,
but the adapter module is not in the tree.

**No comments in the code.** Names, types and small functions carry the meaning;
explanations live in `docs/`. A comment drifts away from the code beside it
silently, whereas a wrong document is visible to a reader who is reading the
document *because* they do not know the answer. Where behaviour genuinely needs
justifying — the two audio chains, the embedding-model choice, the switch prior —
it is written down here, in [benchmarks](benchmarks.md), or in
`deploy/docker/models.manifest`, where it is long enough to actually explain
itself. If a piece of code needs a comment to be understood, that is a signal to
rewrite the code.

## Related reading

- [Configuration](configuration.md) — every setting, and which of them reach code
- [Benchmarks](benchmarks.md) — the measurements behind the decisions above
- [Metrics](metrics.md) — every formula the harness computes
- [Output formats](output-formats.md) — the rendering layer
- [Delivery](delivery.md) — channels, addresses and Graph limitations
- [Minutes](minutes.md) — the summarisation adapters and grounding
- [Sovereignty](sovereignty.md) — where every byte goes
