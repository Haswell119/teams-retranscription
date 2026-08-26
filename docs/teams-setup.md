# Microsoft Teams setup for the Hansard notetaker

This page explains how a Microsoft 365 administrator authorises the Hansard notetaker in their own
tenant, how a meeting organiser invites it, what participants are told, and what to do when a join
fails. It is written for administrators and meeting organisers; no Hansard internals are required.

Hansard is designed to be **admin-authorised**. It contains no evasion or stealth technique, it does
not impersonate a person, and it will not attempt to bypass a policy that says "no bots". If your
tenant does not allow it in, the join fails with a clear message and nothing is recorded.

---

## 1. How the notetaker joins

The notetaker is a headless-browser bot. It runs a real Chromium under an X virtual framebuffer,
opens the **Teams web client**, and joins the meeting like any other web participant:

- it joins **muted, with the camera off**, and it never speaks or shares content;
- it captures the single mixed audio stream that the Teams web client receives, through a private
  PulseAudio null sink, and writes a 16 kHz mono WAV file on your own infrastructure;
- speaker names come from the meeting **metadata** (the signalling roster, the dominant-speaker
  channel, RTP contributing sources, and, as a last resort, the participant list in the page). Teams
  does not expose per-participant audio to any web client, so who-said-what is reconstructed from
  those signals and from local diarisation.

The participant list does one more thing worth knowing about, because it is the single biggest
quality difference between a meeting the bot joined and a recording dropped on it afterwards: it
caps how many distinct speakers the transcript can contain. The bot excludes itself from that
count, and the cap is an **upper bound**, never a target — it can bring an over-count back down,
but it will never split one person in two to reach the number of people in the room. Meetings where
several invitees never say a word are therefore handled correctly.

Everything after the browser — speech recognition, diarisation, minutes — runs locally. No audio and
no text leave your organisation, unless you deliberately enable the Microsoft Graph fallback
described in section 8.

---

## 2. Administrator authorisation (PowerShell)

You need the **Microsoft Teams PowerShell module** and a Teams Administrator (or Global
Administrator) role.

> If your Teams admin center is displayed in French, the labels differ but the underlying settings
> are the ones named below. Search for the **English identifiers** (`ExternalBotAccessMode`,
> `AllowAnonymousUsersToJoinMeeting`, `AutoAdmittedUsers`) — they are locale-independent and appear
> as-is in PowerShell and in the documentation.

```powershell
Install-Module MicrosoftTeams -Scope CurrentUser
Connect-MicrosoftTeams

# 1. Inspect what applies today (do this before changing anything).
Get-CsTeamsMeetingPolicy -Identity Global |
  Select-Object Identity, ExternalBotAccessMode, AllowAnonymousUsersToJoinMeeting, AutoAdmittedUsers
Get-CsTeamsMeetingConfiguration | Select-Object DisableAnonymousJoin
```

### 2.1 Allow external bots (the setting that most often blocks a notetaker)

Since 2026, `ExternalBotAccessMode` defaults to **`RequireApprovalWhenDetected`**: when Teams detects
a bot-like participant it holds it in the lobby until a human approves it, every single meeting.
That is a perfectly workable mode — someone simply has to click *Admit*. If you want the notetaker to
join unattended, set the policy to `AllowBots`.

```powershell
# Option A - a dedicated policy for the teams that use the notetaker (recommended).
New-CsTeamsMeetingPolicy -Identity "Hansard-Notetaker" `
  -ExternalBotAccessMode AllowBots `
  -AllowAnonymousUsersToJoinMeeting $true `
  -AutoAdmittedUsers EveryoneInCompanyExcludingGuests
Grant-CsTeamsMeetingPolicy -Identity organiser@contoso.com -PolicyName "Hansard-Notetaker"

# Option B - tenant-wide.
Set-CsTeamsMeetingPolicy -Identity Global -ExternalBotAccessMode AllowBots
```

Leaving it at `RequireApprovalWhenDetected` is fine and arguably better practice: the notetaker then
waits in the lobby and an organiser admits it explicitly, which doubles as a consent gesture. Hansard
waits for up to `lobby_timeout_seconds` (default 600 s) before giving up.

### 2.2 Allow anonymous participants

The notetaker joins anonymously (it has no Microsoft 365 account) unless you give it one. Anonymous
join must be enabled at both levels:

```powershell
Set-CsTeamsMeetingConfiguration -DisableAnonymousJoin $false          # tenant-wide switch
Set-CsTeamsMeetingPolicy -Identity Global -AllowAnonymousUsersToJoinMeeting $true
```

If anonymous join is disabled, Teams ends the call with **subCode 5723** and Hansard reports
*"anonymous join is disabled by tenant policy"*. There is no workaround other than enabling it or
giving the notetaker a licensed account and signing the browser profile in.

### 2.3 Lobby behaviour

`AutoAdmittedUsers` decides who waits in the lobby:

| Value | Effect on the notetaker |
| --- | --- |
| `Everyone` | joins directly (also lets any external person in — consider the wider impact) |
| `EveryoneInCompany` / `EveryoneInCompanyExcludingGuests` | anonymous notetaker **waits in the lobby** |
| `OrganizerOnly` / `InvitedUsers` | waits in the lobby, an organiser must admit it |

An organiser can also change this per meeting in *Meeting options → Who can bypass the lobby*.

### 2.4 Propagation

Policy changes are not instant. Allow **a few hours** (Microsoft documents up to 24 hours) before
concluding that a change did not work, and re-check with `Get-CsTeamsMeetingPolicy`.

---

## 3. Pinning the Teams interface language

The notetaker recognises pre-join and in-meeting states from `data-tid` and ARIA attributes wherever
possible, which are locale-independent. A few states (lobby, denial, removal, meeting ended) can only
be read from visible text, and Hansard ships **English and French** wordings for all of them, matched
case-insensitively and with typographic apostrophes and non-breaking spaces normalised.

Because Teams renders in the viewer's locale, Hansard forces the browser locale so that the UI is
predictable:

```bash
export HANSARD_CAPTURE__UI_LOCALE=en-US   # default; sets Chromium --lang and the Playwright locale
export HANSARD_CAPTURE__UI_LOCALE=fr-FR   # French Teams UI - fully supported
```

Trade-off: `en-US` is the language the selectors were written and tested against first, so it is the
most stable choice, and it does **not** affect the language of the meeting, of the transcript, or of
the minutes. Set `fr-FR` if you prefer the notetaker's own browser session to be French — for
instance because screenshots of a failed join will be read by French-speaking operators. Both are
covered by the test suite.

---

## 4. Inviting the notetaker to a meeting

1. Copy the meeting join link (*Join Microsoft Teams Meeting*). Both link shapes work:
   - `https://teams.microsoft.com/l/meetup-join/19%3ameeting_...` (classic)
   - `https://teams.microsoft.com/meet/<id>?p=<passcode>` and `https://teams.live.com/meet/...`
2. Hand the link to Hansard (API, CLI or scheduler). Hansard rewrites the launcher URL so that no
   "open the Teams app?" dialog appears, then joins from the browser.
3. The notetaker appears in the participant list under the configured display name — by default
   **"Hansard Notetaker"**. Give it a name your organisation recognises:

```bash
export HANSARD_CAPTURE__DISPLAY_NAME="Notetaker - Direction juridique"
```

4. It leaves automatically when the meeting ends, when it is removed, when it is the only
   participant left (`alone_timeout_seconds`, default 120 s), after `silence_timeout_seconds`
   (default 600 s) without any speech, or at `max_duration_seconds` (default 4 h).

Relevant settings (environment variables use the `HANSARD_CAPTURE__` prefix):

| Setting | Default | Purpose |
| --- | --- | --- |
| `engine` | `browser` | `browser`, `file` (transcribe an existing recording) or `null` |
| `display_name` | `Hansard Notetaker` | name shown in the participant list |
| `announce_recording` | `true` | post the notice in the meeting chat on join |
| `announcement_text` | English default | your own wording; overrides the built-in defaults |
| `join_timeout_seconds` | `300` | budget for launcher + pre-join |
| `lobby_timeout_seconds` | `600` | how long it waits to be admitted |
| `silence_timeout_seconds` | `600` | leave after prolonged silence |
| `alone_timeout_seconds` | `120` | leave when nobody else is left |
| `max_duration_seconds` | `14400` | hard stop |
| `pulse_sink_name` | `hansard_sink` | PulseAudio null sink used for capture |

---

## 5. Telling participants (consent and notification)

Teams does **not** show its own "recording started" banner for an external notetaker, because Teams
is not doing the recording. Announcing is therefore your responsibility, and Hansard makes it the
default behaviour:

- **Visible presence.** The notetaker is a named participant in the roster for the whole meeting.
- **Chat notice.** On join, Hansard posts the configured announcement into the meeting chat. The
  built-in defaults follow the meeting language (`MeetingRequest.language`, otherwise the pinned UI
  locale):
  - English: *"This meeting is being transcribed locally by Hansard. No audio or text leaves this
    organisation."*
  - French: *« Cette réunion est transcrite localement par Hansard. Aucun enregistrement audio ni
    aucun texte ne quitte cette organisation. »*
- **Your own wording.** Set `announcement_text` to replace both defaults, for example to add a link
  to your privacy notice and a retention period.
- **Say it out loud too.** A chat message is easy to miss. Best practice is for the organiser to
  state at the start of the meeting that it is being transcribed, and to note it in the invitation.

Setting `announce_recording=false` is available for meetings where the notice is delivered another
way (invitation text, standing policy, spoken statement). Turning it off does not make an
undisclosed recording lawful — see the next section.

---

## 6. Legal considerations

*This is practical guidance, not legal advice. Confirm with your own counsel or DPO.*

### GDPR / UK GDPR (EU, EEA, UK)

- **Recordings and transcripts of identified speakers are personal data.** You need a lawful basis
  under Article 6. In an employment context, the usual candidates are **legitimate interests**
  (Art. 6(1)(f), with a documented balancing test) or **legal obligation / public task** for bodies
  that must minute their meetings. **Consent** (Art. 6(1)(a)) is difficult to rely on between
  employer and employee, because it is rarely freely given; it is more appropriate for external
  participants who can genuinely decline.
- **Transparency** (Art. 12–14): participants must be told before or at the start — who is
  recording, why, on what basis, how long the data is kept, and how to exercise their rights. The
  chat announcement plus the meeting invitation normally covers this.
- **Data minimisation and retention** (Art. 5): keep the audio no longer than you need. Hansard's
  storage settings include a retention period; set it deliberately.
- **Special categories** (Art. 9): meetings that discuss health, trade-union activity, or similar
  need a stronger basis and usually a **DPIA**. A DPIA is also expected for systematic monitoring of
  employees.
- **Processors and transfers**: because Hansard runs entirely on your infrastructure, there is no
  new processor and no international transfer to assess — that is the point of the sovereign design.
  Enabling the Graph fallback (section 8) changes that: Microsoft then performs the speech
  recognition as your processor.
- **Works councils / staff representatives**: in France, Germany, the Netherlands and elsewhere,
  systematic recording of meetings involving employees may require prior consultation (in France,
  information-consultation of the CSE, plus an entry in the *registre des traitements*).

### Recording-consent laws outside the GDPR

- **All-party (two-party) consent** jurisdictions require every participant to consent: in the
  United States, California, Illinois, Florida, Pennsylvania, Washington, Massachusetts, Michigan,
  Connecticut, Maryland, Montana, New Hampshire, Delaware, Oregon (in part) and Nevada (in part).
  If any participant may be in one of these, get an explicit, recorded agreement — an announcement
  plus the opportunity to object before the substantive discussion is the common practice.
- **One-party consent** covers US federal law and most other states, and Canada
  (Criminal Code s. 184(2)).
- **France**: recording a private conversation without the participants' knowledge can engage
  Article 226-1 of the Code pénal. An announced, business-purpose transcription with a documented
  lawful basis is the safe pattern; a covert one is not.
- Some sectors have their own rules (financial services record-keeping, healthcare confidentiality,
  legal privilege). Meetings covered by legal professional privilege are usually best left
  un-transcribed.

### Practical checklist

1. Name the notetaker after your organisation, not after a person.
2. Keep `announce_recording` on, and say it out loud as well.
3. Publish a short privacy notice and link it from `announcement_text`.
4. Set a retention period and enforce it.
5. Give participants a way to object, and a way to ask for a recording to be deleted.
6. Do not transcribe meetings whose subject makes it inappropriate.

---

## 7. Failure states and troubleshooting

Every failure below is reported by Hansard with a specific message; nothing fails silently.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `MeetingJoinRefused: anonymous join is disabled by tenant policy (subCode 5723)` | Teams ended the call because anonymous participants are not allowed | section 2.2, or give the notetaker an account |
| `MeetingJoinRefused: ... denied the join request from the lobby (subCode 5854)` | a participant clicked *Deny* | ask an organiser to admit it; tell the meeting it is coming |
| `MeetingJoinRefused: a meeting participant denied the notetaker's request to join` | same, detected from the page text | as above |
| `MeetingAdmissionTimeout: nobody admitted the notetaker from the lobby within 600s` | it sat in the lobby | admit it, raise `lobby_timeout_seconds`, or set `ExternalBotAccessMode AllowBots` / `AutoAdmittedUsers Everyone` |
| `CaptureError: the meeting ended before the notetaker was admitted` (subCode 5000) | the meeting finished first | none needed |
| `CaptureError: the notetaker was removed from the meeting` (subCode 5300) | someone removed it | expected behaviour: respect the decision |
| `MeetingJoinRefused: tenant policy blocked the notetaker` | an organisation policy page was shown | check meeting policy and sensitivity labels on the meeting |
| `CaptureError: Teams kept redirecting to the light experience` | Teams pushed the browser to its reduced web experience | usually transient; Hansard already retries with a fresh browser, `HANSARD_CAPTURE__JOIN_ATTEMPTS` times. Persisting: check the Chromium version in the image |
| `CaptureError: ... no audible audio` | an hour of silence was recorded | the container's PulseAudio null sink is not the default output, or Chromium was started with `--mute-audio`. Use the shipped Dockerfile/entrypoint |
| `CaptureError: PulseAudio is not reachable` | no sound server in the container | start `pulseaudio` before the worker; the shipped entrypoint does this |
| `CaptureError: pactl is not installed` | image missing `pulseaudio-utils` | use the shipped image |
| `CaptureError: ffmpeg stopped writing ...` | the monitor source disappeared mid-capture | check that nothing else unloaded the null sink. The recorder restarts into a fresh segment first and only surfaces this once `HANSARD_CAPTURE__RECORDER_RESTART_ATTEMPTS` is spent |
| Transcript has speakers but no names | the roster signal never arrived (Teams changed the signalling format) | the capture still succeeds; diarisation labels speakers generically. Check the health counters in the capture diagnostics |
| Names attached to the wrong speaker near turn changes | metadata trails the audio | Hansard marks close calls as *contested* rather than guessing; tune `metadata_lag_seconds` (measured 1.25–2.0 s in the wild) |

### Health signals

Each capture records per-signal health counters (signalling frames decoded, roster updates,
contributing-source transitions, dominant-speaker messages, DOM transitions, instrumentation
errors). A signal with **zero transitions over a long meeting** means Teams changed something and
that signal needs re-checking; the remaining signals degrade gracefully in the order
contributing-sources → dominant-speaker → participant list.

---

## 8. The Microsoft Graph transcript fallback (NOT sovereign, off by default)

Hansard can, if you explicitly enable it, download a transcript that **Microsoft** produced for a
meeting (`GET /users/{id}/onlineMeetings/{mid}/transcripts/{tid}/content?$format=text/vtt`). Use it
only to recover a meeting the notetaker could not attend, and understand what it costs you:

- **It forfeits sovereignty.** Microsoft performed the speech recognition in its cloud; the audio and
  the resulting text were processed outside your infrastructure. Under GDPR that is a processing
  operation by Microsoft as your processor, with its own transfer and retention analysis.
- **It is metered**: about **$0.0022 per minute** beyond 600 free minutes per month, per tenant, per
  application.
- **It requires**: the `OnlineMeetingTranscript.Read.All` **application** permission (admin consent),
  **plus** an application access policy granting the app access to the organiser's meetings:

```powershell
New-CsApplicationAccessPolicy -Identity "Hansard-Graph-Read" `
  -AppIds "<application-client-id>" -Description "Hansard transcript fallback"
Grant-CsApplicationAccessPolicy -PolicyName "Hansard-Graph-Read" -Identity organiser@contoso.com
```

- **It only works if transcription was actually turned on in the meeting**, and the transcript can
  take several minutes to appear after the meeting ends.

The fallback is disabled by default, refuses to run unless explicitly enabled, and emits a warning
every time it is used.

---

## 9. Running the notetaker container

The image in `src/hansard/adapters/capture/docker/` starts, in order: **Xvfb → fluxbox →
PulseAudio → null sink + muted virtual microphone → the worker**. Points worth knowing:

- The browser runs **headful** under Xvfb, not `--headless`. Headless Chromium behaves differently
  for WebRTC media and is treated as a bot signal.
- Playwright's default `--mute-audio` flag is explicitly removed. Without that, you record silence.
- Nothing ever raises or focuses that window, so Chromium is entitled to decide it is occluded and
  clamp the page's timers to roughly once a minute. The instrumentation that attributes speech runs
  on a 100 ms interval; clamped, it reports a meeting nobody spoke in. The browser is therefore
  launched with `--disable-background-timer-throttling`,
  `--disable-backgrounding-occluded-windows` and `--disable-renderer-backgrounding`. The same
  instrumentation calls its exposed binding far more often than an ordinary page would — which is
  exactly what Chromium's IPC flood protection exists to throttle — so
  `--disable-ipc-flooding-protection` goes with them.
- The moment the bot is admitted, every PulseAudio playback stream is moved onto the capture sink
  and the sink is unmuted. Setting the default sink is not enough on its own: PulseAudio restores
  each stream to whichever sink it played to last, and a sink created after the browser started is
  not adopted at all. See
  [troubleshooting](troubleshooting.md#the-capture-recorded-silence-and-you-want-to-know-before-the-meeting-ends).
- The entrypoint runs the worker as a **child process** and forwards `SIGTERM`/`SIGINT`/`SIGHUP` to
  it, then waits in a loop. A pod deletion therefore stops the capture cleanly instead of escalating
  to `SIGKILL` in the middle of a meeting.
- Pin the browser: build once, read the printed
  `sha256` (also stored at `/opt/hansard/chromium.sha256`), then rebuild with
  `--build-arg CHROMIUM_SHA256=<value>`. The build fails if the browser binary ever changes
  underneath you.
- Give the pod a termination grace period long enough to leave the meeting and flush the WAV
  (30 seconds is comfortable).
