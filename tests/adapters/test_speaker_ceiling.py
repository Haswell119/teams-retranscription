from pathlib import Path

import numpy as np

from hansard.adapters.diarization.consolidation import _agglomerate
from hansard.application.pipeline import _speaker_ceiling
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Participant, Roster


def unit(*values):
    vector = np.asarray(values, dtype=np.float32)
    return vector / float(np.linalg.norm(vector))


FAR_APART = {
    "a": unit(1.0, 0.0, 0.0),
    "b": unit(0.0, 1.0, 0.0),
    "c": unit(0.0, 0.0, 1.0),
}


def groups(mapping):
    return len(set(mapping.values()))


def test_dissimilar_clusters_survive_when_no_ceiling_applies():
    assert groups(_agglomerate(FAR_APART, 0.70)) == 3


def test_a_generous_ceiling_changes_nothing():
    assert groups(_agglomerate(FAR_APART, 0.70, 8)) == 3


def test_a_tight_ceiling_forces_merging_below_the_similarity_floor():
    assert groups(_agglomerate(FAR_APART, 0.70, 2)) == 2


def test_the_ceiling_merges_the_most_similar_pair_first():
    centroids = {"a": unit(1.0, 0.0), "b": unit(0.99, 0.14), "c": unit(0.0, 1.0)}
    merged = _agglomerate(centroids, 0.999, 2)
    assert merged["a"] == merged["b"]
    assert merged["c"] != merged["a"]


def test_similar_clusters_still_merge_on_similarity_alone():
    centroids = {"a": unit(1.0, 0.0), "b": unit(0.99, 0.14)}
    assert groups(_agglomerate(centroids, 0.70)) == 1


def request_with(**kwargs):
    return MeetingRequest(audio_path=Path("meeting.wav"), title="meeting", **kwargs)


def roster_of(count):
    return Roster(
        participants=tuple(
            Participant(identifier=f"p{index}", display_name=f"Person {index}") for index in range(count)
        )
    )


def test_an_explicit_speaker_count_wins_over_the_roster():
    assert _speaker_ceiling(request_with(speaker_count=3), roster_of(9)) == 3


def test_the_roster_size_becomes_the_ceiling():
    assert _speaker_ceiling(request_with(), roster_of(6)) == 6


def test_expected_participants_are_used_when_no_roster_arrived():
    assert _speaker_ceiling(request_with(expected_participants=("Ada", "Grace")), None) == 2


def test_nothing_known_means_no_ceiling():
    assert _speaker_ceiling(request_with(), None) is None
    assert _speaker_ceiling(request_with(), Roster()) is None


class RecordingConsolidator:
    def __init__(self):
        self.calls = 0

    @property
    def name(self):
        return "recording"

    def consolidate(self, diarization, clip, ceiling=None):
        self.calls += 1
        return diarization


class FixedDiarizer:
    def __init__(self, diarization):
        self.diarization = diarization
        self.seen = []

    @property
    def name(self):
        return "fixed"

    @property
    def max_supported_speakers(self):
        return 16

    def diarize(self, clip, request):
        self.seen.append(request)
        return self.diarization


class PassThroughAttributor:
    def attribute(self, transcript, diarization):
        return transcript


class SilentRecognizer:
    @property
    def name(self):
        return "silent"

    @property
    def profile(self):
        from hansard.ports.asr import EngineProfile

        return EngineProfile(
            name="silent",
            languages=("en",),
            emits_word_timestamps=False,
            emits_punctuation=False,
            resident_memory_mb=0,
            license_identifier="MIT",
        )

    def transcribe(self, clip, hints):
        from hansard.domain.transcript import Transcript

        return Transcript(utterances=(), language="en", audio_duration=clip.duration)


def two_speaker_diarization():
    from hansard.domain.speakers import Diarization, SpeakerTurn
    from hansard.domain.timespan import TimeSpan

    turns = (
        SpeakerTurn(TimeSpan(0.0, 30.0), "a"),
        SpeakerTurn(TimeSpan(30.0, 60.0), "b"),
    )
    return Diarization(turns=turns, labels=("a", "b"))


def run_pipeline(request):
    import numpy as np

    from hansard.application.pipeline import TranscriptionPipeline
    from hansard.domain.audio import AudioClip

    diarizer = FixedDiarizer(two_speaker_diarization())
    consolidator = RecordingConsolidator()
    pipeline = TranscriptionPipeline(
        recognizer=SilentRecognizer(),
        attributor=PassThroughAttributor(),
        diarizer=diarizer,
        consolidator=consolidator,
    )
    clip = AudioClip(samples=np.zeros(16_000, dtype=np.float32), sample_rate=16_000)
    pipeline.run(clip, request)
    return diarizer, consolidator


def test_an_asserted_count_reaches_the_diarizer_and_skips_consolidation():
    diarizer, consolidator = run_pipeline(request_with(speaker_count=2))
    assert diarizer.seen[0].known_speaker_count == 2
    assert consolidator.calls == 0


def test_without_an_assertion_consolidation_still_runs():
    diarizer, consolidator = run_pipeline(request_with())
    assert diarizer.seen[0].known_speaker_count is None
    assert consolidator.calls == 1
