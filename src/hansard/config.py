from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AsrEngine = Literal["parakeet", "whisper", "qwen3", "null"]
DiarizationEngine = Literal["sherpa", "spectral", "sortformer", "pyannote", "null"]
Device = Literal["auto", "cpu", "cuda"]
MemoryProfile = Literal["default", "compact"]


class AudioSettings(BaseModel):
    sample_rate: int = 16_000
    loudness_normalisation: bool = True
    target_lufs: float = -23.0
    high_pass_hz: float = 60.0
    denoise: bool = False
    max_segment_seconds: float = 120.0
    min_segment_seconds: float = 1.0
    segment_padding_seconds: float = 0.2


class VadSettings(BaseModel):
    engine: Literal["silero", "energy", "null"] = "silero"
    model_subdirectory: str = "silero"
    threshold: float = 0.5
    min_speech_seconds: float = 0.25
    min_silence_seconds: float = 0.35
    speech_pad_seconds: float = 0.15


class AsrSettings(BaseModel):
    engine: AsrEngine = "parakeet"
    model_id: str = "nemo-parakeet-tdt-0.6b-v3"
    quantization: Literal["none", "int8"] = "none"
    device: Device = "auto"
    beam_size: int = 1
    batch_size: int = 4
    batch_seconds: float = 240.0
    language: str | None = None
    intra_op_threads: int = 0
    inter_op_threads: int = 0
    memory_profile: MemoryProfile = "default"


class DiarizationSettings(BaseModel):
    engine: DiarizationEngine = "sherpa"
    segmentation_model: str = "sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx"
    embedding_model: str = "nemo_en_titanet_small.onnx"
    clustering_threshold: float = 0.99
    minimum_speaker_seconds: float = 10.0
    max_speakers: int = 8
    min_speakers: int = 1
    device: Device = "auto"
    speech_coverage_refinement: bool = True
    cluster_consolidation: bool = True
    merge_similarity: float = 0.70
    maximum_turn_extension: float = 2.5


class AttributionSettings(BaseModel):
    strategy: Literal["roster", "diarization_only", "hybrid"] = "hybrid"
    min_observation_overlap: float = 0.35
    boundary_tolerance_seconds: float = 0.30
    fallback_label_prefix: str = "Speaker"


class MinutesSettings(BaseModel):
    enabled: bool = True
    engine: Literal["auto", "llm", "extractive"] = "auto"
    endpoint: str = "http://localhost:8080/v1"
    model_id: str = "qwen3-8b-instruct"
    api_key: SecretStr | None = None
    context_tokens: int = 32_768
    max_output_tokens: int = 4_096
    chunk_tokens: int = 8_192
    temperature: float = 0.2
    language: str | None = None
    include_speaking_time: bool = True
    include_citations: bool = True


class CaptureSettings(BaseModel):
    engine: Literal["browser", "file", "null"] = "browser"
    display_name: str = "Hansard Notetaker"
    announce_recording: bool = True
    announcement_text: str = (
        "This meeting is being transcribed locally by Hansard. No audio or text leaves this organisation."
    )
    join_timeout_seconds: int = 300
    lobby_timeout_seconds: int = 600
    silence_timeout_seconds: int = 600
    alone_timeout_seconds: int = 120
    max_duration_seconds: int = 4 * 3600
    headless: bool = True
    ui_locale: str = "en-US"
    browser_binary: Path | None = None
    pulse_sink_name: str = "hansard_sink"
    roster_poll_seconds: float = 1.0


class SmtpSettings(BaseModel):
    host: str = "localhost"
    port: int = 25
    username: str | None = None
    password: SecretStr | None = None
    use_tls: bool = False
    start_tls: bool = True
    sender: str = "hansard@localhost"


class GraphSettings(BaseModel):
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: SecretStr | None = None
    authority: str = "https://login.microsoftonline.com"
    scope: str = "https://graph.microsoft.com/.default"
    base_url: str = "https://graph.microsoft.com/v1.0"


class DeliverySettings(BaseModel):
    default_channels: tuple[str, ...] = ("filesystem",)
    formats: tuple[str, ...] = ("markdown", "html")
    smtp: SmtpSettings = Field(default_factory=SmtpSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    webhook_url: str | None = None
    webhook_secret: SecretStr | None = None
    webhook_format: Literal["json", "message_card", "adaptive_card"] | None = None
    bot_tenant_id: str | None = None
    output_dir: Path = Path("artifacts")


class StorageSettings(BaseModel):
    backend: Literal["filesystem", "s3"] = "filesystem"
    root: Path = Path("artifacts")
    endpoint_url: str | None = None
    bucket: str | None = None
    region: str = "us-east-1"
    access_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    ca_bundle: Path | None = None
    force_path_style: bool = True
    retention_days: int = 30


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    root_path: str = ""
    api_key: SecretStr | None = None
    cors_origins: tuple[str, ...] = ()
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"


class RuntimeSettings(BaseModel):
    workspace: Path = Path("/var/lib/hansard")
    models_dir: Path = Path("/var/lib/hansard/models")
    allow_model_downloads: bool = False
    max_concurrent_meetings: int = 2
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    telemetry_enabled: bool = False

    @field_validator("telemetry_enabled")
    @classmethod
    def _forbid_telemetry(cls, value: bool) -> bool:
        if value:
            raise ValueError("Hansard never emits telemetry; this switch exists only to document that")
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HANSARD_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    audio: AudioSettings = Field(default_factory=AudioSettings)
    vad: VadSettings = Field(default_factory=VadSettings)
    asr: AsrSettings = Field(default_factory=AsrSettings)
    diarization: DiarizationSettings = Field(default_factory=DiarizationSettings)
    attribution: AttributionSettings = Field(default_factory=AttributionSettings)
    minutes: MinutesSettings = Field(default_factory=MinutesSettings)
    capture: CaptureSettings = Field(default_factory=CaptureSettings)
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)


def load_settings() -> Settings:
    return Settings()
