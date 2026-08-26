# Troubleshooting

Organised by what you saw, not by what the code calls it. Each entry gives the
symptom, the likely cause, and the fix.

Before anything else:

```bash
hansard doctor
```

Four of the five rows are real checks. What each one means, and what to do when
it says `missing`, is in [installation](installation.md#5-verifying-the-installation).

---

## Audio will not decode

### `HansardError: ffmpeg is required to read .m4a audio`

Also seen as `ffmpeg is required by FfmpegEnhancer` or
`ffmpeg is required to decode in-memory audio`.

**Cause.** ffmpeg is not on the PATH of the process. Hansard shells out to it to
decode anything that is not WAV, FLAC, OGG or Opus, to run the high-pass and
loudness filters, and to record from PulseAudio. There is no pure-Python
fallback.

**Fix.**

```bash
sudo apt-get install -y ffmpeg      # or dnf / brew
ffmpeg -version
hansard doctor                      # the ffmpeg row must read ok
```

If `ffmpeg -version` works in your shell but `doctor` still says `missing`, the
service runs as another user or under systemd with a trimmed PATH. Check the
PATH of the actual process, not of your login shell.

### `HansardError: ffmpeg decode failed: ...`

**Cause.** ffmpeg is present but rejected the file. The message carries the first
400 characters of ffmpeg's own stderr, which usually names the real problem: a
truncated download, a container with no audio stream, or a video file with a
codec this ffmpeg build lacks.

**Fix.** Reproduce it directly, and read what ffmpeg says.

```bash
ffmpeg -i meeting.m4a -f null -
ffmpeg -i meeting.m4a -ac 1 -ar 16000 meeting.wav   # then transcribe the WAV
```

### `HansardError: audio file not found: meeting.m4a`

The path does not exist from the working directory of the process. In Docker,
this is nearly always a path inside the container that was never mounted — check
the volume mappings, and remember the compose stack expects recordings in
`./inbox/`, visible as `/inbox/` inside the container.

---

## Models are missing

### `DiarizationError: diarization model missing: /models/sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx`

### `ModelFileNotFoundError: File 'silero_vad.onnx' not found in path '/models/silero'.`

### `RecognitionError: failed to load ONNX ASR model nemo-parakeet-tdt-0.6b-v3: ...`

**Cause.** All three are the same problem seen from three adapters:
`HANSARD_RUNTIME__MODELS_DIR` does not point at a correctly laid out bundle.
Hansard does not download weights at run time —
`HANSARD_RUNTIME__ALLOW_MODEL_DOWNLOADS` defaults to `false` — so a missing file
is a hard error rather than a silent fetch. That is intentional; see
[sovereignty](sovereignty.md).

Note that `hansard doctor` reports the models row as `ok` when the *directory*
exists. It does not look inside. A directory that exists but is empty, or one
that is a level above or below the real bundle, passes `doctor` and fails here.

**Fix.** Check the layout, which is fixed:

```bash
echo "$HANSARD_RUNTIME__MODELS_DIR"
ls "$HANSARD_RUNTIME__MODELS_DIR"
# expected: nemo-parakeet-tdt-0.6b-v3/  silero/
#           sherpa-onnx-pyannote-segmentation-3-0/  nemo_en_titanet_small.onnx
#           NOTICE  SHA256SUMS
```

The two most common mistakes are pointing at the parent (`/srv` instead of
`/srv/models`) and pointing at `.../models/nemo-parakeet-tdt-0.6b-v3`, one level
too deep.

If files are genuinely absent, fetch and verify the bundle:

```bash
deploy/docker/fetch-models.sh \
  deploy/docker/models.manifest deploy/docker/models.NOTICE ./models
cd models && sha256sum -c SHA256SUMS
```

Full layout and licences in
[installation](installation.md#3-getting-the-models).

In Kubernetes, this error means the init container did not populate the models
volume, or the worker mounted a different volume than the one it filled. See
[deployment](deployment.md).

### `cp: can't create directory '/models/./silero': Permission denied`

From `docker compose run --rm models`, on a compose stack older than this fix.
Docker creates the `models` volume owned by `root:root` the first time it is
mounted, and the copier ran unprivileged, so it could not write into it. The
compose file now runs that one service as root and the copier hands the
directory back to `10001:10001` before it exits; every service that reads the
weights mounts them read-only.

Pull the current `deploy/compose/docker-compose.yml` and re-run. To repair a
volume left behind by the old file without re-downloading:

```bash
docker run --rm -v hansard_models:/models busybox chown -R 10001:10001 /models
```

---

## It will not start at all

### `SettingsError: error parsing value for field "delivery" from source "EnvSettingsSource"`

Wrapped around a `json.decoder.JSONDecodeError`. A setting whose type is a list
or tuple was given a bare word. pydantic-settings parses complex types as JSON,
so every one of them needs JSON syntax in the environment:

```bash
HANSARD_DELIVERY__DEFAULT_CHANNELS='["filesystem"]'      # right
HANSARD_DELIVERY__DEFAULT_CHANNELS=filesystem            # JSONDecodeError
```

The shipped `deploy/compose/docker-compose.yml` had the bare form and has been
fixed. If you are running an older copy, either update it or drop the line
entirely — `("filesystem",)` is already the default.

The same rule covers `HANSARD_ASR__DRIFT_LADDER_SECONDS`,
`HANSARD_RUNTIME__*` tuples and any other list-valued setting. The full list is
in [configuration](configuration.md).

Note that the error names the top-level section, `delivery`, not the field
inside it, so read the whole section's environment rather than only the setting
you last changed.

---

## Speakers are wrong

Everything in this section is governed by `HANSARD_DIARIZATION__*`. The full
table is in [configuration](configuration.md#diarization).

### Everyone is labelled "Speaker 1", "Speaker 2", … and never by name

**Cause 1: there is no roster.** Names come from the active-speaker signal the
browser bot reads out of the Teams client. `hansard transcribe` on a file has no
roster at all, so anonymous labels are the correct and expected output.

**Cause 2: the naming gates rejected the match.** With a roster present,
`RosterSpeakerNamer` requires a cluster's speaking time to be at least
`min_observation_overlap` (0.35) explained by one participant, *and* to lead the
runner-up by 0.15 of that speaking time. When it cannot clear both, it keeps the
anonymous label deliberately: a confidently wrong name is worse than an honest
`Speaker 2`.

**Cause 3: naming is switched off.**

```bash
echo $HANSARD_ATTRIBUTION__STRATEGY   # diarization_only disables naming entirely
```

**Fix.** Set `HANSARD_ATTRIBUTION__STRATEGY=hybrid`, then relax the gate if the
speakers are separated correctly but stay unnamed:

```bash
HANSARD_ATTRIBUTION__MIN_OBSERVATION_OVERLAP=0.20
```

If names then start landing on the wrong person, you have gone too far. Raise it
back above 0.5.

### One person is split across several speakers

**Cause.** `clustering_threshold` is too low: two clusters that were the same
voice did not merge.

**Fix.** Raise it toward `1.0` in steps of 0.01.

```bash
HANSARD_DIARIZATION__CLUSTERING_THRESHOLD=1.00
```

### Two people are merged into one speaker

**Cause.** `clustering_threshold` is too high.

**Fix.** Lower it.

```bash
HANSARD_DIARIZATION__CLUSTERING_THRESHOLD=0.99   # then 0.95, then 0.90
```

`0.99` is calibrated for the TitaNet embedding space and **does not transfer** to
a different `HANSARD_DIARIZATION__EMBEDDING_MODEL`. If you changed the embedding
model, re-derive the threshold with `make bench-meetings` before concluding
anything.

### Too many speakers, most of whom barely say anything

**Cause.** Micro-clusters from crosstalk, laughter, or a single overlapping
syllable. This is not a threshold problem; leave the threshold alone.

**Fix.** Raise the floor that absorbs marginal speakers into their nearest stable
neighbour. It defaults to `10.0` seconds of total speaking time; on a noisy room
go higher:

```bash
HANSARD_DIARIZATION__MINIMUM_SPEAKER_SECONDS=15.0
```

Raise this **before** you touch `MERGE_SIMILARITY`. On the AMI sweep behind the
current defaults, going from 10 s to 20 s barely moved macro DER (29.49 % to
29.62 %), while loosening the similarity made it clearly worse — see
[configuration](configuration.md#minimum_speaker_seconds-and-merge_similarity-the-pair-that-was-retuned).

The floor is skipped entirely when the speaker count is known — a Teams roster,
`--speakers`, or `speaker_count` in the API. If the bot joined the meeting, this
setting is not what you are looking for; pin the count instead.

### One person split across several speakers

**Cause.** Short, spontaneous turns give the embedding model little to work with,
so clustering fragments a person into several clusters. Spontaneous meetings do
this far more than prepared speech.

**Fix.** Cluster consolidation is on by default and merges clusters whose speaker
centroids are too close to be different people. If fragments survive, you can
lower the similarity a person must exceed to be considered the same person:

```bash
HANSARD_DIARIZATION__MERGE_SIMILARITY=0.75   # default 0.77
```

**Do this last, in steps of 0.01, and check who got merged.** The instinct — "I
see too many speakers, so let me merge much more aggressively" — measured
*worse*, not better, and the margin is thin. On a real French meeting with four
speakers, the same floor of 10 s gave four detected speakers at 0.77, three at
0.75, and **two at 0.70**, where cpWER reached 89.82 %. A merged pair of real
speakers is a far worse transcript than one spare cluster.

Raise `MINIMUM_SPEAKER_SECONDS` first. Better still, if the bot joined the
meeting, the participant list already caps the speaker count for you and no
tuning is needed. To turn the stage off entirely:

```bash
HANSARD_DIARIZATION__CLUSTER_CONSOLIDATION=false
```

### Telling it how many people are in the meeting

`--speakers 6` on the command line, `speaker_count` in the API, or a Teams
roster with six participants all pin the number of clusters. This is the single
most effective thing you can do for attribution quality, and it is why the
browser bot reads the participant list: in a real meeting the answer is known,
so nothing has to be inferred from the audio.

---

## The transcript is empty

### Nothing was produced from a live capture

Look at the recorder's own diagnostics first. `TeamsBrowserCapture` stores a
`CaptureDiagnostics` on `last_diagnostics` after every capture, holding the stop
reason, the speaker timeline, which signals were silent, the measured loudness
report, whether it waited in the lobby, how many join attempts it made, and
whether the announcement was posted.

```python
capture = TeamsBrowserCapture(settings=settings)
await capture.capture(request, workspace)

diagnostics = capture.last_diagnostics
print(diagnostics.stop_reason)         # meeting_ended, silence_timeout, alone_timeout, …
print(diagnostics.silence)             # SilenceReport(mean_dbfs, max_dbfs, floor_dbfs)
print(diagnostics.degraded_signals)    # which roster/speaker signals produced nothing
print(diagnostics.waited_in_lobby, diagnostics.join_attempts, diagnostics.announced)
```

A `stop_reason` of `silence_timeout` with `announced=True` means the bot joined,
announced itself, and then heard nothing for the whole
`HANSARD_CAPTURE__SILENCE_TIMEOUT_SECONDS` window. That is an audio-routing
failure, not a transcription failure.

### `CaptureError: the capture contains no audible audio ...`

The recorder measures the finished file with ffmpeg `volumedetect` and refuses to
hand back silence. The full message lists the causes in order of likelihood, and
they are worth taking in that order:

1. **Playwright launched Chromium with its default `--mute-audio`.** The most
   common cause by a distance. Chromium must be launched with that default
   argument suppressed.
2. **The browser is not routed to the PulseAudio null sink.** Confirm the sink
   exists and is the default:
   ```bash
   pactl list short sinks
   pactl info | grep 'Default Sink'
   ```
   The recorder reads `<HANSARD_CAPTURE__PULSE_SINK_NAME>.monitor`, by default
   `hansard_sink.monitor`.
3. **The meeting was never joined, or nobody spoke.** Cross-check
   `diagnostics.stop_reason` and the roster.
4. **The tab was never granted audio permission** for the meeting origin.

### `CaptureError: ffmpeg stopped writing to ... for 20s; the PulseAudio monitor '...' produced no data`

### `CaptureError: ffmpeg exited early with code N; the PulseAudio source '...' is probably gone`

The audio server went away mid-meeting, or the sink was unloaded underneath the
recorder. In a container, this means the entrypoint's PulseAudio process died.
Check the container logs for the `[hansard-entrypoint]` lines.

### `CaptureError: pactl is not installed` / `PulseAudio is not reachable`

The browser bot needs a running PulseAudio server, not only the client tools.
Inside the shipped bot image the entrypoint starts it before the worker. Outside
a container, start it yourself or set `PULSE_SERVER`.

### The file transcribed, but the transcript has almost no words

The voice-activity detector discarded the speech before it reached the
recogniser. This happens with quiet or distant recordings.

```bash
HANSARD_VAD__THRESHOLD=0.35
HANSARD_VAD__MIN_SPEECH_SECONDS=0.15
HANSARD_VAD__SPEECH_PAD_SECONDS=0.25
```

To confirm the diagnosis, disable detection entirely and see whether the words
come back:

```bash
HANSARD_VAD__ENGINE=null hansard transcribe meeting.wav
```

If they do, the VAD was the problem. If the transcript is still empty, the audio
itself is silent — check it with `ffmpeg -i meeting.wav -af volumedetect -f null -`.

---

## The bot never joins the meeting

Everything in this section is tenant configuration, and none of it can be fixed
from Hansard's side. The PowerShell to change each one is in
[Teams setup](teams-setup.md#2-administrator-authorisation-powershell).

| Error | Cause | Fix |
| --- | --- | --- |
| `MeetingJoinRefused: Teams refused the join: anonymous join is disabled by tenant policy (subCode 5723)` | The tenant does not permit anonymous participants, and the notetaker joins anonymously | Enable anonymous join, or give the notetaker its own Microsoft 365 account. [Teams setup §2.2](teams-setup.md#22-allow-anonymous-participants) |
| `MeetingJoinRefused: ... a meeting participant denied the join request from the lobby (subCode 5854)` | Somebody clicked *Deny* | Ask an organiser to admit it, and tell the meeting in advance that it is coming |
| `MeetingAdmissionTimeout: nobody admitted the notetaker from the lobby within 600s` | It sat in the lobby until the deadline | Admit it, raise `HANSARD_CAPTURE__LOBBY_TIMEOUT_SECONDS`, or change the lobby policy so it is admitted automatically |
| `MeetingJoinRefused: tenant policy blocked the notetaker from joining this meeting` | `ExternalBotAccessMode` is blocking it. Since 2026 it defaults to `RequireApprovalWhenDetected` | Set `-ExternalBotAccessMode AllowBots`, preferably on a dedicated policy rather than tenant-wide. [Teams setup §2.1](teams-setup.md#21-allow-external-bots-the-setting-that-most-often-blocks-a-notetaker) |
| `CaptureError: the notetaker was removed from the meeting` | A participant removed it | Working as intended. Anyone in the meeting can stop the recording |

Policy changes take time to propagate. If the PowerShell reports success and the
join still fails, wait and retry before changing anything else.

If the bot joins but the interface is in an unexpected language and the join
buttons are not found, pin the Teams interface language — see
[Teams setup §3](teams-setup.md#3-pinning-the-teams-interface-language).

---

## The meeting ended but the bot stayed in it

The bot leaves as soon as one of these fires, checked once per
`HANSARD_CAPTURE__ROSTER_POLL_SECONDS` (default 1s):

| Signal | Setting | Default |
| --- | --- | --- |
| A `call_end` termination in the Teams signalling traffic | — | immediate |
| The page reports *Meeting ended* / *La réunion est terminée*, or the notetaker was removed | — | immediate |
| Nobody has spoken | `HANSARD_CAPTURE__SILENCE_TIMEOUT_SECONDS` | 600 |
| The notetaker is the only one left in the roster | `HANSARD_CAPTURE__ALONE_TIMEOUT_SECONDS` | 120 |
| The meeting has run too long | `HANSARD_CAPTURE__MAX_DURATION_SECONDS` | 14400 |

The alone timeout arms only once the notetaker has actually seen a roster, so
Hansard opens the participants panel right after joining. If that panel cannot
be opened — a Teams interface language whose *People* button carries a label
Hansard does not know — the log carries:

```
capture.roster_panel_unavailable
```

and the alone timeout stays disarmed. Pin the interface language
([Teams setup §3](teams-setup.md#3-pinning-the-teams-interface-language)); the
silence and duration timeouts still apply.

The state the bot believes it is in is logged on every transition:

```
capture.meeting_state state=in_meeting saw_roster=True
```

If that line stays on `in_meeting` after the meeting is visibly over, Teams is
still reporting an active call to the page. If it reads `unknown`, the page is
showing something Hansard does not recognise. Either way the capture is not
lost: it stops at the silence or duration timeout and transcribes what it has.

Lower `HANSARD_CAPTURE__SILENCE_TIMEOUT_SECONDS` for short test meetings — with
the 600s default a bot that misses the end signal keeps recording silence for
ten minutes.

---

## It is too slow, or runs out of memory

Expected figures on 4 vCPU with no GPU, with the shipped float32 recogniser,
from [benchmarks](benchmarks.md#4-efficiency):

| Profile | RTF | Peak RAM | 60 minutes of audio |
| --- | ---: | ---: | ---: |
| Full pipeline | 0.61 – 0.81 | 3.6 GB | ~44 min |
| Recognition alone | 0.31 – 0.57 | 2.9 GB | ~26 min |

RTF is processing seconds per second of audio; lower is better. Time splits
roughly 55 % recognition, 40 % diarization, 5 % everything else. Both scale with
cores, so an 8-core node roughly halves those figures.

If you are comparing against older figures of "~3× real time and 2.9 GB", those
were the INT8 recogniser, which is no longer the default.

### It is much slower than that

**Check the thread counts first.** `HANSARD_ASR__INTRA_OP_THREADS` defaults to
`0`, meaning ONNX Runtime decides — but a container with a CPU limit will often
see the *host's* core count and oversubscribe badly, which is slower than using
fewer threads.

```bash
HANSARD_ASR__INTRA_OP_THREADS=4     # match the cores you actually have
OMP_NUM_THREADS=4
```

**Then raise the batch size** on a machine with cores to spare:

```bash
HANSARD_ASR__BATCH_SIZE=16
```

**Confirm the GPU is really being used.** `HANSARD_ASR__DEVICE=auto` falls back
to CPU without complaint when ONNX Runtime reports no CUDA provider — which is
what happens when the onnxruntime-gpu wheel does not match the container's CUDA
and cuDNN. Check what the runtime believes:

```bash
python -c "import onnxruntime; print(onnxruntime.get_available_providers())"
```

`CUDAExecutionProvider` must be in that list. The version matrix is documented
at the top of `deploy/docker/Dockerfile.worker-gpu`. Note also that
`HANSARD_DIARIZATION__DEVICE=auto` always resolves to CPU; only the literal
`cuda` selects the GPU there.

### It runs out of memory

In order of effect:

```bash
HANSARD_ASR__QUANTIZATION=int8      # the low-memory profile: 1.4 GB instead of 2.8 GB
HANSARD_ASR__BATCH_SIZE=1           # fewer segments held at once
HANSARD_ASR__INTRA_OP_THREADS=2     # each thread has its own arena
```

`int8` is **not** the default and it is not free: it costs about two points of
word error rate in French and rather less in English, for roughly 1.4 GB of
resident memory. It is also no faster. Take it when the memory is genuinely not
there, and record the choice wherever you report quality —
[benchmarks §5](benchmarks.md#5-choosing-a-quantization-profile) has the full
comparison.

The other lever is the segment ceiling. `HANSARD_AUDIO__MAX_SEGMENT_SECONDS`
defaults to 120, and on real spontaneous meeting audio that is what drives peak
memory: the AMI benchmark reached **7.1 GB** at the default, against 3.6 GB on
the synthetic fixtures. Lowering it to 30–60 seconds cuts memory substantially
and costs word error rate — the exchange rate is measured in
[benchmarks](benchmarks.md#6-engineering-findings-worth-knowing).

If you are running several meetings in parallel on one node, that is the real
cost: each worker holds its own copy of the recogniser, around 2.8 GB at the
float32 default or 1.4 GB with `int8`. Budget per worker process, not per node.

---

## The minutes are empty, or no better than a list of quotes

### The minutes look mechanical

You are getting the extractive writer. That is the designed fallback, not a
failure: with `HANSARD_MINUTES__ENGINE=auto`, Hansard probes the model endpoint
and silently falls back to deterministic extraction when it cannot be reached.
It never returns an empty recap.

Check whether the endpoint is actually up:

```bash
curl -sS "$HANSARD_MINUTES__ENDPOINT/models"
```

That is the same request `auto` makes. A connection error, or a 5xx, sends you
down the extractive path.

### `SummarizationError: model endpoint returned no choices`, `... returned an empty completion`, `model answer contains no JSON object`

The endpoint answered but not usefully. Common causes: a wrong
`HANSARD_MINUTES__MODEL_ID` that the server does not recognise, a context window
smaller than `HANSARD_MINUTES__CONTEXT_TOKENS` claims, or a small model that
cannot hold a JSON schema. Lower `HANSARD_MINUTES__CHUNK_TOKENS` to about `4096`
and set `HANSARD_MINUTES__CONTEXT_TOKENS` to the server's real window.

### You want the deterministic path on purpose

For an air-gapped runner, CI, or a smoke test with no LLM anywhere:

```bash
HANSARD_MINUTES__ENGINE=extractive
```

or `HANSARD_MINUTES__ENABLED=false`, which forces the same writer. Either way no
socket is opened. You still get decisions, action items with owners and
deadlines, open questions and per-topic summaries.

Model choice, prompt structure and how claims are grounded against the
transcript are in [minutes](minutes.md).

---

## Delivery fails

### `DeliveryError: no delivery route for address '...' on channel teams_chat; available address schemes: ...`

The address does not carry a scheme the Teams channel understands. It routes by
prefix: `chat:`, `channel:`, `bot:`, or an `https:` Workflows URL. The `chat:`,
`channel:` and `bot:` routes exist only when
`HANSARD_DELIVERY__GRAPH__TENANT_ID`, `…__CLIENT_ID` and `…__CLIENT_SECRET` are
all set — without them the publisher is built with the webhook route alone, and
the error is what you see above.

### Teams messages are never posted, and Graph returns 401 or 403

Read this before spending time on permissions: **an app-only Microsoft Graph
token cannot post an ordinary Teams chat message.** This is a documented
Microsoft restriction, not a bug in the app registration, and no combination of
application permissions lifts it.

There are two paths that do work, and both are written up with the exact steps in
[delivery](delivery.md#3-teams-channel--what-actually-works):

- a **Power Automate Workflows webhook**, which needs no app registration at all
  and is the shortest route to a message in a channel;
- the **Bot Framework connector**, which posts as a registered bot.

### Email is never delivered

Check the envelope sender first. `HANSARD_DELIVERY__SMTP__SENDER` defaults to
`hansard@localhost`, which most relays reject outright. Set it to an address your
relay will accept from this host.

Then check the TLS pair. `USE_TLS` is implicit TLS from the first byte, for port
465. `START_TLS` is an upgrade on an existing connection, for port 587. Setting
both, or neither, against the wrong port is the usual cause of a hang or a
handshake error.

```bash
HANSARD_DELIVERY__SMTP__HOST=smtp.internal
HANSARD_DELIVERY__SMTP__PORT=587
HANSARD_DELIVERY__SMTP__START_TLS=true
HANSARD_DELIVERY__SMTP__USE_TLS=false
HANSARD_DELIVERY__SMTP__SENDER=hansard@example.org
```

One failing channel never blocks another: the dispatcher fans targets out
concurrently, applies a per-target timeout, and records each failure separately.

---

## Accented French characters look wrong

### The transcript shows `Aurélie` or `AurÃ©lie`

**Cause.** This is a reading problem, not a transcription problem. Every renderer
declares UTF-8 — `text/markdown; charset=utf-8`, `text/html; charset=utf-8`,
`text/plain; charset=utf-8` — and the CLI writes bytes encoded as UTF-8. What you
are seeing is a consumer that assumed something else: a terminal in a non-UTF-8
locale, a Windows editor defaulting to CP-1252, or a spreadsheet import that was
not told the encoding.

**Fix.**

```bash
file -i artifacts/meeting/transcript.md    # expect charset=utf-8
locale                                     # expect a UTF-8 LANG/LC_ALL
export LANG=fr_FR.UTF-8                    # or en_GB.UTF-8; the point is UTF-8
```

For email, check that your relay is not transcoding the body. For a webhook
consumer, check that it reads the declared charset rather than assuming Latin-1.

### The accents are genuinely gone from the text

If the characters are absent rather than mangled, something downstream stripped
them. Hansard does not. **The French normalizer deliberately keeps diacritics**,
and this is a decision with consequences worth understanding.

Stripping accents is common in speech-recognition evaluation because it makes
word error rates look better: *reglement* and *règlement* stop counting as an
error. Hansard refuses to do that, because in a meeting record the difference
between *ou* and *où*, or *a* and *à*, is the difference between two sentences.
It also reports character error rate alongside word error rate specifically to
catch a system that is silently dropping accents — CER is the metric that makes
that visible. The reasoning is in [metrics §2.3](metrics.md#23-french--the-part-that-decides-whether-your-numbers-are-real).

`remove_diacritics` exists in the normalizer module and is reachable through a
`strip_accents` flag, for comparing against a published number produced under
those rules. It is off by default and should stay off for anything you intend to
read.

---

## A bilingual meeting comes out wrong

### Half the meeting is transcribed as gibberish

**Cause.** A single language was pinned. `HANSARD_ASR__LANGUAGE=fr` or
`--language fr` forces French decoding onto *every* segment, so the English
speech is decoded as French-sounding nonsense — and the reverse. The symptom is
distinctive: one language is clean and the other is word-salad that almost
rhymes with what was said.

**Fix.** Unset it, or set it to `mixed`. Both leave the recogniser free to switch,
which is what Parakeet does natively.

```bash
hansard transcribe meeting.m4a                    # let it switch
hansard transcribe meeting.m4a --language mixed   # the same thing, said out loud
```

### The decisions and actions from one language are missing

**Cause.** The minutes were composed against one language. Check the `language`
field of the minutes: if it says `fr` or `en` on a meeting that was genuinely
bilingual, every sentence was matched against that language's cue phrases and the
other language's decisions, actions and deadlines were never looked for.

Two settings cause this. `HANSARD_MINUTES__LANGUAGE` forces the minutes language
outright. `HANSARD_ASR__IDENTIFY_LANGUAGE=false` turns off per-utterance labelling,
after which the whole meeting falls back to one tag.

**Fix.** Unset both. Then confirm from the JSON export:

```bash
python -c "import json,sys; t=json.load(open(sys.argv[1]))['transcript']; \
print(t['language'], t['languages'], t['code_switched'])" \
  artifacts/meeting/transcript.json
```

On a bilingual meeting expect `mixed`, both tags, and `True`. The tags are ordered
most-spoken first, so which comes first tells you which language dominated.

### The meeting is bilingual but `code_switched` is `false`

**Cause.** The second language did not clear the minority threshold: a language
must carry at least 10 % of the transcribed words or at least 20 seconds of speech
before the meeting is marked `mixed`. A meeting that is 95 % French with one short
English aside is French with a borrowing, and calling it bilingual would be
misleading.

**This does not mean the aside was mishandled.** The threshold governs how the
meeting is *labelled*, not how it is *analysed* — extraction always uses each
sentence's own language, so a decision taken in that English aside is still
extracted with English cues. Check the per-utterance `language` fields in the JSON
export before concluding anything was lost.

### Short utterances have the wrong language

**Cause.** "Ok.", "Mm.", "Meridian 42" — some utterances carry no evidence in
either language. They are not guessed at from nothing: they inherit from the
nearest labelled utterance by the same speaker, looking forward before back. At a
language switch this is right most of the time and wrong some of the time.

**Impact.** Usually none that matters: these utterances carry no extractable
content, and `language_accuracy` weights by word count, so a one-word turn costs
almost nothing. If a *long* utterance is mislabelled, that is a real defect worth
reporting — include the exact text, per [filing a good bug report](#filing-a-good-bug-report).

Background and known limits: [multilingual](multilingual.md).

---

## Configuration errors

| Error | Meaning |
| --- | --- |
| `ConfigurationError: unknown ASR engine 'ensemble', available: ('null', 'parakeet', 'qwen3', 'whisper')` | The name is in the type but not registered |
| `RecognitionError: faster-whisper is not installed` | `HANSARD_ASR__ENGINE=whisper` without the extra; `pip install 'hansard[asr-whisper]'` or use `parakeet` |
| `ConfigurationError: storage backend 's3' requires HANSARD_STORAGE__BUCKET` | `HANSARD_STORAGE__BACKEND=s3` with no bucket set |
| `ConfigurationError: the s3 artifact store needs boto3` | `pip install 'hansard[storage-s3]'` |
| `ArtifactKeyError: artifact key ...` | An artefact key that is absolute, padded, or contains `..`, `\`, `:` or a control character. Keys are relative paths under the store root |
| `ConfigurationError: unknown diarization engine ...` | Valid names are `sherpa`, `sortformer`, `pyannote`, `null`. The first three all resolve to the same sherpa implementation |
| `ConfigurationError: unknown output format 'pdf', available: ('html', 'json', 'markdown', 'srt', 'text', 'vtt')` | A `--format` value that no renderer claims |
| `ValidationError: ... Hansard never emits telemetry; this switch exists only to document that` | `HANSARD_RUNTIME__TELEMETRY_ENABLED=true`. There is no telemetry to enable |

A setting that appears to be ignored may be one of the fields that is declared
but not yet read by any code path. They are listed together in
[configuration](configuration.md#not-yet-wired-up).

---

## Filing a good bug report

Include these four things. They are usually enough to diagnose a problem without
a second round trip.

**1. The `doctor` output.**

```bash
hansard doctor
```

**2. Versions.**

```bash
hansard version
python3 --version
ffmpeg -version | head -1
pip show hansard onnxruntime sherpa-onnx onnx-asr 2>/dev/null | grep -E 'Name|Version'
python -c "import onnxruntime; print(onnxruntime.get_available_providers())"
```

**3. Your effective configuration, with secrets redacted for you.**

```bash
python -c "from hansard.config import Settings; import json; \
  print(json.dumps(Settings().model_dump(mode='json'), indent=2, default=str))"
```

Every `SecretStr` field renders as `**********`, so this output is safe to paste.
Check it anyway before you do.

**4. The full traceback**, not the last line. The error classes carry the
diagnosis in the message — the model path that was missing, the PulseAudio source
that produced nothing, the Teams subCode.

### Do not paste meeting content into a public issue

This matters more here than in most projects. A transcript is personal data from
the first word, it usually belongs to people who are not you, and a public issue
tracker is a permanent, indexed, world-readable archive.

- **No transcript text**, in any language, not even one line.
- **No participant names, email addresses, chat ids or tenant ids.** A Teams
  `19:...@thread.v2` address identifies a real conversation inside a real
  organisation.
- **No audio files**, and no meeting join URLs.
- **No `.env` file**, even one you believe is redacted.

Reproduce the problem on a recording you own and are willing to publish. If the
failure only happens on real meeting audio, describe its *shape* — duration,
number of speakers, language, whether it was mixed or far-field, roughly how
quiet — and paste the metrics rather than the words:

```bash
cat artifacts/meeting/metrics.json
```

That file holds durations, timings, speaker count and word count. No content.

If the issue genuinely cannot be described without the content, say so in the
issue and ask the maintainers for a private channel rather than posting it.

---

## Related reading

- [Installation](installation.md) — prerequisites, models, `hansard doctor`
- [Configuration](configuration.md) — every setting and what changing it does
- [Teams setup](teams-setup.md) — tenant policy, lobby, consent
- [Delivery](delivery.md) — channels, addresses, Graph limitations
- [Minutes](minutes.md) — running a local model
- [Multilingual](multilingual.md) — meetings held in French and English at once
- [Deployment](deployment.md) — Docker Compose and Kubernetes
- [Architecture](architecture.md) — why the pipeline is shaped this way
