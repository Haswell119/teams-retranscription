from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hansard.adapters.language.identification import UtteranceLanguageTagger
from hansard.domain.language import MIXED, normalise_tag
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.transcript import Transcript
from hansard.evaluation.datasets import load_reference_json
from hansard.evaluation.formats.subtitles import load_subtitles
from hansard.evaluation.metrics.decomposition import Decomposition, decompose
from hansard.evaluation.metrics.language import language_identification, reference_language_at
from hansard.evaluation.metrics.quiet import QuietSpeakerReport, quiet_speaker_report
from hansard.evaluation.metrics.speaker import (
    concatenated_minimum_permutation_wer,
    time_constrained_cpwer,
    word_diarization_error_rate,
)
from hansard.evaluation.metrics.text import word_error_rate
from hansard.evaluation.normalizers import NORMALIZER_VERSION, TextNormalizer, normalizer_for

COMPARISON_VERSION = "hansard-comparison-1.1.0"
SUBTITLE_SUFFIXES = frozenset({".vtt", ".srt"})


@dataclass(frozen=True, slots=True)
class LanguageSlice:
    language: str
    reference_words: int
    hypothesis_words: int
    wer: float
    cer: float
    decomposition: Decomposition | None = None


@dataclass(frozen=True, slots=True)
class SystemScore:
    name: str
    reference_words: int
    hypothesis_words: int
    wer: float
    cer: float
    cpwer: float
    tcpwer: float
    wder: float
    language_accuracy: float
    detected_languages: tuple[str, ...]
    by_language: tuple[LanguageSlice, ...]
    decomposition: Decomposition
    speakers: QuietSpeakerReport | None = None

    def slice_for(self, language: str) -> LanguageSlice | None:
        return next((item for item in self.by_language if item.language == language), None)


@dataclass(frozen=True, slots=True)
class Comparison:
    meeting: str
    reference_languages: tuple[str, ...]
    scores: tuple[SystemScore, ...]

    @property
    def best(self) -> SystemScore | None:
        return min(self.scores, key=lambda score: score.wer) if self.scores else None

    def score_for(self, name: str) -> SystemScore | None:
        return next((score for score in self.scores if score.name == name), None)


def load_transcript(path: Path, language: str | None = None) -> Transcript:
    suffix = path.suffix.lower()
    if suffix in SUBTITLE_SUFFIXES:
        return load_subtitles(path, language)
    if suffix == ".json":
        return _from_json(path, language)
    raise ValueError(f"unsupported transcript format {suffix or path.name}; expected .vtt, .srt or .json")


def _from_json(path: Path, language: str | None) -> Transcript:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and "transcript" in payload:
        return _from_export(payload["transcript"])
    return load_reference_json(path, language or "en", path.stem).reference


def _from_export(payload: object) -> Transcript:
    if not isinstance(payload, Mapping):
        raise ValueError("transcript payload must be an object")
    record = {
        "language": payload.get("language"),
        "duration": payload.get("audio_duration_seconds") or 0.0,
        "segments": payload.get("utterances") or [],
    }
    from hansard.evaluation.datasets import sample_from_record

    return sample_from_record(record, source="export", index=0).reference


def _restricted(transcript: Transcript, reference: Transcript, language: str) -> Transcript:
    kept = tuple(
        utterance
        for utterance in transcript.utterances
        if reference_language_at(reference, utterance.span) == language
    )
    return Transcript(utterances=kept, language=language, audio_duration=transcript.audio_duration)


def _reference_in(reference: Transcript, language: str) -> Transcript:
    kept = tuple(
        utterance for utterance in reference.utterances if normalise_tag(utterance.language) == language
    )
    return Transcript(utterances=kept, language=language, audio_duration=reference.audio_duration)


def reference_languages(reference: Transcript) -> tuple[str, ...]:
    return reference.language_profile.significant


def tagged_for_scoring(transcript: Transcript) -> Transcript:
    if transcript.language_profile.significant:
        return transcript
    return UtteranceLanguageTagger().tag(transcript)


def transcript_diarization(transcript: Transcript) -> Diarization:
    turns = tuple(
        SpeakerTurn(span=utterance.span, label=utterance.speaker)
        for utterance in transcript.utterances
        if utterance.span.duration > 0.0
    )
    return Diarization(turns=turns, labels=tuple(dict.fromkeys(turn.label for turn in turns)))


def _scoring_language(reference: Transcript) -> str:
    tag = reference.language_profile.tag
    return "fr" if tag in (None, MIXED) else str(tag)


def score_system(
    name: str,
    hypothesis: Transcript,
    reference: Transcript,
    normalizer: TextNormalizer | None = None,
    glossary: Sequence[str] = (),
) -> SystemScore:
    scoring = normalizer or normalizer_for(reference.language_profile.tag or MIXED)
    scored_hypothesis = tagged_for_scoring(hypothesis)
    overall = word_error_rate(reference.text, hypothesis.text, scoring)
    identified = language_identification(scored_hypothesis, reference)
    slices: list[LanguageSlice] = []
    for language in reference_languages(reference):
        expected = _reference_in(reference, language)
        observed = _restricted(hypothesis, reference, language)
        language_normalizer = normalizer_for(language)
        scored = word_error_rate(expected.text, observed.text, language_normalizer)
        slices.append(
            LanguageSlice(
                language=language,
                reference_words=expected.word_count,
                hypothesis_words=observed.word_count,
                wer=scored.wer,
                cer=scored.cer,
                decomposition=decompose(
                    language_normalizer.normalize(expected.text),
                    language_normalizer.normalize(observed.text),
                    language,
                    expected.text,
                    glossary,
                ),
            )
        )
    return SystemScore(
        name=name,
        reference_words=reference.word_count,
        hypothesis_words=hypothesis.word_count,
        wer=overall.wer,
        cer=overall.cer,
        cpwer=concatenated_minimum_permutation_wer(reference, hypothesis, scoring).wer,
        tcpwer=time_constrained_cpwer(reference, hypothesis, scoring, collar=5.0).wer,
        wder=word_diarization_error_rate(reference, hypothesis, scoring),
        language_accuracy=identified.accuracy,
        detected_languages=scored_hypothesis.language_profile.significant,
        by_language=tuple(slices),
        decomposition=decompose(
            scoring.normalize(reference.text),
            scoring.normalize(hypothesis.text),
            _scoring_language(reference),
            reference.text,
            glossary,
        ),
        speakers=quiet_speaker_report(
            reference,
            hypothesis,
            transcript_diarization(reference),
            transcript_diarization(hypothesis),
            scoring,
        ),
    )


def compare(
    meeting: str,
    reference: Transcript,
    systems: Sequence[tuple[str, Transcript]],
    glossary: Sequence[str] = (),
) -> Comparison:
    normalizer = normalizer_for(reference.language_profile.tag or MIXED)
    return Comparison(
        meeting=meeting,
        reference_languages=reference_languages(reference),
        scores=tuple(
            score_system(name, hypothesis, reference, normalizer, glossary) for name, hypothesis in systems
        ),
    )


def _percent(value: float) -> float:
    return round(value * 100, 2)


def comparison_payload(comparison: Comparison) -> dict[str, object]:
    return {
        "benchmark": "comparison",
        "comparison_version": COMPARISON_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "meeting": comparison.meeting,
        "reference_languages": list(comparison.reference_languages),
        "systems": [
            {
                "system": score.name,
                "reference_words": score.reference_words,
                "hypothesis_words": score.hypothesis_words,
                "wer_percent": _percent(score.wer),
                "cer_percent": _percent(score.cer),
                "cpwer_percent": _percent(score.cpwer),
                "tcpwer_percent": _percent(score.tcpwer),
                "wder_percent": _percent(score.wder),
                "language_accuracy_percent": _percent(score.language_accuracy),
                "detected_languages": list(score.detected_languages),
                "by_language": [
                    {
                        "language": item.language,
                        "reference_words": item.reference_words,
                        "hypothesis_words": item.hypothesis_words,
                        "wer_percent": _percent(item.wer),
                        "cer_percent": _percent(item.cer),
                        "decomposition": item.decomposition.as_dict()
                        if item.decomposition is not None
                        else None,
                    }
                    for item in score.by_language
                ],
                "decomposition": score.decomposition.as_dict(),
                "speakers": score.speakers.as_dict() if score.speakers is not None else None,
            }
            for score in comparison.scores
        ],
    }


def comparison_markdown(comparison: Comparison) -> str:
    languages = comparison.reference_languages
    header = ["| System | WER | cpWER | WDER | Language accuracy | Languages detected |"]
    header.append("| --- | ---: | ---: | ---: | ---: | --- |")
    for score in comparison.scores:
        header.append(
            f"| {score.name} | {_percent(score.wer):.2f} % | {_percent(score.cpwer):.2f} % | "
            f"{_percent(score.wder):.2f} % | {_percent(score.language_accuracy):.2f} % | "
            f"{', '.join(score.detected_languages) or 'none'} |"
        )
    lines = [f"# Comparison — {comparison.meeting}", "", *header]
    if len(languages) > 1:
        lines.extend(["", "## Word error rate by language spoken", ""])
        lines.append(f"| System | {' | '.join(languages)} |")
        lines.append(f"| --- | {' | '.join('---:' for _ in languages)} |")
        for score in comparison.scores:
            cells = []
            for language in languages:
                item = score.slice_for(language)
                cells.append(f"{_percent(item.wer):.2f} %" if item is not None else "n/a")
            lines.append(f"| {score.name} | {' | '.join(cells)} |")
    return "\n".join(lines) + "\n"
