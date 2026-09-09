# Your first meeting

A runbook for the person testing Hansard for the first time. Thirty minutes,
one real Teams meeting, and an honest read of what came out.

If you are the Teams administrator setting the tenant up, read
[teams-setup.md](teams-setup.md) first — none of this works until an admin has
allowed external participants. This page assumes that is done.

---

## Before the day

### 1. Get the tenant to allow the notetaker

The single most common reason a notetaker never appears is that the tenant
forbids it. An administrator must run the PowerShell in
[teams-setup.md §2](teams-setup.md#2-administrator-authorisation-powershell) and
wait for propagation — **up to 24 hours**, so do not leave this to the morning
of the test.

### 2. Pick the right machine, because the bot needs Linux

The notetaker drives a headless Chromium and captures its audio through a
**PulseAudio** null sink with `pactl` and `ffmpeg -f pulse`. That is Linux, with
no fallback. Three honest options:

| You have | Do this |
| --- | --- |
| A Linux machine or VM | Install natively — [§3](#3-install-no-make-required) |
| Windows or macOS | Run the bot in Docker — [§3b](#3b-windows-or-macos-run-it-in-a-container) |
| Windows with WSL2 | Native install inside WSL2 works, but you must start PulseAudio yourself; Docker is less fiddly |

Transcribing an existing recording (`hansard transcribe`) works anywhere Python
and ffmpeg do. It is only *joining a meeting* that needs Linux.

### 3. Install, no `make` required

The Makefile is a convenience; every target is one or two commands. This is all
it does:

```bash
git clone https://github.com/Haswell119/teams-retranscription
cd teams-retranscription

# Virtualenv and dependencies. uv is the fast path; plain pip works too.
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[api,asr-onnx,diarization,delivery,metrics,observability]"
uv pip install --python .venv/bin/python -e ".[capture]"
.venv/bin/python -m playwright install --with-deps chromium
```

Without `uv`: `python3.11 -m venv .venv` then `.venv/bin/pip install -e ".[...]"`
with the same extras. Slower, identical result.

Model weights, ~3.2 GB, checksum-verified, network needed **this once only**:

```bash
sh deploy/docker/fetch-models.sh deploy/docker/models.manifest deploy/docker/models.NOTICE "$PWD/models"
export HANSARD_RUNTIME__MODELS_DIR="$PWD/models"
```

If you would rather not run a shell script, Docker does the same job — see the
`--target export` build in [§3b](#3b-windows-or-macos-run-it-in-a-container).

You also need **ffmpeg**, **pulseaudio** and **pulseaudio-utils** from your
distribution: `apt install ffmpeg pulseaudio pulseaudio-utils` on Debian and
Ubuntu.

After the model fetch the transcription path never touches the network again. A
CI job runs a transcription and fails the build if a socket opens.

### 3b. Windows or macOS: run it in a container

The bot image packages Xvfb, Chromium, PulseAudio and ffmpeg, so nothing goes on
the host. Build it with diarization included — the default build leaves it out
because in Kubernetes a separate worker does the transcription:

```bash
docker build -f src/hansard/adapters/capture/docker/Dockerfile --build-arg EXTRAS=capture,asr-onnx,diarization,delivery -t hansard-bot:local .
```

Fetch the models once. A build target exists that only downloads, verifies and
hands you the directory — no shell script, no `make`:

```bash
docker build -f deploy/docker/Dockerfile.models --target export --output type=local,dest=./models .
```

Then join the meeting from inside the container:

```bash
docker run --rm -v "$PWD/models:/models:ro" -v "$PWD/artifacts:/artifacts" -e HANSARD_RUNTIME__MODELS_DIR=/models -e HANSARD_CAPTURE__DISPLAY_NAME="Notetaker - test IT" --shm-size=2g hansard-bot:local hansard join "<paste the join URL>" --title "Test Hansard" --output /artifacts
```

`--shm-size=2g` is not optional: Chromium crashes on Docker's default 64 MB.

#### The same thing in PowerShell

Docker Desktop with the WSL2 backend, and `${PWD}` rather than `$PWD` — the
brace matters, because the `:` that follows it would otherwise be read as part
of the variable name. Backtick is PowerShell's line continuation, so these are
written on one line each to avoid the question entirely.

```powershell
docker build -f src/hansard/adapters/capture/docker/Dockerfile --build-arg EXTRAS=capture,asr-onnx,diarization,delivery -t hansard-bot:local .

docker build -f deploy/docker/Dockerfile.models --target export --output type=local,dest=./models .

docker run --rm -v "${PWD}/models:/models:ro" -v "${PWD}/artifacts:/artifacts" -e HANSARD_RUNTIME__MODELS_DIR=/models -e HANSARD_CAPTURE__DISPLAY_NAME="Notetaker - test IT" --shm-size=2g hansard-bot:local hansard join "<paste the join URL>" --title "Test Hansard" --output /artifacts
```

Create `artifacts` before the first run — Docker would otherwise create it as a
directory owned by root:

```powershell
New-Item -ItemType Directory -Force -Path .\artifacts | Out-Null
```

To try a recording first, mount it and swap the command:

```powershell
docker run --rm -v "${PWD}/models:/models:ro" -v "${PWD}:/data" -e HANSARD_RUNTIME__MODELS_DIR=/models hansard-bot:local hansard transcribe /data/some-recording.wav --output /data/artifacts
```

Two PowerShell habits worth knowing here:

- **Setting an environment variable** is `$env:HANSARD_CAPTURE__DISPLAY_NAME = "Notetaker - test IT"`,
  not `export`. Inside `docker run` use `-e` as above and the question does not
  arise.
- **A native Windows install can transcribe but cannot join.** If you want
  `hansard transcribe` on the host, install Python 3.11 and ffmpeg, then use
  `.venv\Scripts\hansard.exe` where this guide writes `.venv/bin/hansard`.
  Joining a meeting still needs the container, because PulseAudio does not exist
  on Windows.

### 4. Check the machine can actually do it

```bash
.venv/bin/hansard doctor          # or: docker run --rm ... hansard-bot:local hansard doctor
```

It verifies ffmpeg, the model bundle, the ONNX providers and the workspace. Fix
anything it reports before booking a meeting.

### 5. Prove the pipeline on a recording first

Do **not** let a live meeting be your first test. Take any WAV or MP4 of people
talking and run it through the file path:

```bash
.venv/bin/hansard transcribe ~/some-recording.wav --output ./artifacts
```

In a container, mount the recording and swap `join` for `transcribe`:
`docker run --rm -v "$PWD/models:/models:ro" -v "$PWD:/data" -e HANSARD_RUNTIME__MODELS_DIR=/models hansard-bot:local hansard transcribe /data/some-recording.wav --output /data/artifacts`

You get a transcript, speaker labels and minutes in `./artifacts`. If this works,
the transcription half is fine and anything that fails later is capture.

---

## The meeting itself

### 6. Name the notetaker something your colleagues will recognise

It appears in the participant list. `Hansard Notetaker` is the default and it
looks like a stranger.

```bash
export HANSARD_CAPTURE__DISPLAY_NAME="Notetaker - test IT"
```

### 7. Tell the room, out loud

Hansard posts a notice in the meeting chat on join and sits visibly in the
roster, but **Teams does not show its own recording banner** for an external
notetaker — Teams is not doing the recording. A chat message is easy to miss.
The organiser should say it at the start and put it in the invitation.

The notetaker has no camera and cannot acquire one — it is removed at the browser level, not
just toggled off — so it shows up in the roster as a camera-off participant with the name you
gave it.
[teams-setup.md §5 and §6](teams-setup.md#5-telling-participants-consent-and-notification)
cover consent and the GDPR position properly. For a test with colleagues who
know what is happening, saying it out loud is enough.

### 8. Join

Copy the *Join Microsoft Teams Meeting* link and:

```bash
.venv/bin/hansard join "<paste the join URL>" --title "Test Hansard" --output ./artifacts
```

In a container it is the same command inside the `docker run` from
[§3b](#3b-windows-or-macos-run-it-in-a-container).

Both link shapes work — the classic `meetup-join` one and the newer
`teams.microsoft.com/meet/<id>?p=<passcode>`.

The notetaker takes up to a minute to appear. **Somebody already in the meeting
has to admit it from the lobby** unless the organiser has set the lobby to let
it in. If nobody admits it, it gives up after ten minutes.

### 9. Run a meeting worth measuring

Twenty minutes is plenty. What makes the test informative:

- **Let people interrupt each other.** Overlapping speech is where Hansard is
  weakest and where you most need to know what it does. A polite meeting where
  everyone waits their turn will flatter it.
- **Mix French and English if that is how you actually work.** One model handles
  both in a single pass; there is nothing to configure.
- **Have four or so people.** Everything here was measured on four-person
  meetings.

Hansard leaves on its own when the meeting ends, when it is removed, when it is
the last participant left (two minutes), or after ten minutes of silence.

---

## Reading what came out

Everything lands in `./artifacts`: transcript in Markdown, HTML, JSON and
subtitles, plus minutes and an RTTM speaker timeline.

**Judge it on the right things.** Two separate questions:

| Question | Where to look | What to expect |
| --- | --- | --- |
| Are the words right? | the transcript text | Good. 21 % word error on English meetings, 43 % on casual French, and French meeting speech is genuinely hard |
| Is the right person credited? | the speaker labels | Weaker, and worse the more people talk over each other |

The honest numbers are in [benchmarks.md](benchmarks.md) and the reasoning
behind every one of them, including what failed, is in
[quality-research.md](quality-research.md). Nothing there is hidden and nothing
is rounded in our favour.

**What will annoy you, in advance:**

- **Speaker over-detection.** Four people can come back as five or six clusters,
  especially in a lively meeting. The participant list Hansard reads from the
  meeting limits this, which is why it does better in a real Teams meeting than
  the "told nothing" numbers in the benchmarks suggest.
- **Words disappearing under crosstalk.** When two people talk at once, one of
  them is lost. This is not a bug that a setting fixes: a single-stream
  recogniser cannot emit two voices. It is the largest open problem in the
  project and it is documented as such.
- **Filler words and false starts** appear in the transcript because they were
  said. That is a transcription, not a summary — the minutes are the summary.

---

## When it goes wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| Notetaker never appears | tenant forbids external participants | [teams-setup.md §2.1](teams-setup.md#21-allow-external-bots-the-setting-that-most-often-blocks-a-notetaker); allow up to 24 h |
| Stuck in the lobby | nobody admitted it | admit it, or change the lobby policy |
| Joins, transcript is empty | browser audio not routed into the capture sink | check the logs for `capture.audio_silent`; [troubleshooting.md](troubleshooting.md) |
| Leaves after ten minutes | genuine silence, or dead audio | same as above — a silent capture and a silent meeting look identical from outside |
| Wrong speaker names | roster panel not readable | check the logs for `capture.roster_panel_unavailable` |

[troubleshooting.md](troubleshooting.md) has the full list. The logs are
structured JSON by default; `HANSARD_RUNTIME__LOG_FORMAT=console` makes them
readable while you are watching.

---

## Tell us what you found

The one test nobody has run is **Hansard and Teams on the same meeting**. If you
have the Teams transcript for the meeting you just recorded, that comparison is
worth more than every benchmark in this repository, because it is the only one
measured on your audio, your accents and your vocabulary:

```bash
.venv/bin/hansard compare --help
```

The protocol is in [metrics.md](metrics.md#741-running-the-head-to-head-against-teams).
