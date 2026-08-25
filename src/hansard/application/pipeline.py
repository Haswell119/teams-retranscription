from __future__ import annotations

import time
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass, field

from hansard.adapters.diarization.refinement import SpeechCoverageRefiner
from hansard.adapters.enhancement.segmentation import SegmentationPolicy, plan_segments
from hansard.domain.audio import AudioClip
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Diarization, Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript
from hansard.ports.asr import RecognitionHints, SpeechRecognizer
from hansard.ports.diarization import DiarizationRequest, Diarizer, SpeakerAttributor, SpeakerNamer
from hansard.ports.enhancement import AudioEnhancer, VoiceActivityDetector


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
    refiner: SpeechCoverageRefiner | None = None
    segmentation: SegmentationPolicy = field(default_factory=SegmentationPolicy)
    max_speakers: int = 8
    min_speakers: int = 1

    def run(
        self,
        clip: AudioClip,
        request: MeetingRequest,
        roster: Roster | None = None,
    ) -> PipelineOutcome:
        timings: dict[str, float] = {}
        duration = clip.duration
        with _timed(timings, "enhance"):
            prepared = self.enhancer.enhance(clip) if self.enhancer else clip
        with _timed(timings, "voice_activity"):
            speech = self.detector.detect(prepared) if self.detector else ()
        segments = plan_segments(speech, self.segmentation, prepared.duration)
        hints = RecognitionHints(
            language=request.language,
            vocabulary=request.vocabulary,
            speaker_names=request.expected_participants,
            segments=segments,
        )
        with _timed(timings, "recognise"):
            transcript = self.recognizer.transcribe(prepared, hints)
        diarization = Diarization()
        if self.diarizer is not None:
            with _timed(timings, "diarise"):
                acoustic = (
                    self.diarization_enhancer.enhance(clip) if self.diarization_enhancer else clip
                )
                diarization = self.diarizer.diarize(
                    acoustic,
                    DiarizationRequest(
                        max_speakers=min(self.max_speakers, self.diarizer.max_supported_speakers),
                        min_speakers=self.min_speakers,
                        known_speaker_count=_known_speaker_count(request, roster),
                    ),
                )
        if self.refiner is not None and diarization.turns and speech:
            with _timed(timings, "refine"):
                diarization = self.refiner.refine(diarization, speech)
        with _timed(timings, "attribute"):
            attributed = self.attributor.attribute(transcript, diarization)
        names: dict[str, str] = {}
        if self.namer is not None and diarization.turns:
            with _timed(timings, "resolve_names"):
                names = self.namer.resolve_names(attributed, diarization, roster or Roster())
            attributed = attributed.renamed(names)
        return PipelineOutcome(
            transcript=attributed,
            diarization=diarization,
            speech_spans=speech,
            names=names,
            stage_seconds=timings,
            audio_duration=duration,
        )


def _known_speaker_count(request: MeetingRequest, roster: Roster | None) -> int | None:
    if roster and roster.participants:
        return len(roster.participants)
    if request.expected_participants:
        return len(request.expected_participants)
    return None


@contextmanager
def _timed(store: dict[str, float], label: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        store[label] = round(time.perf_counter() - started, 3)
