# How Hansard measures itself

This page explains every number the evaluation module produces: what it means, how it is
computed, what a good value looks like, and how it can mislead you. It is written for someone
who has to decide whether Hansard is good enough to replace a commercial meeting-transcription
service — not for someone reading the source code.

Everything described here runs **entirely on your own machine**. No audio, no text and no metric
is ever sent to a third party. The only optional network step is downloading a public evaluation
corpus, and you have to ask for it explicitly.

---

## 1. The three questions a meeting transcriber must answer

A meeting transcript is only useful if three things are right at the same time:

1. **The words** — did the system hear what was actually said?
2. **The speakers** — did it attribute each sentence to the right person?
3. **The cost** — did it do so fast enough, on hardware you can afford?

Traditional speech benchmarks only answer question 1. That is why a vendor can advertise a
"2.4 % error rate" and still produce minutes that credit the wrong person for a decision. Hansard
therefore reports a metric for each question, and treats the speaker-aware metric — **cpWER** —
as the headline number.

---

## 2. Text normalization: the invisible thumb on the scale

Before any two transcripts can be compared, they must be written the same way. `Mr. Dupont`,
`monsieur Dupont` and `M. Dupont` are the same words; `21` and `vingt et un` are the same number.
If the comparison is done naively, a perfectly correct system is punished for punctuation.

Normalization is therefore part of the metric, not a detail. **Two error rates are only
comparable if they were produced by the same normalizer.** For that reason every report carries a
`normalizer_version` field (currently `hansard-normalizers-1.0.0`). If that string changes, all
previously recorded baselines must be re-recorded.

### 2.1 The language-agnostic normalizer

`BasicNormalizer` applies Unicode NFKC normalization, lowercases, removes bracketed content such
as `[inaudible]` or `(laughs)`, replaces punctuation with spaces and collapses whitespace. It is
the fallback for languages that have no dedicated normalizer.

**Accents are kept by default.** This matters: OpenAI's widely copied `BasicTextNormalizer`
strips diacritics, which merges `à`/`a`, `é`/`e` and `où`/`ou`. On French that silently deletes a
whole class of errors and deflates the word error rate. Hansard keeps accents unless you opt in
with `BasicNormalizer(strip_accents=True)`, and the same rule applies to French.

### 2.2 English

`EnglishNormalizer` implements the OpenAI Whisper English normalization rules, which are the
de-facto standard for published English WER numbers: bracketed content removal, filler words
(`uh`, `um`, `hmm`) dropped, contractions expanded (`didn't` → `did not`, `Quilter's` →
`quilter is`), title abbreviations expanded (`Mr.` → `mister`, `St.` → `saint`), spelled-out
numbers converted to digits (`twenty five dollars` → `$25`) and British spellings mapped to
American ones (`colour` → `color`).

**Design decision.** The `whisper_normalizer` package is a faithful, clean re-publication of
OpenAI's original code, so when it is installed Hansard uses it. That keeps our English numbers
directly comparable with every published Whisper benchmark instead of "close but not identical".
The package is part of the `metrics` extra, so a correctly installed environment always takes
that path. Hansard also ships its own implementation of the same rule set, used automatically
when the package is missing and selected explicitly with
`EnglishNormalizer(prefer_installed_whisper=False)`. The two agree on contractions, titles,
fillers and punctuation (a unit test asserts it); the built-in fallback handles spelled-out
numbers with a simpler grammar, so prefer the packaged path for headline figures.

### 2.3 French — the part that decides whether your numbers are real

French normalization is where fake improvements are manufactured, so `FrenchNormalizer` is
deliberately explicit:

| Step | Example | Result |
| --- | --- | --- |
| Apostrophe variants unified | `l’équipe` | `l'équipe` |
| Titles expanded (before lowercasing, so `M.` ≠ `m`) | `M. Dupont`, `Mme Martin` | `monsieur dupont`, `madame martin` |
| Symbols spoken | `%`, `€`, `n° 42` | `pour cent`, `euros`, `numéro quarante-deux` |
| Ligatures | `cœur` | `coeur` |
| Elisions split, never glued | `l'équipe`, `aujourd'hui` | `l équipe`, `aujourd hui` |
| Digits spelled out | `1 200`, `9h30`, `1er`, `3,5` | `mille deux cent`, `neuf heures trente`, `premier`, `trois virgule cinq` |
| Hyphens become spaces | `quatre-vingt-dix` | `quatre vingt dix` |
| Number plurals folded | `quatre-vingts`, `deux cents` | `quatre vingt`, `deux cent` |
| Fillers removed | `euh`, `ben`, `bah`, `hein` | *(removed)* |
| Accents | `très élégant` | `très élégant` (kept) |

**Canonical direction: spell-out.** Numbers are always converted from digits to words, never the
other way round. Spelling out is safe (`21` has exactly one reading, `vingt et un`), while
parsing French number words back into digits is ambiguous and error-prone. The speller covers
0 – 999 999 999 with correct French orthography, including the awkward cases: `soixante-dix`,
`soixante et onze`, `quatre-vingts`, `quatre-vingt-un`, `quatre-vingt-dix-neuf`, `deux cents`,
`deux cent un`, years (`1995` → `mille neuf cent quatre-vingt-quinze`) and ordinals (`1er` →
`premier`, `1re` → `première`, `5e` → `cinquième`, `9e` → `neuvième`, `21e` → `vingt et unième`).

Because hyphens are turned into spaces and the plural `s` of `vingts`/`cents` is folded away,
the pre-1990 spelling (`vingt et un`) and the post-reform spelling (`vingt-et-un`) normalize to
exactly the same token sequence. A human reference and a machine hypothesis can no longer differ
merely because of a spelling convention.

**Known limitation.** Gender agreement is not applied to spelled numbers outside of times
(`21 personnes` normalizes to `vingt et un personnes`, not `vingt et une personnes`). Both sides
of the comparison are normalized identically, so this costs at most a fixed, symmetric penalty
when the reference is written in words; it never favours the system under test.

---

## 3. Word-level metrics

### 3.1 Word error rate (WER)

```
WER = (substitutions + deletions + insertions) / words_in_reference
```

The three error types come from the optimal alignment between the reference and the hypothesis
(computed with `jiwer`). A substitution is a wrong word, a deletion is a missing word, an
insertion is an invented word.

*Why it matters.* It is the universal comparison point for speech recognition, and the number
every vendor publishes.

*How to read it.* 5 % means one word in twenty is wrong. WER can exceed 100 % if the system
hallucinates more words than were spoken. It says nothing at all about who spoke.

*Aggregation.* Corpus WER is computed as total errors over total reference words, not as the
average of per-file WERs. Short files therefore do not dominate the result.

### 3.2 Character error rate (CER)

The same formula at character level. It is useful for French, where a single wrong accent or
elision would count as a whole wrong word in WER but as one wrong character here. A large gap
between CER and WER usually means spelling and agreement problems rather than misheard speech.

---

## 4. Speaker-aware metrics — the ones that decide meeting quality

### 4.1 cpWER — concatenated minimum-permutation word error rate (**primary metric**)

For each speaker, all their utterances are concatenated into one long stream, on both sides. The
system's speaker labels (`spk0`, `spk1`, …) are then matched to the reference speakers (`Marie`,
`Paul`, …) using the assignment that minimizes the total number of errors — computed exactly with
the Hungarian algorithm, not greedily. cpWER is the total error count of that best assignment
divided by the total number of reference words.

```
cpWER = min over speaker permutations of (S + D + I) / words_in_reference
```

*Why it matters.* This is what CHiME-6/7/8 and NOTSOFAR rank systems on, and it is the only
common metric that punishes both misheard words **and** misattributed speech. If the system
merges two participants, the words of one of them become insertions and deletions against the
other, and the score collapses — as it should, because merged speakers destroy meeting minutes.

*How to read it.* cpWER is always at least as large as WER on the same audio. A system with 8 %
WER and 30 % cpWER hears well and attributes badly; its minutes will be confidently wrong.

*Extra speakers.* If the system invents a speaker who has no counterpart in the reference, that
speaker's words all count as insertions (`false_alarm_speakers`); a missed speaker's words all
count as deletions (`missed_speakers`).

*Cross-check.* When the optional `meeteval` package is installed, `cross_check_with_meeteval()`
recomputes cpWER with the reference implementation used by the CHiME organizers. Our test suite
asserts that both agree exactly on fixed fixtures.

### 4.2 tcpWER — time-constrained cpWER

cpWER has one blind spot: it ignores *when* a word was said. A system that transcribes everything
correctly but places it minutes away from the real timestamps still scores 0 %. tcpWER closes
that hole: a reference word and a hypothesis word may only be aligned if their time intervals
overlap once the reference interval is extended by a collar (5 seconds by default, the CHiME-8 /
NOTSOFAR convention). Words that drift outside the collar can no longer match, so they are
charged as one deletion plus one insertion.

Word timings come from word-level timestamps when the engine provides them; otherwise the
utterance's time span is divided evenly across its words, which is accurate enough at a 5 s
collar.

*How to read it.* tcpWER ≈ cpWER means the timeline is trustworthy — citations, jump-to-audio
links and time-boxed topics will land in the right place. tcpWER ≫ cpWER means the content is
right but the timeline is not.

*Cost.* The time-constrained alignment is a dynamic program over both word sequences. Very long
single sessions (millions of word pairs) are refused with an explicit error rather than running
for hours; split them into shorter sessions.

### 4.3 WDER — word diarization error rate

```
WDER = words_recognized_correctly_but_attributed_to_the_wrong_speaker / words_recognized_correctly
```

Only correctly recognized words are considered, and speaker labels are again matched optimally
before counting.

*Why it matters.* It isolates attribution quality from transcription quality. cpWER mixes the two;
WDER answers the single question "when the words were right, was the name right?".

*How to read it.* 5 % means one correctly transcribed word in twenty is credited to the wrong
person. Because minutes quote and attribute, WDER is the metric that predicts embarrassing
minutes most directly.

### 4.4 DER — diarization error rate

DER scores the speaker timeline alone, ignoring words entirely. The reference and hypothesis
timelines are cut into regions at every boundary; in each region the number of active reference
speakers and system speakers is compared.

```
DER = (missed speech + false alarm speech + speaker confusion) / total reference speech time
```

* **Missed speech** — someone was speaking and the system heard nobody.
* **False alarm** — the system heard someone when nobody (or fewer people) was speaking.
* **Speaker confusion** — the right amount of speech, credited to the wrong speaker.

All three components are reported separately, because they call for different fixes: missed
speech points at voice-activity detection, false alarm at noise, confusion at clustering.

*Collar.* Human annotations are imprecise at turn boundaries, so a collar (0.25 s by default)
excludes a window around every reference boundary from scoring. This is the NIST convention.
Report the collar with the number: DER at 0 s and DER at 0.25 s are different metrics.

*Overlap.* Set `skip_overlap=True` to exclude regions where several people speak at once — also a
common convention. Hansard scores overlap by default, which is stricter and more honest for
meetings.

### 4.5 JER — Jaccard error rate

For each reference speaker, mapped to their best-matching system speaker:

```
JER_speaker = 1 - (time where both agree) / (time where either is active)
JER         = average over reference speakers
```

Unlike DER, every speaker counts equally regardless of how much they talked. A quiet participant
who is completely missed shows up loudly in JER and barely at all in DER. Use JER to check that
minority speakers are not being sacrificed.

### 4.6 Speaker count error

The signed difference between the number of speakers found and the number really present
(negative = speakers merged, positive = speakers split). Reported per meeting, and aggregated as
a mean absolute error across the corpus.

---

## 5. Minutes and summary metrics (no cloud service involved)

These metrics judge the generated minutes, deterministically and locally.

### 5.1 Action-item F1 and owner accuracy

Reference and generated action items are matched one-to-one by fuzzy text similarity (a token-set
ratio computed with the standard library, threshold 0.7 by default), using the assignment that
maximizes total similarity. From the matched count:

```
precision = matched / generated      recall = matched / reference
F1        = 2·precision·recall / (precision + recall)
```

**Owner accuracy** is the share of matched action items whose owner also matches. An action item
with the right task and the wrong owner counts as found by F1 and as wrong by owner accuracy —
which is exactly the distinction that matters when the minutes are circulated.

*Caveat to know.* With a token-set ratio, a hypothesis whose words are a subset of the reference
("Send report" vs "Send the budget report to Marie") scores 1.0. Raising the threshold does not
change that; if you need stricter behaviour, pass your own matcher — the metric accepts any
object with `similarity()`, `matches()` and `threshold`.

### 5.2 Decision recall

The share of reference decisions that appear in the generated minutes, matched with the same
fuzzy matcher. Missing a decision is far worse than phrasing it differently, which is why recall
is reported rather than F1.

### 5.3 Grounding score — a local factuality proxy

```
grounding = supported sentences / sentences containing content words
```

Every sentence of the minutes (abstract, topic summaries, key points, decisions, actions, open
questions) is normalized and reduced to its *content words* — tokens that are not stop-words in
French or English and are at least three characters long, plus numbers. A sentence is
**supported** when at least 70 % of its content words also occur in the transcript.

*Why it matters.* It is a cheap, deterministic, offline proxy for "did the model invent this?".
It requires no second model and gives the same answer every time.

*How to read it.* 1.0 means every sentence is vocabulary-grounded in the meeting. It cannot
detect a sentence that reuses the right words to state the opposite fact — for that, use the
optional rubric judge below. Legitimate paraphrase ("migration" for "migrate") lowers the score
slightly, so compare grounding across runs rather than reading it as an absolute truth score.

### 5.4 Hallucination rate

```
hallucination = mentions absent from the transcript / mentions extracted from the minutes
```

Mentions are named entities and numbers pulled out of the minutes with regular expressions and
capitalization heuristics (no external NLP model): capitalized word sequences that are not merely
sentence-initial, plus every number. A mention is supported when all of its words (accent- and
case-insensitively) or its digits appear in the transcript.

*How to read it.* This is the metric that catches invented people, invented amounts and invented
dates — the failure mode that makes a summary dangerous rather than merely poor. Target 0.

### 5.5 Optional rubric judge

`RubricJudge` sends the transcript and the minutes to a **local** OpenAI-compatible model through
the project's existing `TextGenerator` port, with a strict rubric that returns JSON scores from 1
to 5 for coverage, faithfulness, actionability and structure. It is entirely optional; nothing in
the harness or the quality gates requires it, and no metric silently depends on it. Its output is
advisory: LLM judges are not reproducible across model versions, so do not gate releases on them.

---

## 6. Cost metrics

* **Real-time factor (RTF)** = `processing seconds / audio seconds`. 0.5 means one hour of
  meeting is transcribed in thirty minutes; below 1.0 is required to keep up with a live meeting
  on the same machine. The inverse (`speedup`) is also available.
* **Peak resident memory** — the highest physical memory the process ever held, read from
  `VmHWM` in `/proc/self/status` and cross-checked with `getrusage`. This is the number that
  decides which machine you need.
* **CPU time** and **wall-clock time** — together they show whether the pipeline is actually using
  the cores you paid for.
* **GPU memory** — reported when an NVIDIA GPU and `pynvml` are present, otherwise absent from
  the report rather than reported as zero.

---

## 7. Evaluation data

### 7.1 JSONL manifests

The simple form, one JSON object per line:

```json
{"audio": "/data/0000.wav", "text": "the reference words", "seconds": 5.85, "language": "en"}
```

The extended form adds per-utterance speaker segments, which unlocks cpWER, tcpWER, WDER and DER:

```json
{"audio": "/data/meeting.wav", "language": "fr",
 "utterances": [{"start": 0.0, "end": 2.0, "speaker": "Marie", "text": "bonjour"},
                {"start": 2.0, "end": 5.0, "speaker": "Paul", "text": "salut"}]}
```

`seconds` may also be written `duration`, and `utterances` may also be written `segments`, so the
bundled reference files load unchanged.

### 7.2 Reference bundles (`.ref.json`)

A single JSON object with `audio`, `duration`, `speakers` and `segments`. When a matching
`.rttm` file sits next to it, that file is used as the reference diarization. This is the shape
of the bundled synthetic meetings (`meeting_3spk`, `meeting_6spk`, `meeting_9spk`), which have
exact ground truth and are used to unit-test DER, cpWER, tcpWER and WDER against hand-computed
answers.

### 7.3 RTTM

The NIST speaker-timeline format, readable and writable:

```
SPEAKER meeting 1 0.000 2.500 <NA> <NA> Marie <NA> <NA>
```

Output is sorted deterministically (by file, then start time, then label) so that two runs
produce byte-identical files.

### 7.4 WebVTT and SRT, including Microsoft Teams exports

Both formats are parsed, with cue text, timings and speaker names. Teams and Copilot exports use
the WebVTT voice-span convention:

```
00:00:01.000 --> 00:00:04.000
<v Marie Dupont>Bonjour à tous, on commence.</v>
```

The speaker name is taken from the `<v …>` tag; when there is none, a leading `Name:` prefix is
recognized. This means a Teams transcript can be used either as the **hypothesis** (to benchmark
Microsoft against Hansard on your own meetings) or as the **reference** (when Teams output has
been manually corrected).

### 7.5 SUMM-RE — French meetings (optional, large)

French *meeting* speech is much harder than French *read* speech, so read-speech corpora cannot
be used to set meeting expectations. SUMM-RE (`linagora/SUMM-RE`, CC-BY-SA-4.0) is the reference
corpus of transcribed French meetings, distributed as per-speaker tracks. It is roughly **93 GB**,
so Hansard never downloads it implicitly.

Preparation, when you want it:

1. Fetch the corpus once — `download_summ_re(destination)` wraps `huggingface_hub`, or download it
   manually. Nothing else in the module will ever start a download.
2. Arrange each meeting as one directory containing one JSON file per speaker (named after the
   speaker) holding `{"start", "end", "text"}` records, plus an optional `mixed.wav`.
3. Run `prepare_summ_re(root, rttm_directory)`. It reads every meeting, sums the per-speaker
   tracks into a single reference timeline and writes one RTTM per meeting.
4. `summ_re_samples(root)` then yields ready-to-benchmark samples tagged `fr` / `summ-re`.

---

## 8. Bilingual reporting is mandatory

Hansard is built for organizations that meet in French **and** in English. A benchmark that
reports only English is not a benchmark of this product.

Every report therefore carries a language dimension:

* one row per **(dataset, language)** pair — for example `fleurs_fr / fr`, `synthetic / en`;
* one roll-up row per language;
* one overall row.

The Markdown report prints the headline metrics for each language side by side, and the JSON
report contains `metrics`, `metrics_by_language` and `metrics_by_dataset`. French quality gates
are evaluated against the French numbers only, and if a run contains no French data those gates
are marked **missing**, which fails the run. It is deliberately impossible to publish an
English-only pass.

---

## 9. What we are competing against

These are measured third-party figures, not our own runs, and they are shipped as the default
baseline column so that comparisons stay honest.

| System / condition | Metric | Value | Source |
| --- | --- | --- | --- |
| Azure / Teams on AMI | cpWER | 27.39 % | AssemblyAI benchmark, January 2026 |
| Azure / Teams on NOTSOFAR-1 (test) | cpWER | 35.68 % | AssemblyAI benchmark, January 2026 |
| Azure / Teams on NOTSOFAR-1 (dev) | cpWER | 45.38 % | AssemblyAI benchmark, January 2026 |
| Azure / Teams on DiPCo | cpWER | 33.23 % | AssemblyAI benchmark, January 2026 |
| Teams live transcription, English, controlled | WER | 11.54 % | TestDevLab, 2024 |
| Teams live transcription, English, field | WER | 12 – 25 % | TestDevLab, 2024 |
| Microsoft marketing claim, curated short clips | WER | 2.4 % | Vendor material |

Two honest conclusions follow.

**The advertised 2.4 % is not a meeting number.** It comes from short, clean, curated clips with
one speaker. The same technology, measured on real multi-speaker meetings with diarization, lands
between 27 % and 45 % cpWER — an order of magnitude away. Any README comparison that quotes 2.4 %
against a meeting-transcription system is comparing two different problems.

**There is no published Azure or Copilot figure for French meetings.** None. The baseline column
for French is therefore intentionally empty, and Hansard's French meeting numbers will be the
first ones publicly available for this task. Never fill that cell with an English value.

For calibration, published WER on the SUMM-RE French meeting corpus is 19.79 % for
`linto_stt_fr_fastconformer_pc`, 19.82 % for `canary-1b`, 22.57 % for `whisper-large-v3` and
22.87 % for `whisper-large-v3-turbo`. The same class of model scores 4 – 5 % on FLEURS-fr *read*
speech. French meeting targets must be set from the first list, never from the second.

---

## 10. Quality gates

A gate is one line: a metric, a comparison, a threshold, a tier and a language.

* **must_pass** — a release blocker. Any failure, or any missing metric, fails the run.
* **stretch** — where we want to be. Never blocks; it is reported so that progress is visible.

Default meeting gates (`DEFAULT_GATES`, tune them as evidence accumulates):

| Metric | English must_pass | English stretch | French must_pass | French stretch |
| --- | --- | --- | --- | --- |
| cpWER | ≤ 27 % | ≤ 20 % | ≤ 30 % | ≤ 22 % |
| tcpWER (5 s collar) | ≤ 30 % | — | ≤ 33 % | — |
| WDER | ≤ 10 % | ≤ 5 % | ≤ 12 % | ≤ 6 % |
| WER | ≤ 15 % | ≤ 12 % | ≤ 20 % | ≤ 17 % |
| CER | ≤ 8 % | — | ≤ 10 % | — |
| DER (0.25 s collar) | ≤ 15 % | ≤ 8 % | ≤ 15 % | ≤ 8 % |
| Speaker count error | ≤ 1 | — | ≤ 1 | — |

System gates apply to the whole run: RTF ≤ 1.0 (stretch ≤ 0.35) and peak memory ≤ 8 GB.

The English cpWER blocker is set just under Azure's measured 27.39 % on AMI: shipping a release
that does not beat the incumbent on its own headline metric is not acceptable. French thresholds
are anchored on published SUMM-RE results, with a margin because no vendor number exists to
compare against.

A separate, much stricter set (`READ_SPEECH_GATES`) applies to read-speech corpora such as
LibriSpeech and FLEURS: ≤ 5 % WER for English and ≤ 6 % for French. Never gate meetings with
read-speech thresholds, or the reverse.

---

## 11. Reading a report without fooling yourself

1. **Check the normalizer version first.** Different version, different scale — the numbers are
   not comparable, no matter how similar they look.
2. **Check that both languages are present.** A missing language is a missing conclusion, not a
   neutral result.
3. **Read cpWER before WER.** WER measures a component; cpWER measures the product.
4. **Compare tcpWER with cpWER** to know whether the timeline can be trusted.
5. **Read the DER components, not just DER.** Missed speech, false alarm and confusion have
   different causes and different fixes.
6. **Check the collar and the overlap setting** before comparing a DER with a published one.
7. **Read RTF and peak memory next to quality.** A 3 % improvement that halves throughput may not
   be worth deploying.
8. **Treat grounding and hallucination as regression detectors**, not as absolute truth scores.
9. **Never compare a meeting number with a read-speech number**, in either direction.
