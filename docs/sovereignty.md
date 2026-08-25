# Sovereignty and privacy

Hansard exists for one reason: a meeting transcript is one of the most sensitive
documents an organisation produces, and it should never have to leave the
organisation to be useful.

This page states exactly what Hansard does with your data, exactly what the
alternative does, and how you can verify both claims yourself.

## What Hansard guarantees

| Guarantee | How it is enforced |
| --- | --- |
| Audio never leaves your infrastructure | Speech recognition, diarization and minutes generation all run in containers you operate. There is no vendor API in the inference path. |
| No telemetry, ever | There is no analytics code, no crash reporter, no "improve the product" toggle. The `telemetry_enabled` setting exists only to raise an error if anyone tries to turn it on. |
| No model downloads at run time | `HANSARD_RUNTIME__ALLOW_MODEL_DOWNLOADS` defaults to `false`. Models are staged into the image or an internal registry at build time. An air-gapped cluster is a supported configuration, not an afterthought. |
| No outbound connection you did not configure | The only network calls Hansard makes are to endpoints you set: your SMTP server, your Teams tenant, your webhook, your local LLM. Ship the bundled `NetworkPolicy` and the cluster enforces it. |
| Your retention policy, your filesystem | Artefacts are written where you point them. Nothing is copied into anyone's mailbox. Deleting the directory deletes the data. |
| Verifiable | The transcription path runs with `--network none`. If it ever needed the internet, it would fail loudly instead of leaking quietly. |

## What the alternative does

These are not accusations. Every statement below is documented by Microsoft and
linked to its source. They are the facts an organisation should weigh before
deciding where its meetings are processed.

### Meeting content is processed by a large language model, and that inference can happen outside the EU

Microsoft's **Copilot flex routing** documentation states that flex routing
"lets customers in the European Union (EU) and the European Free Trade
Association (EFTA) allow large language model (LLM) inferencing to occur
outside the EU Data Boundary during periods of peak demand", and that
inferencing "may occur in the United States, Canada, or Australia".

The setting is **on by default for eligible tenants created after 25 March 2026**.
Turning it off requires an administrator with the AI Administrator role to go to
the Microsoft 365 admin center and choose *Do not allow flex routing*.

Because AI meeting notes and AI tasks *are* LLM inferencing, meeting content in a
new EU tenant can be inferenced outside the EU unless someone actively opts out.

Source: <https://learn.microsoft.com/en-us/microsoft-365/copilot/copilot-flex-routing>

### The EU Data Boundary has documented carve-outs

Microsoft's own "continuing data transfers" page documents that:

- engineering personnel outside the boundary access EU-stored customer data for
  operations, which Microsoft describes as a transfer under European privacy law;
- pseudonymised personal data processed for security purposes "is transferred to
  any Azure region worldwide" and consolidated "primarily in the United States";
- Multi-Geo customers are not in scope for the EU Data Boundary;
- preview and free-trial services are not in scope — and several meeting recap
  features are in public preview;
- network routing "may occasionally result in routing of customer traffic outside
  of the EU Data Boundary";
- models provided by Anthropic as a subprocessor are excluded from the boundary
  and process customer data in the United States.

Source: <https://learn.microsoft.com/en-us/privacy/eudb/eu-data-boundary-transfers-for-all-services>

### Transcripts are copied into many mailboxes

Teams stores the transcript in the organiser's Exchange Online mailbox, and
stores AI notes, AI tasks, speaker-timeline markers and name-mention markers in
an Exchange folder in the mailbox of **every meeting participant**. Recordings
and chapter markers go to OneDrive or SharePoint. Each copy then follows its own
retention policy and is discoverable through Microsoft Purview.

Source: <https://learn.microsoft.com/en-us/microsoftteams/privacy/intelligent-recap>

### To be fair, here is what Microsoft does commit to

An honest comparison includes the other side. Microsoft states that prompts,
responses and Microsoft Graph data are not used to train foundation models, that
customer data is not logged or used for model training or testing in intelligent
recap, that Copilot services are opted out of Azure OpenAI abuse monitoring and
human review, and that Customer Lockbox is available.

Those are meaningful commitments. They are also commitments, rather than
properties of the architecture. Hansard's position is that for meeting content,
an architectural guarantee is worth more than a contractual one — and that you
should be able to choose.

## Regulatory posture

Hansard is a tool, not legal advice, but it is built so that the compliance
conversation is short.

**GDPR.** A recording of an identifiable person speaking is personal data from
the first word. Running Hansard on your own infrastructure means you remain the
sole controller, there is no processor to contract with, no transfer to assess
under Chapter V, and no sub-processor list to track. You still need a lawful
basis (usually legitimate interests with a documented balancing test, or explicit
consent), a retention period, and a DPIA if you transcribe systematically.

**Consent.** Presence in a meeting is not consent to be recorded. Around eleven
US states require all-party consent, and a single participant in such a state can
bring the whole meeting under that rule. Germany treats non-consensual recording
of a call as a criminal offence. Hansard therefore announces itself: the bot
joins under a name you choose, and posts a recording notice into the meeting chat
on arrival. `announce_recording` is on by default and we strongly recommend
leaving it on.

**Works councils.** In several European jurisdictions, systematic recording of
employees is subject to works-council consultation. The fact that processing is
local, that the retention period is a directory you control, and that no third
party receives the data, generally makes that conversation considerably easier.

**Sector rules.** Because no data leaves the perimeter, Hansard is compatible
with air-gapped and classified environments, with hosting requirements such as
France's SecNumCloud or HDS, and with contractual clauses that forbid
sub-processing entirely.

## Verifying the claims yourself

You do not have to take any of this on trust.

```bash
# 1. Transcribe with no network at all. If anything phoned home, this would fail.
docker run --rm --network none \
  -v "$PWD/audio:/audio:ro" -v "$PWD/out:/out" \
  ghcr.io/haswell119/hansard-worker:latest \
  transcribe /audio/meeting.wav --output /out

# 2. Watch every socket the process opens.
strace -f -e trace=network -o /tmp/net.log hansard transcribe meeting.wav
grep -c 'connect(' /tmp/net.log

# 3. Read the egress policy the Helm chart installs.
helm template hansard deploy/helm/hansard | yq 'select(.kind == "NetworkPolicy")'
```

The first command is also run in our CI on every commit. A pull request that
introduces a network call into the transcription path fails the build.

## What we do not claim

- Hansard does not make Microsoft Teams itself sovereign. If you hold your
  meetings in Teams, Microsoft carries the audio during the call. Hansard
  changes where the *transcription, the analysis and the resulting document*
  live, which is where the durable record is created.
- Hansard is not a legal compliance certification. It is infrastructure that
  makes compliance achievable.
- Running the browser bot means a container in your cluster joins the meeting as
  a participant. Your Teams administrator authorises it explicitly. See
  [Teams setup](teams-setup.md).

## Related reading

- [Architecture](architecture.md) — where every byte goes
- [Deployment on NKP](deployment-nkp.md) — air-gapped installation
- [Teams setup](teams-setup.md) — what your administrator has to approve
- [Benchmarks](benchmarks.md) — the quality you get for it
