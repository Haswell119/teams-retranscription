from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

from hansard.adapters.diarization.consolidation import EmbeddingClusterConsolidator
from hansard.adapters.diarization.refinement import SpeechCoverageRefiner
from hansard.adapters.enhancement.segmentation import SegmentationPolicy, plan_segments
from hansard.adapters.language.identification import UtteranceLanguageTagger
from hansard.domain.audio import AudioClip
from hansard.domain.language import MIXED, normalise_tag
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Diarization, Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript
from hansard.observability.logging import StageLogger, get_logger, stage_span
from hansard.observability.metrics import (
    record_asr_failure,
    record_diarization,
    record_transcription,
)
from hansard.ports.asr import RecognitionHints, SpeechRecognizer
from hansard.ports.diarization import DiarizationRequest, Diarizer, SpeakerAttributor, SpeakerNamer
from hansard.ports.enhancement import AudioEnhancer, VoiceActivityDetector

LOGGER = get_logger(__name__)
UNKNOWN_COMPUTE = "unknown"


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    transcript: Transcript
    diarization: Diarization
    speech_spans: tuple[TimeSpan, ...]
    names: dict[str, str]
    stage_seconds: dict[str, float]
    audio_duration: float

    @property
    def real_time_factor(self) -> float:
        elapsed = sum(self.stage_seconds.values())
        return elapsed / self.audio_duration if self.audio_duration else 0.0

    @property
    def speech_ratio(self) -> float:
        covered = sum(span.duration for span in self.speech_spans)
        return covered / self.audio_duration if self.audio_duration else 0.0


@dataclass(slots=True)
class TranscriptionPipeline:
    recognizer: SpeechRecognizer
    attributor: SpeakerAttributor
    enhancer: AudioEnhancer | None = None
    diarization_enhancer: AudioEnhancer | None = None
    detector: VoiceActivityDetector | None = None
    diarizer: Diarizer | None = None
    namer: SpeakerNamer | None = None
    language_tagger: UtteranceLanguageTagger | None = None
    refiner: SpeechCoverageRefiner | None = None
    consolidator: EmbeddingClusterConsolidator | None = None
    segmentation: SegmentationPolicy = field(default_factory=SegmentationPolicy)
    max_speakers: int = 8
    min_speakers: int = 1

    def run(
        self,
        clip: AudioClip,
        request: MeetingRequest,
        roster: Roster | None = None,
    ) -> PipelineOutcome:
        logger = LOGGER.bind(meeting=request.identifier)
        timings: dict[str, float] = {}
        duration = clip.duration
        with _timed(timings, "enhance", logger):
            prepared = self.enhancer.enhance(clip) if self.enhancer else clip
        with _timed(timings, "voice_activity", logger) as measured:
            speech = self.detector.detect(prepared) if self.detector else ()
            measured["speech_spans"] = float(len(speech))
        segments = plan_segments(speech, self.segmentation, prepared.duration)
        hints = RecognitionHints(
            language=request.language,
            vocabulary=request.vocabulary,
            speaker_names=request.expected_participants,
            segments=segments,
        )
        with _timed(timings, "recognise", logger) as measured:
            transcript = self._recognise(prepared, hints)
            measured["utterances"] = float(len(transcript.utterances))
            measured["words"] = float(transcript.word_count)
        if self.language_tagger is not None:
            with _timed(timings, "identify_language", logger) as measured:
                transcript = self._tag_languages(transcript, request)
                profile = transcript.language_profile
                measured["languages"] = float(len(profile.significant))
                measured["code_switched"] = float(profile.is_mixed)
        self._record_recognition(transcript, prepared.duration, timings["recognise"], request)
        diarization = Diarization()
        acoustic = clip
        ceiling = _speaker_ceiling(request, roster)
        asserted = request.speaker_count
        if self.diarizer is not None:
            with _timed(timings, "diarise", logger) as measured:
                acoustic = self.diarization_enhancer.enhance(clip) if self.diarization_enhancer else clip
                diarization = self.diarizer.diarize(
                    acoustic,
                    DiarizationRequest(
                        max_speakers=min(self.max_speakers, self.diarizer.max_supported_speakers),
                        min_speakers=self.min_speakers,
                        known_speaker_count=asserted,
                        speaker_ceiling=ceiling,
                    ),
                )
                measured["speakers"] = float(diarization.speaker_count)
            record_diarization(diarization.speaker_count)
        if self.consolidator is not None and asserted is None and diarization.speaker_count > 1:
            with _timed(timings, "consolidate", logger) as measured:
                diarization = self.consolidator.consolidate(diarization, acoustic, ceiling)
                measured["speakers"] = float(diarization.speaker_count)
        if self.refiner is not None and diarization.turns and speech:
            with _timed(timings, "refine", logger):
                diarization = self.refiner.refine(diarization, speech)
        with _timed(timings, "attribute", logger):
            attributed = self.attributor.attribute(transcript, diarization)
        names: dict[str, str] = {}
        if self.namer is not None and diarization.turns:
            with _timed(timings, "resolve_names", logger) as measured:
                names = self.namer.resolve_names(attributed, diarization, roster or Roster())
                measured["named_speakers"] = float(len(names))
            attributed = attributed.renamed(names)
        return PipelineOutcome(
            transcript=attributed,
            diarization=diarization,
            speech_spans=speech,
            names=names,
            stage_seconds=timings,
            audio_duration=duration,
        )

    def _recognise(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        try:
            return self.recognizer.transcribe(clip, hints)
        except Exception as error:
            record_asr_failure(type(error).__name__)
            raise

    def _tag_languages(self, transcript: Transcript, request: MeetingRequest) -> Transcript:
        tagger = self.language_tagger
        if tagger is None:
            return transcript
        requested = normalise_tag(request.language)
        tagged = replace(tagger, default_language=None if requested == MIXED else requested).tag(transcript)
        return _stamped(tagged, requested)

    def _record_recognition(
        self,
        transcript: Transcript,
        audio_seconds: float,
        processing_seconds: float,
        request: MeetingRequest,
    ) -> None:
        profile = self.recognizer.profile
        metadata = profile.metadata
        record_transcription(
            model=profile.name,
            compute=metadata.get("compute_type", metadata.get("quantization", UNKNOWN_COMPUTE)),
            processing_seconds=processing_seconds,
            audio_seconds=audio_seconds,
            language=transcript.language or request.language,
        )


def _stamped(transcript: Transcript, requested: str | None) -> Transcript:
    if requested is not None and requested != MIXED:
        return replace(transcript, language=requested)
    return replace(transcript, language=transcript.language_profile.tag or transcript.language)


def _speaker_ceiling(request: MeetingRequest, roster: Roster | None) -> int | None:
    if request.speaker_count:
        return request.speaker_count
    if roster and roster.participants:
        return len(roster.participants)
    if request.expected_participants:
        return len(request.expected_participants)
    return None


@contextmanager
def _timed(store: dict[str, float], label: str, logger: StageLogger) -> Iterator[dict[str, float]]:
    started = time.perf_counter()
    try:
        with stage_span(logger, label) as measurements:
            yield measurements
    finally:
        store[label] = round(time.perf_counter() - started, 3)
