from __future__ import annotations

import argparse
import io
import json
import random
import tarfile
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from hansard.domain.errors import ConfigurationError
from hansard.domain.language import MIXED
from hansard.evaluation.corpora import (
    SUMM_RE_DEV_SHARDS,
    SUMM_RE_SPLITS,
    summ_re_meetings_in_split,
)

TARGET_SAMPLE_RATE = 16_000
LIBRISPEECH_DEV_CLEAN = "https://www.openslr.org/resources/12/dev-clean.tar.gz"
LIBRISPEECH_DUMMY_PARQUET = (
    "https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy/"
    "resolve/main/clean/validation-00000-of-00001.parquet"
)
FLEURS_PARQUET_INDEX = "https://huggingface.co/api/datasets/google/fleurs/parquet/{config}/test"
AMI_AUDIO = (
    "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/{meeting}/audio/{meeting}.Mix-Headset.wav"
)
AMI_ANNOTATIONS = "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip"
AMI_TEST_MEETINGS: tuple[str, ...] = ("ES2004a", "IS1009a", "TS3003a")
MLS_FRENCH_BASE = (
    "https://huggingface.co/datasets/facebook/multilingual_librispeech/resolve/main/data/mls_french/dev"
)
SUMM_RE_REVISION = "47cb4ec3437ef5497b6092b8c6d1e0b5b1d86dc0"
SUMM_RE_SHARD = (
    "https://huggingface.co/datasets/linagora/SUMM-RE/resolve/{revision}/data/dev/"
    "dev-{shard:05d}-of-{shards:05d}.parquet"
)
SUMM_RE_REPOSITORY_PATH = (
    "datasets/linagora/SUMM-RE@{revision}/data/dev/dev-{shard:05d}-of-{shards:05d}.parquet"
)
SUMM_RE_DEFAULT_MEETINGS = 1
MLS_FRENCH_SPEAKERS: tuple[str, ...] = (
    "10087_11650_000",
    "10177_10625_000",
    "12205_11650_000",
    "1591_1028_000",
    "1770_1028_000",
    "3267_1902_000",
    "4193_3103_000",
    "4724_3731_000",
    "4937_2928_000",
)


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    speaker: str
    start: float
    end: float
    text: str
    samples: np.ndarray
    language: str = "en"


@dataclass(frozen=True, slots=True)
class MeetingRecipe:
    name: str
    speakers: int
    overlap_probability: float
    seed: int
    utterances_per_speaker: int = 8
    language: str = "en"


DEFAULT_FIXTURE_LANGUAGE = "en"

MEETING_RECIPES: tuple[MeetingRecipe, ...] = (
    MeetingRecipe("meeting_3spk", 3, 0.10, 11),
    MeetingRecipe("meeting_6spk", 6, 0.18, 22),
    MeetingRecipe("meeting_9spk", 9, 0.20, 33, utterances_per_speaker=6),
)

FRENCH_MEETING_RECIPES: tuple[MeetingRecipe, ...] = (
    MeetingRecipe("meeting_fr_3spk", 3, 0.10, 11, language="fr"),
    MeetingRecipe("meeting_fr_6spk", 6, 0.18, 22, language="fr"),
    MeetingRecipe("meeting_fr_9spk", 9, 0.20, 33, utterances_per_speaker=6, language="fr"),
)

MIXED_MEETING_RECIPES: tuple[MeetingRecipe, ...] = (
    MeetingRecipe("meeting_mixed_4spk", 4, 0.12, 44, language=MIXED),
    MeetingRecipe("meeting_mixed_6spk", 6, 0.18, 55, language=MIXED),
    MeetingRecipe("meeting_mixed_8spk", 8, 0.20, 66, utterances_per_speaker=6, language=MIXED),
)


def _download(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    with urllib.request.urlopen(url, timeout=1800) as response, destination.open("wb") as handle:
        while chunk := response.read(1 << 20):
            handle.write(chunk)
    return destination


def _write_manifest(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def prepare_fleurs(output: Path, config: str, name: str, language: str, limit: int = 80) -> Path | None:
    import pyarrow.parquet as pq

    index_url = FLEURS_PARQUET_INDEX.format(config=config)
    with urllib.request.urlopen(index_url, timeout=300) as response:
        shards = json.load(response)
    if not shards:
        return None
    archive = _download(shards[0], output / f"{name}.parquet")
    table = pq.read_table(archive)
    directory = output / name
    directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for row in table.to_pylist():
        if len(records) >= limit:
            break
        payload = row.get("audio")
        raw = payload["bytes"] if isinstance(payload, dict) else payload
        if raw is None:
            continue
        samples, rate = sf.read(io.BytesIO(raw), dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        path = directory / f"{len(records):04d}.wav"
        sf.write(str(path), samples, rate)
        records.append(
            {
                "audio": str(path),
                "text": row.get("transcription") or row.get("raw_transcription"),
                "seconds": len(samples) / rate,
                "language": language,
            }
        )
    archive.unlink(missing_ok=True)
    manifest = output / f"{name}.jsonl"
    _write_manifest(manifest, records)
    return manifest


def prepare_librispeech_dummy(output: Path) -> Path:
    import pyarrow.parquet as pq

    archive = _download(LIBRISPEECH_DUMMY_PARQUET, output / "librispeech_dummy.parquet")
    table = pq.read_table(archive)
    directory = output / "librispeech_dummy"
    directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for row in table.to_pylist():
        payload = row["audio"]
        raw = payload["bytes"] if isinstance(payload, dict) else payload
        samples, rate = sf.read(io.BytesIO(raw), dtype="float32")
        path = directory / f"{len(records):04d}.wav"
        sf.write(str(path), samples, rate)
        records.append(
            {
                "audio": str(path),
                "text": row.get("text"),
                "seconds": len(samples) / rate,
                "language": "en",
            }
        )
    archive.unlink(missing_ok=True)
    manifest = output / "librispeech_dummy.jsonl"
    _write_manifest(manifest, records)
    return manifest


def prepare_librispeech_corpus(output: Path) -> Path:
    root = output / "LibriSpeech" / "dev-clean"
    if root.is_dir():
        return root
    archive = _download(LIBRISPEECH_DEV_CLEAN, output / "dev-clean.tar.gz")
    with tarfile.open(archive) as handle:
        handle.extractall(output, filter="data")
    archive.unlink(missing_ok=True)
    return root


def _collect_speakers(root: Path) -> dict[str, list[tuple[Path, str]]]:
    speakers: dict[str, list[tuple[Path, str]]] = {}
    for transcript in sorted(root.glob("*/*/*.trans.txt")):
        speaker = transcript.parts[-3]
        for line in transcript.read_text(encoding="utf-8").splitlines():
            identifier, _, text = line.partition(" ")
            audio = transcript.parent / f"{identifier}.flac"
            if audio.exists():
                speakers.setdefault(speaker, []).append((audio, text))
    return speakers


def prepare_mls_french_corpus(output: Path) -> Path:
    root = output / "mls_french"
    root.mkdir(parents=True, exist_ok=True)
    _download(f"{MLS_FRENCH_BASE}/transcripts.txt", root / "transcripts.txt")
    for bundle in MLS_FRENCH_SPEAKERS:
        marker = root / f"{bundle}.done"
        if marker.exists():
            continue
        archive = _download(f"{MLS_FRENCH_BASE}/audio/{bundle}.tar.gz", root / f"{bundle}.tar.gz")
        with tarfile.open(archive) as handle:
            handle.extractall(root, filter="data")
        archive.unlink(missing_ok=True)
        marker.touch()
    return root


def _collect_mls_speakers(root: Path) -> dict[str, list[tuple[Path, str]]]:
    audio = {path.stem: path for path in root.rglob("*.flac")}
    speakers: dict[str, list[tuple[Path, str]]] = {}
    for line in (root / "transcripts.txt").read_text(encoding="utf-8").splitlines():
        identifier, _, text = line.partition("\t")
        path = audio.get(identifier)
        if path is None or not text:
            continue
        speakers.setdefault(identifier.split("_")[0], []).append((path, text))
    return speakers


def summ_re_shard_index(
    revision: str = SUMM_RE_REVISION, shards: int = SUMM_RE_DEV_SHARDS
) -> dict[str, tuple[int, ...]]:
    import pyarrow.parquet as pq

    filesystem = _summ_re_filesystem()
    index: dict[str, list[int]] = {}
    for shard in range(shards):
        location = SUMM_RE_REPOSITORY_PATH.format(revision=revision, shard=shard, shards=shards)
        with filesystem.open(location, "rb") as handle:
            table = pq.ParquetFile(handle).read(columns=["meeting_id"])
        for identifier in dict.fromkeys(table.column("meeting_id").to_pylist()):
            index.setdefault(str(identifier), []).append(shard)
    return {identifier: tuple(found) for identifier, found in index.items()}


def _summ_re_filesystem() -> Any:
    try:
        from huggingface_hub import HfFileSystem
    except ImportError as error:
        raise ConfigurationError(
            "listing the SUMM-RE shards requires huggingface_hub; "
            "install it with pip install 'hansard[asr-onnx]'"
        ) from error
    return HfFileSystem()


def _summ_re_prepared(root: Path) -> tuple[str, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        sorted(item.name for item in root.iterdir() if item.is_dir() and (item / "mixed.wav").exists())
    )


def prepare_summ_re_corpus(
    output: Path,
    meetings: Sequence[str] | None = None,
    limit: int = SUMM_RE_DEFAULT_MEETINGS,
    split: str | None = None,
    keep_tracks: bool = False,
    revision: str = SUMM_RE_REVISION,
    shards: int = SUMM_RE_DEV_SHARDS,
) -> Path:
    import pyarrow.parquet as pq

    root = output / "summ-re"
    root.mkdir(parents=True, exist_ok=True)
    prepared = _summ_re_prepared(root)
    if meetings is None and len(summ_re_meetings_in_split(prepared, split)) >= limit:
        return root
    index = summ_re_shard_index(revision=revision, shards=shards)
    wanted = _summ_re_selection(index, meetings, limit, split)
    missing = tuple(name for name in wanted if name not in prepared)
    if not missing:
        return root
    needed = sorted({shard for name in missing for shard in index[name]})
    pending: dict[str, _SummReAccumulator] = {}
    for shard in needed:
        url = SUMM_RE_SHARD.format(revision=revision, shard=shard, shards=shards)
        archive = _download(url, output / f"summ_re_dev_{shard:05d}.parquet")
        table = pq.read_table(archive)
        identifiers = [str(value) for value in table.column("meeting_id").to_pylist()]
        for position, identifier in enumerate(identifiers):
            if identifier not in missing:
                continue
            accumulator = pending.setdefault(identifier, _SummReAccumulator(root / identifier, keep_tracks))
            accumulator.add(table.slice(position, 1).to_pylist()[0])
        del table
        archive.unlink(missing_ok=True)
        for identifier in [name for name, found in index.items() if name in pending and found[-1] == shard]:
            pending.pop(identifier).finish()
    for accumulator in pending.values():
        accumulator.finish()
    return root


def _summ_re_selection(
    index: Mapping[str, tuple[int, ...]],
    meetings: Sequence[str] | None,
    limit: int,
    split: str | None,
) -> tuple[str, ...]:
    if meetings is not None:
        unknown = tuple(name for name in meetings if name not in index)
        if unknown:
            raise ConfigurationError(f"unknown SUMM-RE meetings: {unknown}")
        return tuple(meetings)
    return summ_re_meetings_in_split(tuple(index), split)[: max(0, limit)]


@dataclass
class _SummReAccumulator:
    directory: Path
    keep_tracks: bool = False
    mixture: np.ndarray | None = None

    def add(self, row: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        speaker = str(row.get("speaker_id"))
        payload = row.get("audio")
        raw = payload["bytes"] if isinstance(payload, dict) else payload
        samples = _resampled_mono(raw)
        if self.mixture is None or len(samples) > len(self.mixture):
            grown = np.zeros(len(samples), dtype=np.float32)
            if self.mixture is not None:
                grown[: len(self.mixture)] = self.mixture
            self.mixture = grown
        self.mixture[: len(samples)] += samples
        if self.keep_tracks:
            sf.write(str(self.directory / f"{speaker}.wav"), samples, TARGET_SAMPLE_RATE, subtype="PCM_16")
        records = [_summ_re_segment(segment) for segment in row.get("segments") or []]
        kept = [record for record in records if record["text"]]
        (self.directory / f"{speaker}.json").write_text(
            json.dumps(kept, ensure_ascii=False), encoding="utf-8"
        )

    def finish(self) -> None:
        if self.mixture is None:
            return
        peak = float(np.max(np.abs(self.mixture)))
        mixture = (self.mixture / peak * 0.85).astype(np.float32) if peak > 0 else self.mixture
        sf.write(str(self.directory / "mixed.wav"), mixture, TARGET_SAMPLE_RATE, subtype="PCM_16")
        self.mixture = None


def _summ_re_segment(segment: Mapping[str, Any]) -> dict[str, Any]:
    words = [
        {
            "start": float(word["start"]),
            "end": float(word["end"]),
            "word": str(word["word"]),
        }
        for word in segment.get("words") or []
        if str(word.get("word", "")).strip()
    ]
    return {
        "start": float(segment["start"]),
        "end": float(segment["end"]),
        "text": str(segment["transcript"]).strip(),
        "words": words,
    }


def _resampled_mono(raw: Any) -> np.ndarray:
    samples, rate = sf.read(io.BytesIO(raw), dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if rate == TARGET_SAMPLE_RATE:
        return np.asarray(samples, dtype=np.float32)
    count = round(len(samples) * TARGET_SAMPLE_RATE / rate)
    source = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    target = np.linspace(0.0, 1.0, num=count, endpoint=False)
    return np.asarray(np.interp(target, source, samples), dtype=np.float32)


def merge_speaker_pools(
    pools: Mapping[str, dict[str, list[tuple[Path, str]]]],
) -> tuple[dict[str, list[tuple[Path, str]]], dict[str, str]]:
    combined: dict[str, list[tuple[Path, str]]] = {}
    languages: dict[str, str] = {}
    for language, speakers in sorted(pools.items()):
        for speaker, items in speakers.items():
            key = f"{language}-{speaker}"
            combined[key] = items
            languages[key] = language
    return combined, languages


def _balanced_sample(
    generator: random.Random,
    speakers: Mapping[str, str],
    candidates: Sequence[str],
    count: int,
) -> list[str]:
    by_language: dict[str, list[str]] = {}
    for speaker in candidates:
        by_language.setdefault(speakers.get(speaker, DEFAULT_FIXTURE_LANGUAGE), []).append(speaker)
    tags = sorted(by_language)
    for pool in by_language.values():
        generator.shuffle(pool)
    chosen: list[str] = []
    while len(chosen) < count:
        drawn = [by_language[tag].pop() for tag in tags if by_language[tag]]
        if not drawn:
            break
        chosen.extend(drawn[: count - len(chosen)])
    return chosen


def synthesise_meeting(
    recipe: MeetingRecipe,
    speakers: dict[str, list[tuple[Path, str]]],
    output: Path,
    languages: Mapping[str, str] | None = None,
) -> Path:
    generator = random.Random(recipe.seed)
    spoken = dict(languages or {})
    chosen = (
        _balanced_sample(generator, spoken, sorted(speakers), recipe.speakers)
        if recipe.language == MIXED
        else generator.sample(sorted(speakers), recipe.speakers)
    )
    pools: dict[str, list[tuple[Path, str]]] = {}
    for speaker in chosen:
        items = list(speakers[speaker])
        generator.shuffle(items)
        pools[speaker] = items[: recipe.utterances_per_speaker]
    order = [speaker for speaker in chosen for _ in pools[speaker]]
    generator.shuffle(order)
    cursors = dict.fromkeys(chosen, 0)
    timeline: list[TimelineEntry] = []
    position = 1.0
    for speaker in order:
        index = cursors[speaker]
        if index >= len(pools[speaker]):
            continue
        cursors[speaker] = index + 1
        path, text = pools[speaker][index]
        samples, rate = sf.read(str(path), dtype="float32")
        if rate != TARGET_SAMPLE_RATE:
            continue
        duration = len(samples) / TARGET_SAMPLE_RATE
        overlapping = timeline and generator.random() < recipe.overlap_probability
        start = (
            max(0.0, position - generator.uniform(0.3, min(1.0, duration * 0.4)))
            if overlapping
            else position + generator.uniform(0.15, 0.8)
        )
        timeline.append(
            TimelineEntry(
                speaker,
                start,
                start + duration,
                text,
                samples,
                spoken.get(speaker, recipe.language),
            )
        )
        position = max(position, start + duration)
    total = position + 1.0
    mixture = np.zeros(int(total * TARGET_SAMPLE_RATE) + TARGET_SAMPLE_RATE, dtype=np.float32)
    for segment in timeline:
        offset = int(segment.start * TARGET_SAMPLE_RATE)
        block = np.asarray(segment.samples, dtype=np.float32)
        mixture[offset : offset + len(block)] += block * 0.9
    peak = float(np.max(np.abs(mixture)))
    if peak > 0:
        mixture = (mixture / peak * 0.85).astype(np.float32)
    directory = output / "synthetic"
    directory.mkdir(parents=True, exist_ok=True)
    audio_path = directory / f"{recipe.name}.wav"
    sf.write(str(audio_path), mixture, TARGET_SAMPLE_RATE)
    ordered = sorted(timeline, key=lambda item: item.start)
    with (directory / f"{recipe.name}.rttm").open("w", encoding="utf-8") as handle:
        for segment in ordered:
            span = segment.end - segment.start
            handle.write(
                f"SPEAKER {recipe.name} 1 {segment.start:.3f} {span:.3f} "
                f"<NA> <NA> {segment.speaker} <NA> <NA>\n"
            )
    reference = {
        "audio": str(audio_path),
        "language": recipe.language,
        "duration": len(mixture) / TARGET_SAMPLE_RATE,
        "speakers": sorted({item.speaker for item in ordered}),
        "segments": [
            {
                "speaker": item.speaker,
                "start": round(item.start, 3),
                "end": round(item.end, 3),
                "text": item.text,
                "language": item.language,
            }
            for item in ordered
        ],
    }
    (directory / f"{recipe.name}.ref.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return audio_path


def prepare_ami(output: Path, meetings: tuple[str, ...] = AMI_TEST_MEETINGS) -> Path:
    import zipfile

    root = output / "ami"
    root.mkdir(parents=True, exist_ok=True)
    annotations = root / "annotations"
    if not (annotations / "words").is_dir():
        archive = _download(AMI_ANNOTATIONS, output / "ami_annotations.zip")
        annotations.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(annotations)
        archive.unlink(missing_ok=True)
    for meeting in meetings:
        _download(AMI_AUDIO.format(meeting=meeting), root / f"{meeting}.Mix-Headset.wav")
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hansard-prepare")
    parser.add_argument("--output", type=Path, default=Path("bench/data"))
    parser.add_argument("--skip-fleurs", action="store_true")
    parser.add_argument("--skip-meetings", action="store_true")
    parser.add_argument("--skip-french-meetings", action="store_true")
    parser.add_argument("--skip-mixed-meetings", action="store_true")
    parser.add_argument("--ami", action="store_true", help="also fetch the AMI test meetings")
    parser.add_argument("--summ-re", action="store_true", help="also fetch real French meetings from SUMM-RE")
    parser.add_argument(
        "--summ-re-meetings",
        type=int,
        default=SUMM_RE_DEFAULT_MEETINGS,
        help="how many SUMM-RE meetings to prepare",
    )
    parser.add_argument(
        "--summ-re-split",
        choices=SUMM_RE_SPLITS,
        default=None,
        help="restrict the SUMM-RE selection to one deterministic split",
    )
    parser.add_argument(
        "--summ-re-tracks",
        action="store_true",
        help="also keep the per-speaker SUMM-RE tracks, for diagnostics only",
    )
    arguments = parser.parse_args(argv)
    output = arguments.output
    output.mkdir(parents=True, exist_ok=True)

    manifest = prepare_librispeech_dummy(output)
    print(f"librispeech_dummy -> {manifest}")

    if not arguments.skip_fleurs:
        for config, name, language in (("fr_fr", "fleurs_fr", "fr"), ("en_us", "fleurs_en", "en")):
            try:
                path = prepare_fleurs(output, config, name, language)
                print(f"{name} -> {path}")
            except Exception as error:
                print(f"{name} failed: {type(error).__name__}: {error}")

    if arguments.ami:
        try:
            root = prepare_ami(output)
            print(f"ami -> {root}")
        except Exception as error:
            print(f"ami failed: {type(error).__name__}: {error}")

    if arguments.summ_re:
        try:
            root = prepare_summ_re_corpus(
                output,
                limit=arguments.summ_re_meetings,
                split=arguments.summ_re_split,
                keep_tracks=arguments.summ_re_tracks,
            )
            print(f"summ-re -> {root}")
        except Exception as error:
            print(f"summ-re failed: {type(error).__name__}: {error}")

    speakers: dict[str, list[tuple[Path, str]]] = {}
    french_speakers: dict[str, list[tuple[Path, str]]] = {}
    if not arguments.skip_meetings:
        root = prepare_librispeech_corpus(output)
        speakers = _collect_speakers(root)
        print(f"librispeech dev-clean: {len(speakers)} speakers")
        for recipe in MEETING_RECIPES:
            path = synthesise_meeting(recipe, speakers, output)
            print(f"{recipe.name} -> {path}")

    if not arguments.skip_meetings and not arguments.skip_french_meetings:
        try:
            root = prepare_mls_french_corpus(output)
            french_speakers = _collect_mls_speakers(root)
            print(f"mls french dev: {len(french_speakers)} speakers")
            for recipe in FRENCH_MEETING_RECIPES:
                path = synthesise_meeting(recipe, french_speakers, output)
                print(f"{recipe.name} -> {path}")
        except Exception as error:
            french_speakers = {}
            print(f"french meetings failed: {type(error).__name__}: {error}")

    if not arguments.skip_meetings and not arguments.skip_mixed_meetings and french_speakers:
        combined, spoken = merge_speaker_pools({"en": speakers, "fr": french_speakers})
        print(f"code-switched pool: {len(combined)} speakers")
        for recipe in MIXED_MEETING_RECIPES:
            path = synthesise_meeting(recipe, combined, output, spoken)
            print(f"{recipe.name} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
