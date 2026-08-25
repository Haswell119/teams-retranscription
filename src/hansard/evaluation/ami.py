from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word

NITE_NAMESPACE = "{http://nite.sourceforge.net/}"
NON_LEXICAL = re.compile(r"^(vocalsound|gap|disfmarker|pause|nonvocalsound|other)$", re.IGNORECASE)
SPEAKER_CODES = ("A", "B", "C", "D", "E")


@dataclass(frozen=True, slots=True)
class AmiMeeting:
    identifier: str
    audio_path: Path
    reference: Transcript
    diarization: Diarization

    @property
    def speaker_count(self) -> int:
        return len({turn.label for turn in self.diarization.turns})


def _is_lexical(element: ElementTree.Element) -> bool:
    if element.get("punc") == "true":
        return False
    text = (element.text or "").strip()
    if not text:
        return False
    return not NON_LEXICAL.match(element.tag)


def _read_words(path: Path, speaker: str) -> list[Word]:
    root = ElementTree.parse(path).getroot()
    words: list[Word] = []
    for element in root:
        if not _is_lexical(element):
            continue
        start = element.get("starttime")
        end = element.get("endtime")
        if start is None or end is None:
            continue
        begins = float(start)
        finishes = max(float(end), begins)
        words.append(
            Word(text=(element.text or "").strip(), span=TimeSpan(begins, finishes), speaker=speaker)
        )
    return words


def _read_segments(path: Path, speaker: str) -> list[SpeakerTurn]:
    root = ElementTree.parse(path).getroot()
    turns: list[SpeakerTurn] = []
    for element in root:
        start = element.get("transcriber_start") or element.get("starttime")
        end = element.get("transcriber_end") or element.get("endtime")
        if start is None or end is None:
            continue
        begins, finishes = float(start), float(end)
        if finishes > begins:
            turns.append(SpeakerTurn(TimeSpan(begins, finishes), speaker))
    return turns


def _group_into_utterances(words: list[Word], maximum_gap: float) -> list[Utterance]:
    if not words:
        return []
    ordered = sorted(words, key=lambda word: word.span.start)
    groups: list[list[Word]] = [[ordered[0]]]
    for word in ordered[1:]:
        if word.span.start - groups[-1][-1].span.end > maximum_gap:
            groups.append([word])
        else:
            groups[-1].append(word)
    return [
        Utterance(
            span=TimeSpan(group[0].span.start, group[-1].span.end),
            text=" ".join(item.text for item in group),
            speaker=group[0].speaker,
            language="en",
            words=tuple(group),
        )
        for group in groups
    ]


def load_meeting(
    identifier: str,
    audio_path: Path,
    annotations: Path,
    utterance_gap: float = 1.0,
) -> AmiMeeting:
    words: list[Word] = []
    turns: list[SpeakerTurn] = []
    utterances: list[Utterance] = []
    for code in SPEAKER_CODES:
        word_file = annotations / "words" / f"{identifier}.{code}.words.xml"
        if word_file.exists():
            spoken = _read_words(word_file, code)
            words.extend(spoken)
            utterances.extend(_group_into_utterances(spoken, utterance_gap))
        segment_file = annotations / "segments" / f"{identifier}.{code}.segments.xml"
        if segment_file.exists():
            turns.extend(_read_segments(segment_file, code))
    utterances.sort(key=lambda utterance: utterance.span.start)
    duration = max((word.span.end for word in words), default=0.0)
    turns.sort(key=lambda turn: turn.span.start)
    labels = tuple(dict.fromkeys(turn.label for turn in turns))
    return AmiMeeting(
        identifier=identifier,
        audio_path=audio_path,
        reference=Transcript(utterances=tuple(utterances), language="en", audio_duration=duration),
        diarization=Diarization(turns=tuple(turns), labels=labels),
    )


def discover_meetings(audio_root: Path, annotations: Path) -> tuple[AmiMeeting, ...]:
    meetings: list[AmiMeeting] = []
    for audio in sorted(audio_root.glob("*.Mix-Headset.wav")):
        identifier = audio.name.split(".")[0]
        if (annotations / "words" / f"{identifier}.A.words.xml").exists():
            meetings.append(load_meeting(identifier, audio, annotations))
    return tuple(meetings)
