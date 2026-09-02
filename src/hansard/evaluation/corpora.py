from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hansard.domain.errors import ConfigurationError
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.evaluation.formats.rttm import write_rttm

SUMM_RE_DATASET = "linagora/SUMM-RE"
SUMM_RE_LANGUAGE = "fr"
SUMM_RE_LICENSE = "CC-BY-SA-4.0"
SUMM_RE_APPROXIMATE_SIZE_GB = 93
SUMM_RE_SOURCE = "summ-re"
SUMM_RE_DEV_SHARDS = 29
SUMM_RE_TUNING_SPLIT = "tuning"
SUMM_RE_HELD_OUT_SPLIT = "held-out"
SUMM_RE_SPLITS = (SUMM_RE_TUNING_SPLIT, SUMM_RE_HELD_OUT_SPLIT)
MIXED_AUDIO_NAMES = ("mixed.wav", "mix.wav", "meeting.wav")
SUMM_RE_ANNOTATION_MARKERS: tuple[str, ...] = ("+", "@", "*")
_SUMM_RE_MARKER = re.compile(r"(?:(?<=\s)|^)[+@*](?:(?=\s)|$)")
_SUMM_RE_JOINER = re.compile(r"[#_]")
_SUMM_RE_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SpeakerTrack:
    speaker: str
    utterances: tuple[Utterance, ...]
    audio_path: Path | None = None

    @property
    def speech_duration(self) -> float:
        return sum(utterance.span.duration for utterance in self.utterances)


@dataclass(frozen=True, slots=True)
class SummReMeeting:
    identifier: str
    tracks: tuple[SpeakerTrack, ...]
    mixed_audio: Path | None = None

    @property
    def duration(self) -> float:
        return max(
            (utterance.span.end for track in self.tracks for utterance in track.utterances),
            default=0.0,
        )

    @property
    def speakers(self) -> tuple[str, ...]:
        return tuple(track.speaker for track in self.tracks)


def summ_re_split(identifier: str) -> str:
    digest = hashlib.blake2b(identifier.encode("utf-8"), digest_size=8).digest()
    return SUMM_RE_TUNING_SPLIT if digest[0] % 2 == 0 else SUMM_RE_HELD_OUT_SPLIT


def summ_re_meetings_in_split(identifiers: Sequence[str], split: str | None) -> tuple[str, ...]:
    if split is None:
        return tuple(sorted(identifiers))
    if split not in SUMM_RE_SPLITS:
        raise ConfigurationError(f"unknown SUMM-RE split {split!r}, expected one of {SUMM_RE_SPLITS}")
    return tuple(sorted(name for name in identifiers if summ_re_split(name) == split))


def strip_annotation(text: str) -> str:
    without_markers = _SUMM_RE_MARKER.sub(" ", text)
    spelled = _SUMM_RE_JOINER.sub(" ", without_markers)
    return _SUMM_RE_SPACES.sub(" ", spelled).strip()


def read_speaker_track(path: Path, speaker: str, audio_path: Path | None = None) -> SpeakerTrack:
    return SpeakerTrack(
        speaker=speaker,
        utterances=tuple(_utterances(_records(path), speaker)),
        audio_path=audio_path,
    )


def read_meeting(directory: Path) -> SummReMeeting:
    tracks = tuple(
        read_speaker_track(path, path.stem, _sibling_audio(path))
        for path in sorted(directory.glob("*.json"))
        if not path.name.endswith(".ref.json")
    )
    if not tracks:
        raise ConfigurationError(f"no per-speaker transcript found in {directory}")
    return SummReMeeting(identifier=directory.name, tracks=tracks, mixed_audio=_mixed_audio(directory))


def meeting_transcript(meeting: SummReMeeting) -> Transcript:
    utterances = sorted(
        (utterance for track in meeting.tracks for utterance in track.utterances),
        key=lambda item: (item.span.start, item.span.end, item.speaker),
    )
    return Transcript(
        utterances=tuple(utterances),
        language=SUMM_RE_LANGUAGE,
        audio_duration=meeting.duration,
    )


def meeting_diarization(meeting: SummReMeeting) -> Diarization:
    turns = sorted(
        (
            SpeakerTurn(span=utterance.span, label=track.speaker)
            for track in meeting.tracks
            for utterance in track.utterances
            if utterance.span.duration > 0.0
        ),
        key=lambda turn: (turn.span.start, turn.span.end, turn.label),
    )
    return Diarization(turns=tuple(turns), labels=tuple(sorted({turn.label for turn in turns})))


def prepare_summ_re(root: Path, rttm_directory: Path | None = None) -> tuple[SummReMeeting, ...]:
    meetings = tuple(read_meeting(directory) for directory in sorted(root.iterdir()) if directory.is_dir())
    if rttm_directory is not None:
        rttm_directory.mkdir(parents=True, exist_ok=True)
        for meeting in meetings:
            write_rttm(
                rttm_directory / f"{meeting.identifier}.rttm",
                {meeting.identifier: meeting_diarization(meeting)},
            )
    return meetings


def download_summ_re(
    destination: Path,
    revision: str = "main",
    allow_patterns: Sequence[str] | None = None,
) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise ConfigurationError(
            "downloading SUMM-RE requires huggingface_hub; install it and rerun, "
            f"or fetch {SUMM_RE_DATASET} manually (about {SUMM_RE_APPROXIMATE_SIZE_GB} GB)"
        ) from error
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=SUMM_RE_DATASET,
        repo_type="dataset",
        revision=revision,
        local_dir=str(destination),
        allow_patterns=list(allow_patterns) if allow_patterns is not None else None,
    )
    return destination


def _records(path: Path) -> list[dict[str, object]]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    if content.startswith("["):
        payload = json.loads(content)
        return [item for item in payload if isinstance(item, dict)]
    records = [json.loads(line) for line in content.splitlines() if line.strip()]
    return [item for item in records if isinstance(item, dict)]


def _utterances(records: list[dict[str, object]], speaker: str) -> list[Utterance]:
    utterances: list[Utterance] = []
    for record in records:
        start = float(str(record.get("start", 0.0)))
        end = float(str(record.get("end", start)))
        text = strip_annotation(str(record.get("text", "")))
        if not text:
            continue
        utterances.append(
            Utterance(
                span=TimeSpan(start, max(start, end)),
                text=text,
                speaker=speaker,
                language=SUMM_RE_LANGUAGE,
            )
        )
    return utterances


def _sibling_audio(path: Path) -> Path | None:
    candidate = path.with_suffix(".wav")
    return candidate if candidate.exists() else None


def _mixed_audio(directory: Path) -> Path | None:
    for name in MIXED_AUDIO_NAMES:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None
