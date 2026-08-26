# Meetings held in two languages

Some meetings are not held in a language. They are held in two. Somebody opens in
French, the platform team answers in English, and the decision at the end is taken
in whichever language the person who took it happened to be speaking.

This page describes what Hansard does with those meetings, how it is measured, and
where it still falls short.

## What "mixed" means here

Two things are worth separating, because they are not equally hard.

**Inter-speaker code-switching.** Different people speak different languages in the
same meeting. Aurélie speaks French throughout, Sofia speaks English throughout.
This is the common case in a bilingual organisation and Hansard handles it.

**Intra-speaker code-switching.** One person switches language mid-meeting, or mid
sentence — *"le kickoff meeting est prévu pour la semaine prochaine"*. Hansard
handles the sentence-level case: each utterance is labelled independently, so a
speaker who switches between turns is followed. Within a single sentence, the
sentence is assigned to its **matrix language** — the grammar it is built on — and
borrowed words are left where they are. *"Le kickoff meeting est prévu"* is French
containing two English nouns, and is reported as French. That is the right answer
for extraction, and it is not the same thing as word-level language labelling,
which Hansard does not do.

## How it works

A multilingual meeting needs no configuration. Leave `HANSARD_ASR__LANGUAGE` unset,
or set it to `mixed` to say so explicitly — they mean the same thing to the
recogniser.

```
                        ┌───────────────────────────────────────────────┐
  audio  ───────────▶   │  Recognise    Parakeet TDT 0.6b v3 decodes     │
                        │               each speech segment in whatever  │
                        │               language it was spoken in. No    │
                        │               decoding language is forced.     │
                        ├───────────────────────────────────────────────┤
                        │  Identify     every utterance is labelled fr   │
                        │               or en from the text that came    │
                        │               back; short utterances inherit   │
                        │               from their own speaker           │
                        ├───────────────────────────────────────────────┤
                        │  Extract      decisions, actions, deadlines    │
                        │               and questions are matched with   │
                        │               the cues of the language each    │
                        │               sentence was spoken in           │
                        ├───────────────────────────────────────────────┤
                        │  Render       headings in the dominant         │
                        │               language, content untranslated   │
                        └───────────────────────────────────────────────┘
```

**Why identification runs on the text and not on the audio.** Parakeet transcribes
25 European languages and switches between them by itself, but it does not report
which one it used. Rather than add a second acoustic model and a second pass over
the audio, Hansard reads the words that came back. Function words, elisions
(`l'`, `qu'`, `d'`), diacritics and contractions (`I'll`, `don't`) separate French
from English decisively and for free. An utterance with too little evidence —
"Okay.", "Mm." — is not guessed at: it inherits from the nearest labelled utterance
**by the same speaker**, looking forward before back, because a short
acknowledgement more often opens the speaker's next turn than closes the previous
one. Only if that speaker says nothing decidable anywhere does it fall back to its
neighbours.

Turn this off with `HANSARD_ASR__IDENTIFY_LANGUAGE=false` to get the pre-1.1
behaviour back. Pinning `HANSARD_ASR__LANGUAGE=fr` does **not** turn it off, and on
the default engine it does not steer the recogniser either — see
[below](#when-the-recogniser-picks-the-wrong-language). It labels the meeting and
supplies the fallback for utterances the identifier cannot decide; an utterance it
*can* decide keeps the language it was actually spoken in.

## When the recogniser picks the wrong language

Everything above assumes the recogniser transcribed what was said. On long
segments it may not.

Parakeet TDT 0.6b v3 carries one shared vocabulary for 25 languages and no
language conditioning at all — passing a language to it through `onnx-asr` is
silently ignored, because only Whisper and Canary read that argument. The model
therefore infers the language acoustically, per decoded segment, and **the longer
the segment the less reliably it does so.**

Measured on a 6-minute French recording, decoding the same audio at different
segment ceilings and nothing else changed:

| Segment ceiling | Words transcribed | Share of output in French |
| ---: | ---: | ---: |
| 4 s | **858** | **95 %** |
| 6 s | 829 | 79 % |
| 8 s | 762 | 57 % |
| 15 s | 694 | 66 % |
| 120 s (the default) | 318 | 11 % |

Two failures at once, and they have the same cause. The output drifts into
English — French speech spelled as English words, *"on va se pencher sur"*
becoming *"one will pench on"* — and it **deletes more than half the words**.

This is why `AUDIO__MAX_SEGMENT_SECONDS` is not the harmless memory knob it looks
like. Its default of 120 s was tuned on AMI, an English corpus, where drift
cannot happen and long context genuinely helps: the repository measures 120 s as
4.1 WER points better than 28 s there. On French the same setting is
catastrophic.

### The guard

Lowering the ceiling for everyone would trade a measured English gain for an
unmeasured one, so the pipeline detects the failure instead of assuming it:

1. Decode normally, at whatever ceiling is configured.
2. Decode a handful of **short probes** — eight 4-second windows spread across
   the detected speech, about 1 % of an hour-long meeting.
3. Identify the language of the probe text and of the full transcript. If they
   agree, stop: nothing drifted, and nothing was re-decoded.
4. If they disagree, re-decode at successively shorter ceilings — 15 s, then 8 s,
   then 4 s — stopping at the first where the probed language accounts for at
   least 75 % of the transcript.

The probe must run at the ceiling the recogniser is most reliable at, which is
why it defaults to the lowest rung of the ladder. At 4 s the probe on the
reference recording returned French with no English evidence whatsoever; at 6 s
it was wrong often enough to miss the drift completely. That is a real
sensitivity, not a tuning detail.

Turn the whole thing off with `HANSARD_ASR__LANGUAGE_DRIFT_GUARD=false`.

### What this does not fix

- **The guard only fires when the probe disagrees with the transcript.** If the
  recogniser drifts so thoroughly that even 4-second windows come out in the
  wrong language, the probe agrees with the drifted transcript and the guard
  stays silent. It repairs a wrong decision; it cannot repair audio the model
  simply cannot read.
- **It is validated on one recording.** The numbers above come from a single
  6-minute French podcast. The mechanism is exercised by unit tests against
  scripted recognisers, but the ladder values are calibrated on that one file and
  should be re-derived once a French meeting benchmark exists.
- **Shorter segments cost context.** Punctuation, capitalisation and long-range
  agreement all suffer when the model sees 4 seconds instead of 120. The guard
  accepts that cost only on recordings that were already unusable.

## Why it matters more than it sounds

Language is not only a label on the transcript. Almost every downstream stage is
language-dependent, and before this work each of them ran with **one** language for
the whole meeting — English, by default, whenever no language was configured.

| Stage | What is language-dependent |
| --- | --- |
| Decision detection | `on acte`, `c'est validé` vs `we agreed`, `let's go with` |
| Action detection | `je m'occupe de`, `peux-tu` vs `I'll take`, `can you` |
| Deadline resolution | `vendredi prochain`, `d'ici la fin du mois` vs `next Friday`, `EOM` |
| Question detection | `est-ce que`, `qui prend` vs `should we`, `who owns` |
| Boilerplate | `bonne journée`, `on se retrouve` vs `have a good day` |
| Stemming and stopwords | different suffix tables, different function words |
| Phonetic matching | French and English spelling-to-sound rules differ |
| Scoring | number expansion and contraction handling differ |

The consequence was concrete. On a bilingual meeting scored as English, the French
decisions, French action items and French deadlines were **silently dropped** — not
flagged, not degraded, absent. The minutes looked complete and were half a meeting.

Here is that difference on a fixture with four French turns and four English ones:

| | Meeting scored as `en` | Meeting scored as `mixed` |
| --- | --- | --- |
| Decisions found | 1 (English only) | 2 (both) |
| Actions found | 1 (English only) | 2 (both) |
| French deadline resolved | — | `vendredi prochain` → 2026-06-12 |
| English deadline resolved | `before Friday` → 2026-06-05 | `before Friday` → 2026-06-05 |

The two deadlines resolve to different dates because they mean different dates, and
each was resolved with its own language's rules.

## What comes out

The transcript and minutes carry the mix explicitly.

- Every utterance in the JSON export has a `language`.
- The transcript payload carries `languages`, `language_shares` and `code_switched`.
- The metadata line reads *"français et anglais (fr, en)"* rather than naming one.
- Headings and labels render in the **dominant** language; nothing is translated.
- The minutes are stamped `mixed`, and each item stays in the language it was said
  in. The LLM prompt pack for mixed meetings forbids translating quotes and forbids
  collapsing the meeting into one language.

A language counts as present when it carries at least 10 % of the transcribed words
or at least 20 seconds of speech. Below that it is treated as borrowing, not as a
second meeting language, and the meeting is not marked `mixed`.

## How it is measured

`make bench-mixed` scores three code-switched fixtures built from the same
generators as the monolingual ones — LibriSpeech speakers and MLS French speakers
drawn alternately into one meeting, so the reference knows which language every
segment is in.

Alongside the usual cpWER, WER and DER, a mixed run reports
**`language_accuracy`**: the share of transcribed words whose language label matches
the reference, weighted by word count. The mixed quality gates require 95 % and
stretch to 98 %.

Word error rate on a mixed meeting is computed with a **mixed normalizer**, which
splits the text into language runs and normalises each with its own rules —
applying English number and contraction handling to a French passage would inflate
its error rate for reasons that have nothing to do with recognition.

### Comparing against another system

`hansard compare` scores any number of systems against the same reference and
breaks the result down **by language spoken**, which is where a single-language
system loses:

```bash
hansard compare reference.ref.json \
  --system hansard=artifacts/meeting/transcript.json \
  --system teams=exports/copilot.vtt \
  --meeting "board sync" \
  --report comparison.md
```

The reference and each system may be `.json` (a Hansard export or a reference file)
or `.vtt`/`.srt` — including the `.vtt` Microsoft Graph returns for a Teams
meeting, whose `<v Name>` voice tags are read as speakers. A system whose transcript
carries no language labels is labelled by Hansard's own identifier before scoring,
so the comparison measures **the language each system actually produced**, not the
one it claimed.

Read `language_accuracy` on a third-party system carefully. It scores the language
of the words that came out. A system that renders a French passage as
English-sounding nonsense is reported as having produced English — which is true,
and is *not* the same statement as "it got the language wrong N % of the time".
The per-language WER is the honest number for that.

The per-language breakdown is the point. A system locked to one language does not
degrade evenly: its English stays clean and its French collapses, and an overall
WER averages that away.

## Limits, stated plainly

- **No French/English meeting benchmark has been published yet.** The fixtures and
  the gates exist and run; the numbers in [benchmarks](benchmarks.md) do not yet
  include a mixed row, because none has been recorded on real hardware. We would
  rather leave the cell empty than fill it with a monolingual number.
- **The synthetic mixed fixtures model inter-speaker switching only.** Each
  synthetic speaker speaks one language, because the source corpora are
  monolingual and splicing French audio onto an English speaker's voice would
  corrupt the diarization ground truth. Intra-speaker switching is exercised by
  unit tests on text, not by an audio benchmark.
- **Language identification is lexical, not acoustic.** It reads what the
  recogniser produced. If the recogniser mis-transcribes a French passage as
  English words, the identifier will faithfully report English — it measures output,
  not truth. That is the correct behaviour for a comparison harness and a real
  limitation for error analysis.
- **Only French and English.** Parakeet decodes 25 languages, and the pipeline will
  transcribe them, but the cue sets, stopwords, date grammars and identification
  markers exist for `fr` and `en` only. A third language will transcribe and will
  fall back to bilingual union behaviour downstream, which is not the same as
  being supported.
- **Word-level language labelling is not implemented.** The unit is the utterance,
  and within a sentence the matrix language wins.
- **An utterance with no lexical evidence is inherited, not measured.** A turn made
  only of proper nouns and figures — *"Meridian 16, Legrand, 42, PostgreSQL."* —
  carries no signal in either language. It takes the label of the nearest decided
  turn by the same speaker, which is a reasonable guess and still a guess. Such
  turns count towards `language_shares` under an inherited label, so a meeting full
  of telegraphic recaps has slightly softer share figures than its content warrants.
