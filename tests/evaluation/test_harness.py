from pathlib import Path

import numpy as np
import pytest

from hansard.domain.audio import AudioClip
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.evaluation.datasets import EvaluationSample
from hansard.evaluation.harness import BenchmarkRunner
from hansard.ports.asr import EngineProfile

PROFILE = EngineProfile(
    name="fake-engine",
    languages=("en",),
    emits_word_timestamps=False,
    emits_punctuation=True,
    resident_memory_mb=128,
    license_identifier="Apache-2.0",
)


class StubRecognizer:
    def __init__(self, transcripts):
        self._transcripts = list(transcripts)
        self.hints = []

    @property
    def profile(self):
        return PROFILE

    def transcribe(self, clip, hints):
        self.hints.append(hints)
        return self._transcripts.pop(0)


class StubDiarizer:
    def __init__(self, diarizations):
        self._diarizations = list(diarizations)

    @property
    def name(self):
        return "fake-diarizer"

    @property
    def max_supported_speakers(self):
        return 4

    def diarize(self, clip, request):
        return self._diarizations.pop(0)


class StubAudioSource:
    def __init__(self, seconds):
        self.seconds = seconds
        self.loaded = []

    def load(self, path):
        self.loaded.append(path)
        return AudioClip(np.zeros(int(16_000 * self.seconds), dtype=np.float32), 16_000)


def sample(identifier, text, speakers=(), duration=10.0):
    if speakers:
        utterances = tuple(
            Utterance(TimeSpan(index * 5.0, index * 5.0 + 5.0), part, speaker)
            for index, (speaker, part) in enumerate(speakers)
        )
    else:
        utterances = (Utterance(TimeSpan(0.0, duration), text, "unknown"),)
    reference = Transcript(utterances=utterances, language="en", audio_duration=duration)
    return EvaluationSample(
        identifier=identifier,
        reference=reference,
        language="en",
        source="unit-test",
        audio_path=Path(f"/data/{identifier}.wav"),
        audio_seconds=duration,
    )


def test_runner_reports_word_error_rate_over_the_corpus():
    samples = [
        sample("a", "the cat sat on the mat"),
        sample("b", "dogs bark loudly"),
    ]
    hypotheses = [
        Transcript(utterances=(Utterance(TimeSpan(0.0, 10.0), "the cat sat on a mat", "unknown"),)),
        Transcript(utterances=(Utterance(TimeSpan(0.0, 10.0), "dogs bark loudly", "unknown"),)),
    ]
    runner = BenchmarkRunner(recognizer=StubRecognizer(hypotheses), audio_source=StubAudioSource(10.0))
    report = runner.run(samples, label="unit")
    assert report.engine == "fake-engine"
    assert report.corpus.reference_words == 9
    assert report.corpus.wer == pytest.approx(1 / 9)
    assert report.corpus.cpwer is None
    assert report.corpus.der is None
    assert [outcome.identifier for outcome in report.samples] == ["a", "b"]
    assert report.samples[0].wer == pytest.approx(1 / 6)
    assert report.metric_values["sample_count"] == pytest.approx(2.0)
    assert report.real_time_factor.audio_seconds == pytest.approx(20.0)


def test_runner_computes_speaker_metrics_when_diarization_is_available():
    reference = sample("meeting", "", speakers=(("Marie", "hello world"), ("Paul", "good bye now")))
    reference = EvaluationSample(
        identifier=reference.identifier,
        reference=reference.reference,
        language="en",
        source="unit-test",
        audio_path=reference.audio_path,
        reference_diarization=Diarization(
            turns=(
                SpeakerTurn(TimeSpan(0.0, 5.0), "Marie"),
                SpeakerTurn(TimeSpan(5.0, 10.0), "Paul"),
            ),
            labels=("Marie", "Paul"),
        ),
        audio_seconds=10.0,
    )
    hypothesis = Transcript(
        utterances=(
            Utterance(TimeSpan(0.0, 5.0), "hello world good", "S1"),
            Utterance(TimeSpan(5.0, 10.0), "bye now", "S2"),
        )
    )
    diarization = Diarization(
        turns=(SpeakerTurn(TimeSpan(0.0, 6.0), "S1"), SpeakerTurn(TimeSpan(6.0, 10.0), "S2")),
        labels=("S1", "S2"),
    )
    runner = BenchmarkRunner(
        recognizer=StubRecognizer([hypothesis]),
        audio_source=StubAudioSource(10.0),
        diarizer=StubDiarizer([diarization]),
        collar=0.0,
    )
    report = runner.run([reference])
    outcome = report.samples[0]
    assert outcome.wer == pytest.approx(0.0)
    assert outcome.cpwer == pytest.approx(0.4)
    assert outcome.wder == pytest.approx(0.2)
    assert outcome.der == pytest.approx(0.1)
    assert outcome.speaker_count_error == 0
    assert report.corpus.cpwer == pytest.approx(0.4)
    assert report.corpus.der == pytest.approx(0.1)
    assert report.corpus.wder == pytest.approx(0.2)
    assert report.metric_values["speaker_count_error"] == pytest.approx(0.0)


def test_runner_passes_language_and_speaker_hints():
    reference = sample("meeting", "", speakers=(("Marie", "bonjour"), ("Paul", "salut")))
    hypothesis = Transcript(utterances=(Utterance(TimeSpan(0.0, 5.0), "bonjour salut", "S1"),))
    recognizer = StubRecognizer([hypothesis])
    audio_source = StubAudioSource(10.0)
    BenchmarkRunner(recognizer=recognizer, audio_source=audio_source).run([reference])
    assert recognizer.hints[0].language == "en"
    assert recognizer.hints[0].speaker_names == ("Marie", "Paul")
    assert audio_source.loaded == [Path("/data/meeting.wav")]


def test_runner_rejects_samples_without_audio():
    reference = EvaluationSample(
        identifier="no-audio",
        reference=Transcript(),
        language="en",
        source="unit-test",
    )
    runner = BenchmarkRunner(recognizer=StubRecognizer([]), audio_source=StubAudioSource(1.0))
    with pytest.raises(ValueError, match="no audio path"):
        runner.run([reference])


def french_sample(identifier, text, duration=10.0):
    reference = Transcript(
        utterances=(Utterance(TimeSpan(0.0, duration), text, "unknown"),),
        language="fr",
        audio_duration=duration,
    )
    return EvaluationSample(
        identifier=identifier,
        reference=reference,
        language="fr",
        source="fleurs_fr",
        audio_path=Path(f"/data/{identifier}.wav"),
        audio_seconds=duration,
    )


def test_runner_reports_both_languages_side_by_side():
    samples = [
        sample("en-1", "the cat sat on the mat"),
        french_sample("fr-1", "le chat est assis sur le tapis"),
    ]
    hypotheses = [
        Transcript(utterances=(Utterance(TimeSpan(0.0, 10.0), "the cat sat on a mat", "unknown"),)),
        Transcript(utterances=(Utterance(TimeSpan(0.0, 10.0), "le chat est assis sur le tapis", "unknown"),)),
    ]
    runner = BenchmarkRunner(recognizer=StubRecognizer(hypotheses), audio_source=StubAudioSource(10.0))
    report = runner.run(samples, label="bilingual")
    assert report.languages == ("en", "fr")
    assert [(item.dataset, item.language) for item in report.dataset_slices] == [
        ("fleurs_fr", "fr"),
        ("unit-test", "en"),
    ]
    assert report.metric_values_for("en")["wer"] == pytest.approx(1 / 6)
    assert report.metric_values_for("fr")["wer"] == pytest.approx(0.0)
    assert report.metric_values_for("de") is None
    assert report.normalizer_version.startswith("hansard-normalizers-")
    assert [outcome.language for outcome in report.samples] == ["en", "fr"]


def test_runner_reports_time_constrained_cpwer_for_meetings():
    reference = sample("meeting", "", speakers=(("Marie", "bonjour tout le monde"), ("Paul", "salut marie")))
    hypothesis = Transcript(
        utterances=(
            Utterance(TimeSpan(0.0, 5.0), "bonjour tout le monde", "S1"),
            Utterance(TimeSpan(200.0, 205.0), "salut marie", "S2"),
        )
    )
    runner = BenchmarkRunner(
        recognizer=StubRecognizer([hypothesis]),
        audio_source=StubAudioSource(10.0),
        time_collar=5.0,
    )
    report = runner.run([reference])
    assert report.samples[0].cpwer == pytest.approx(0.0)
    assert report.samples[0].tcpwer > 0.0
    assert report.corpus.tcpwer == report.samples[0].tcpwer
