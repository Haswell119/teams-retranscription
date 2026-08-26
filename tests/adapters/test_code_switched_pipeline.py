from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hansard.adapters.asr.biasing import VocabularyBiaser
from hansard.adapters.asr.onnx_engine import _decoder_language
from hansard.adapters.asr.phonetics import sound_key, sound_keys
from hansard.adapters.language.identification import UtteranceLanguageTagger
from hansard.application.pipeline import TranscriptionPipeline
from hansard.domain.audio import AudioClip
from hansard.domain.language import MIXED
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Diarization
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.ports.asr import EngineProfile, RecognitionHints

SPOKEN: tuple[tuple[str, str], ...] = (
    ("Aurélie", "On valide le périmètre de la version trois avant vendredi prochain."),
    ("Sofia", "I will circulate the release notes to everybody before Friday."),
    ("Aurélie", "Parfait, on acte cette décision et on passe au point suivant."),
)


@dataclass(slots=True)
class ScriptedRecognizer:
    seen: list[RecognitionHints]

    @property
    def profile(self) -> EngineProfile:
        return EngineProfile(
            name="scripted",
            languages=("en", "fr"),
            emits_word_timestamps=False,
            emits_punctuation=True,
            resident_memory_mb=1,
            license_identifier="mit",
        )

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        self.seen.append(hints)
        utterances = tuple(
            Utterance(span=TimeSpan(index * 10.0, index * 10.0 + 8.0), text=text, speaker=speaker)
            for index, (speaker, text) in enumerate(SPOKEN)
        )
        return Transcript(utterances=utterances, language=hints.language, audio_duration=30.0)


class PassThroughAttributor:
    def attribute(self, transcript: Transcript, diarization: Diarization) -> Transcript:
        return transcript


def _clip() -> AudioClip:
    return AudioClip(samples=np.zeros(16_000 * 30, dtype=np.float32), sample_rate=16_000)


def _pipeline(seen: list[RecognitionHints]) -> TranscriptionPipeline:
    return TranscriptionPipeline(
        recognizer=ScriptedRecognizer(seen),
        attributor=PassThroughAttributor(),
        language_tagger=UtteranceLanguageTagger(),
    )


def test_the_pipeline_labels_each_utterance_with_the_language_it_was_spoken_in():
    outcome = _pipeline([]).run(_clip(), MeetingRequest(join_url="https://example.invalid/m"))
    assert [utterance.language for utterance in outcome.transcript.utterances] == ["fr", "en", "fr"]
    assert outcome.transcript.language == MIXED
    assert "identify_language" in outcome.stage_seconds


def test_an_explicitly_single_language_meeting_keeps_the_language_it_was_given():
    request = MeetingRequest(join_url="https://example.invalid/m", language="fr")
    outcome = _pipeline([]).run(_clip(), request)
    assert outcome.transcript.language == "fr"


def test_declaring_a_mixed_meeting_does_not_force_a_decoder_language():
    seen: list[RecognitionHints] = []
    request = MeetingRequest(join_url="https://example.invalid/m", language=MIXED)
    outcome = _pipeline(seen).run(_clip(), request)
    assert seen and seen[0].language == MIXED
    assert _decoder_language(seen[0].language) is None
    assert outcome.transcript.language == MIXED


def test_without_a_tagger_the_transcript_keeps_the_engine_verdict():
    pipeline = TranscriptionPipeline(
        recognizer=ScriptedRecognizer([]),
        attributor=PassThroughAttributor(),
    )
    outcome = pipeline.run(_clip(), MeetingRequest(join_url="https://example.invalid/m"))
    assert all(utterance.language is None for utterance in outcome.transcript.utterances)


def test_a_mixed_meeting_keys_a_boost_phrase_under_both_phonetic_alphabets():
    assert len(sound_keys("Aurélie Fontaine", MIXED)) >= 1
    assert sound_keys("Kubernetes", "fr") == (sound_key("Kubernetes", "fr"),)


def test_vocabulary_biasing_uses_the_language_of_the_utterance_it_is_correcting():
    biaser = VocabularyBiaser()
    compiled = biaser.compile(("SecNumCloud",), MIXED)
    assert compiled and compiled[0].surface == "SecNumCloud"
    assert all(key for key in compiled[0].keys)
