from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

from hansard.adapters.enhancement.segmentation import SegmentationPolicy
from hansard.application.drift import DriftGuardPolicy, has_drifted, probe_spans
from hansard.application.pipeline import TranscriptionPipeline
from hansard.domain.audio import AudioClip
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Diarization
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.ports.asr import EngineProfile, RecognitionHints

FRENCH = "Aujourd'hui on va se pencher sur la copropriété et sur le dilemme auquel elle est confrontée."
DRIFTED = "Today one will pench on the copropriety and on the dilemma to which it is confronted."

LONG_SEGMENT = 120.0
SAFE_SEGMENT = 15.0
AUDIO_SECONDS = 360.0


@dataclass(slots=True)
class DriftingRecognizer:
    calls: list[RecognitionHints] = field(default_factory=list)
    drifts_above: float = 20.0

    @property
    def profile(self) -> EngineProfile:
        return EngineProfile(
            name="drifting",
            languages=("en", "fr"),
            emits_word_timestamps=False,
            emits_punctuation=True,
            resident_memory_mb=1,
            license_identifier="mit",
        )

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        self.calls.append(hints)
        spans = hints.segments or (clip.span,)
        longest = max(span.duration for span in spans)
        text = DRIFTED if longest > self.drifts_above else FRENCH
        utterances = tuple(Utterance(span=span, text=text, speaker="Speaker 1") for span in spans)
        return Transcript(utterances=utterances, audio_duration=clip.duration)


@dataclass(slots=True)
class SteadyRecognizer:
    calls: list[RecognitionHints] = field(default_factory=list)

    @property
    def profile(self) -> EngineProfile:
        return EngineProfile(
            name="steady",
            languages=("en", "fr"),
            emits_word_timestamps=False,
            emits_punctuation=True,
            resident_memory_mb=1,
            license_identifier="mit",
        )

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        self.calls.append(hints)
        spans = hints.segments or (clip.span,)
        utterances = tuple(Utterance(span=span, text=FRENCH, speaker="Speaker 1") for span in spans)
        return Transcript(utterances=utterances, audio_duration=clip.duration)


@dataclass(slots=True)
class HardPassageRecognizer:
    easy_seconds: float = 60.0
    calls: list[RecognitionHints] = field(default_factory=list)

    @property
    def profile(self) -> EngineProfile:
        return EngineProfile(
            name="hard-passages",
            languages=("en", "fr"),
            emits_word_timestamps=False,
            emits_punctuation=True,
            resident_memory_mb=1,
            license_identifier="mit",
        )

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        self.calls.append(hints)
        spans = hints.segments or (clip.span,)
        covered = sum(span.duration for span in spans)
        text = FRENCH if covered <= self.easy_seconds else DRIFTED
        utterances = tuple(Utterance(span=span, text=text, speaker="Speaker 1") for span in spans)
        return Transcript(utterances=utterances, audio_duration=clip.duration)


class PassThroughAttributor:
    def attribute(self, transcript: Transcript, diarization: Diarization) -> Transcript:
        return transcript


class WholeClipDetector:
    def detect(self, clip: AudioClip) -> tuple[TimeSpan, ...]:
        return (TimeSpan(0.0, clip.duration),)


def _clip(seconds: float = AUDIO_SECONDS) -> AudioClip:
    return AudioClip(samples=np.zeros(int(16_000 * seconds), dtype=np.float32), sample_rate=16_000)


def _pipeline(recognizer: object, guard: DriftGuardPolicy | None) -> TranscriptionPipeline:
    return TranscriptionPipeline(
        recognizer=recognizer,  # type: ignore[arg-type]
        attributor=PassThroughAttributor(),
        detector=WholeClipDetector(),
        drift_guard=guard,
        segmentation=SegmentationPolicy(max_seconds=LONG_SEGMENT),
    )


def _request() -> MeetingRequest:
    return MeetingRequest(join_url="https://example.invalid/meeting")


def _is_probe(hints: RecognitionHints, policy: DriftGuardPolicy) -> bool:
    return len(hints.segments) == policy.probe_count and all(
        span.duration <= policy.probe_seconds for span in hints.segments
    )


def test_probe_spans_are_spread_across_the_speech():
    policy = DriftGuardPolicy()
    spans = probe_spans((TimeSpan(0.0, 300.0),), 300.0, policy)
    assert len(spans) == policy.probe_count
    starts = [span.start for span in spans]
    assert starts == sorted(starts)
    assert starts[0] < starts[-1]
    assert all(span.duration <= policy.probe_seconds for span in spans)


def test_probe_spans_skip_speech_too_short_to_carry_evidence():
    assert probe_spans((TimeSpan(0.0, 0.5),), 0.5, DriftGuardPolicy()) == ()


def test_drift_is_only_declared_when_both_verdicts_are_known_and_differ():
    assert has_drifted("fr", "en")
    assert not has_drifted("fr", "fr")
    assert not has_drifted(None, "en")
    assert not has_drifted("fr", None)


def test_a_recogniser_that_drifts_on_long_segments_is_decoded_again_on_short_ones():
    recognizer = DriftingRecognizer()
    outcome = _pipeline(recognizer, DriftGuardPolicy()).run(_clip(), _request())
    assert "Aujourd'hui" in outcome.transcript.text
    assert "Today one will pench" not in outcome.transcript.text
    assert outcome.stage_seconds["language_drift"] >= 0.0
    final = recognizer.calls[-1]
    assert max(span.duration for span in final.segments) <= SAFE_SEGMENT


def test_a_steady_recogniser_is_probed_once_and_never_decoded_again():
    recognizer = SteadyRecognizer()
    policy = DriftGuardPolicy()
    _pipeline(recognizer, policy).run(_clip(), _request())
    assert len(recognizer.calls) == 2
    assert not _is_probe(recognizer.calls[0], policy)
    assert _is_probe(recognizer.calls[1], policy)


def test_the_probe_costs_only_a_fraction_of_the_audio():
    recognizer = SteadyRecognizer()
    policy = DriftGuardPolicy()
    _pipeline(recognizer, policy).run(_clip(), _request())
    probed = sum(span.duration for span in recognizer.calls[1].segments)
    assert probed <= policy.probe_budget
    assert probed / AUDIO_SECONDS < 0.10


def test_the_guard_leaves_short_recordings_alone():
    recognizer = DriftingRecognizer()
    _pipeline(recognizer, DriftGuardPolicy()).run(_clip(seconds=30.0), _request())
    assert len(recognizer.calls) == 1


def test_segments_already_short_enough_are_never_decoded_again():
    recognizer = DriftingRecognizer()
    pipeline = TranscriptionPipeline(
        recognizer=recognizer,
        attributor=PassThroughAttributor(),
        detector=WholeClipDetector(),
        drift_guard=DriftGuardPolicy(),
        segmentation=SegmentationPolicy(max_seconds=SAFE_SEGMENT),
    )
    outcome = pipeline.run(_clip(), _request())
    assert "Aujourd'hui" in outcome.transcript.text
    assert len([call for call in recognizer.calls if not _is_probe(call, DriftGuardPolicy())]) == 1


def test_the_guard_stops_at_the_lowest_rung_when_nothing_recovers():
    policy = DriftGuardPolicy()
    recognizer = HardPassageRecognizer()
    _pipeline(recognizer, policy).run(_clip(), _request())
    decodes = [call for call in recognizer.calls if not _is_probe(call, policy)]
    assert len(decodes) == 1 + len(policy.rungs_below(LONG_SEGMENT))
    assert max(span.duration for span in decodes[-1].segments) == pytest.approx(
        policy.safe_segment_seconds, abs=0.5
    )


def test_the_guard_cannot_fire_when_the_probe_drifts_too():
    policy = DriftGuardPolicy()
    recognizer = DriftingRecognizer(drifts_above=0.0)
    _pipeline(recognizer, policy).run(_clip(), _request())
    decodes = [call for call in recognizer.calls if not _is_probe(call, policy)]
    assert len(decodes) == 1


def test_the_guard_stops_as_soon_as_a_rung_recovers_the_language():
    recognizer = DriftingRecognizer(drifts_above=10.0)
    policy = DriftGuardPolicy()
    _pipeline(recognizer, policy).run(_clip(), _request())
    decodes = [call for call in recognizer.calls if not _is_probe(call, policy)]
    assert len(decodes) == 3
    assert max(span.duration for span in decodes[-1].segments) <= 8.0


def test_the_guard_is_off_when_no_policy_is_configured():
    recognizer = DriftingRecognizer()
    outcome = _pipeline(recognizer, None).run(_clip(), _request())
    assert len(recognizer.calls) == 1
    assert "Today one will pench" in outcome.transcript.text
    assert "language_drift" not in outcome.stage_seconds
