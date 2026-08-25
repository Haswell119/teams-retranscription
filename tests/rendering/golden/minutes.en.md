# Weekly platform sync

_Minutes_

- **Date:** 3 June 2026 at 09:30 (UTC)
- **Duration:** 25 min
- **Attendees:** Amara Okafor, Léa Fontaine, Jonas Weber
- **Language:** English (en)
- **Produced with:** parakeet (nemo-parakeet-tdt-0.6b-v3), sortformer (diar_streaming_sortformer_4spk), qwen3 (qwen3-8b-instruct)

## Executive summary

The team confirmed that release 4.2 is ready apart from the German locale, agreed a two-week on-call rotation after last Tuesday's night incident, and approved two additional GPU nodes for the sovereign transcription cluster.

## Key decisions

1. **Release 4.2 ships on 12 June with the German locale disabled.** [00:06:11]
   - Rationale: The billing strings are neither translated nor proof-read, and the release window is fixed.
2. **The on-call rotation moves to a two-week cycle from July.** [00:13:32]
   - Rationale: A weekly cycle concentrates night work on a single responder.
3. **Two additional GPU nodes are approved for the transcription cluster.** [00:23:45]

## Action items

| Owner | Action | Due | Source |
| --- | --- | --- | --- |
| Léa Fontaine | Disable the German locale in the 4.2 release branch and open a translation ticket. | 2026-06-10 | 00:06:20 |
| Jonas Weber | Circulate the incident review notes and the new hand-over template. | 2026-06-05 | 00:10:52 |
| Unassigned | Draft the procurement request for the two GPU nodes. | — | — |
| Amara Okafor | Compare on-premises \| cloud costs for the cluster before the board meeting. | 2026-06-18 | — |

## Discussion by topic

### 1. Release 4.2 readiness (00:00:00 – 00:07:00)

Every runner is green and the only blocker is the German locale, where 47 billing strings are still untranslated and unreviewed.

- Build and integration suites pass on all runners.
- 47 untranslated strings remain, all in the billing screens.
- The release window on 12 June cannot be moved.

### 2. On-call rotation and incident review (00:07:00 – 00:17:00)

Last Tuesday's night incident showed that the weekly rotation concentrates fatigue and that hand-over notes are not written down.

- The pager fired at 02:00 for a responder at the end of a full week.
- Hand-over notes were missing entirely.

### 3. Transcription cluster capacity (00:17:00 – 00:25:00)

Peak queue time exceeds ten minutes; two additional GPU nodes bring it back within the service target without leaving the data centre.

- Queue time at peak is above the ten-minute target.

## Open questions

- Do we need a second reviewer for the German locale before the next release? — _raised by Léa Fontaine_ [00:07:35]
- Who owns the monthly cost report once the cluster is live?

## Speaking time

| Speaker | Duration | Share |
| --- | --- | --- |
| Amara Okafor | 10 min 12 s | 40.8% |
| Léa Fontaine | 8 min 18 s | 33.2% |
| Jonas Weber | 5 min 10 s | 20.7% |
| Unidentified speaker | 1 min 18 s | 5.3% |

---

_Transcribed and summarised locally by Hansard using parakeet (nemo-parakeet-tdt-0.6b-v3), sortformer (diar_streaming_sortformer_4spk), qwen3 (qwen3-8b-instruct). No audio, transcript or minutes left the organisation._

_Generated on 3 June 2026 at 10:02 (UTC)_
