from __future__ import annotations

from dataclasses import dataclass

from hansard.adapters.asr.registry import build_recognizer
from hansard.adapters.attribution.fusion import WordLevelAttributor
from hansard.adapters.attribution.naming import RosterSpeakerNamer
from hansard.adapters.diarization.consolidation import EmbeddingClusterConsolidator
from hansard.adapters.diarization.refinement import SpeechCoverageRefiner
from hansard.adapters.diarization.registry import build_diarizer
from hansard.adapters.enhancement.ffmpeg_chain import FfmpegEnhancer
from hansard.adapters.enhancement.segmentation import SegmentationPolicy
from hansard.adapters.enhancement.vad import EnergyVoiceActivityDetector, SileroVoiceActivityDetector
from hansard.adapters.storage.registry import build_artifact_store
from hansard.application.pipeline import TranscriptionPipeline
from hansard.config import Settings, StorageSettings
from hansard.ports.enhancement import AudioEnhancer, VoiceActivityDetector
from hansard.ports.storage import ArtifactStore


@dataclass(frozen=True, slots=True)
class Composition:
    settings: Settings

    def enhancer(self) -> AudioEnhancer | None:
        audio = self.settings.audio
        if not audio.loudness_normalisation and not audio.denoise and audio.high_pass_hz <= 0:
            return None
        return FfmpegEnhancer(
            high_pass_hz=audio.high_pass_hz,
            target_lufs=audio.target_lufs if audio.loudness_normalisation else None,
            denoise=audio.denoise,
        )

    def diarization_enhancer(self) -> AudioEnhancer | None:
        audio = self.settings.audio
        if audio.high_pass_hz <= 0:
            return None
        return FfmpegEnhancer(high_pass_hz=audio.high_pass_hz, target_lufs=None, denoise=False)

    def detector(self) -> VoiceActivityDetector | None:
        vad = self.settings.vad
        if vad.engine == "null":
            return None
        if vad.engine == "energy":
            return EnergyVoiceActivityDetector(
                min_speech_seconds=vad.min_speech_seconds,
                min_silence_seconds=vad.min_silence_seconds,
                speech_pad_seconds=vad.speech_pad_seconds,
            )
        return SileroVoiceActivityDetector(
            model_path=str(self.settings.runtime.models_dir / vad.model_subdirectory),
            allow_download=self.settings.runtime.allow_model_downloads,
            threshold=vad.threshold,
            min_speech_seconds=vad.min_speech_seconds,
            min_silence_seconds=vad.min_silence_seconds,
            speech_pad_seconds=vad.speech_pad_seconds,
            max_speech_seconds=self.settings.audio.max_segment_seconds,
        )

    def artifact_store(self) -> ArtifactStore:
        return build_artifact_store(self._storage_settings())

    def _storage_settings(self) -> StorageSettings:
        storage = self.settings.storage
        if storage.backend != "filesystem" or storage.root.is_absolute():
            return storage
        return storage.model_copy(update={"root": self.settings.runtime.workspace / storage.root})

    def segmentation(self) -> SegmentationPolicy:
        audio = self.settings.audio
        return SegmentationPolicy(
            max_seconds=audio.max_segment_seconds,
            min_seconds=audio.min_segment_seconds,
            padding_seconds=audio.segment_padding_seconds,
        )

    def pipeline(self) -> TranscriptionPipeline:
        settings = self.settings
        diarization = settings.diarization
        return TranscriptionPipeline(
            recognizer=build_recognizer(settings.asr, settings.runtime.models_dir),
            attributor=WordLevelAttributor(
                boundary_dilation=settings.attribution.boundary_tolerance_seconds,
            ),
            enhancer=self.enhancer(),
            diarization_enhancer=self.diarization_enhancer(),
            detector=self.detector(),
            diarizer=(
                None
                if diarization.engine == "null"
                else build_diarizer(diarization, settings.runtime.models_dir)
            ),
            namer=(
                None
                if settings.attribution.strategy == "diarization_only"
                else RosterSpeakerNamer(
                    minimum_coverage=settings.attribution.min_observation_overlap,
                    fallback_prefix=settings.attribution.fallback_label_prefix,
                )
            ),
            consolidator=(
                EmbeddingClusterConsolidator(
                    models_dir=settings.runtime.models_dir,
                    embedding_model=diarization.embedding_model,
                    merge_similarity=diarization.merge_similarity,
                )
                if diarization.cluster_consolidation and diarization.engine != "null"
                else None
            ),
            refiner=(
                SpeechCoverageRefiner(maximum_extension=diarization.maximum_turn_extension)
                if diarization.speech_coverage_refinement
                else None
            ),
            segmentation=self.segmentation(),
            max_speakers=diarization.max_speakers,
            min_speakers=diarization.min_speakers,
        )
