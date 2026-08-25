from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

import pytest

from hansard.domain.speakers import UNKNOWN_SPEAKER
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word
from hansard.rendering.composition import (
    CueLayout,
    compose_minutes_document,
    compose_transcript_document,
    format_human_duration,
    format_moment,
    format_percentage,
    group_lines_into_cues,
    speaker_blocks,
    speaking_shares,
    subtitle_cues,
    wrap_caption_lines,
)
from hansard.rendering.i18n import ENGLISH, FRENCH, translations_for

LAYOUT = CueLayout()


def _utterance(start, end, text, speaker="Speaker A", words=()):
    return Utterance(span=TimeSpan(start, end), text=text, speaker=speaker, words=words)


def test_speaker_blocks_merge_contiguous_turns(context):
    transcript = Transcript(
        utterances=(
            _utterance(0.0, 2.0, "First part."),
            _utterance(2.4, 4.0, "Second part."),
            _utterance(4.2, 6.0, "Other voice.", speaker="Speaker B"),
        )
    )
    blocks = speaker_blocks(transcript, ENGLISH)
    assert [block.speaker for block in blocks] == ["Speaker A", "Speaker B"]
    assert blocks[0].text == "First part. Second part."
    assert blocks[0].timecode == "00:00:00"


def test_speaker_blocks_drop_empty_text_and_name_unknown_speakers():
    transcript = Transcript(
        utterances=(
            _utterance(0.0, 1.0, "   ", speaker=UNKNOWN_SPEAKER),
            _utterance(1.0, 2.0, "Audible again.", speaker=UNKNOWN_SPEAKER),
        )
    )
    blocks = speaker_blocks(transcript, FRENCH)
    assert len(blocks) == 1
    assert blocks[0].speaker == "Intervenant non identifié"


def test_speaking_shares_are_ordered_and_normalised():
    shares = speaking_shares((("B", 25.0), ("A", 75.0)))
    assert [share.speaker for share in shares] == ["A", "B"]
    assert shares[0].share == pytest.approx(0.75)
    assert sum(share.share for share in shares) == pytest.approx(1.0)


def test_speaking_shares_tolerate_zero_total():
    shares = speaking_shares((("A", 0.0),))
    assert shares[0].share == 0.0


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, "0 s"), (45.0, "45 s"), (60.0, "1 min"), (95.0, "1 min 35 s"), (3725.0, "1 h 2 min 5 s")],
)
def test_format_human_duration(seconds, expected):
    assert format_human_duration(seconds, ENGLISH) == expected


def test_format_percentage_follows_locale_typography():
    assert format_percentage(0.4321, ENGLISH) == "43.2%"
    assert format_percentage(0.4321, FRENCH) == "43,2 %"


def test_format_moment_is_localised():
    moment = datetime(2026, 6, 3, 9, 30, tzinfo=UTC)
    assert format_moment(moment, "UTC", ENGLISH) == "3 June 2026 at 09:30 (UTC)"
    assert format_moment(moment, "UTC", FRENCH) == "3 juin 2026 à 09:30 (UTC)"


def test_format_moment_converts_to_requested_zone():
    moment = datetime(2026, 6, 3, 9, 30, tzinfo=UTC)
    rendered = format_moment(moment, "Europe/Paris", ENGLISH)
    assert rendered in {"3 June 2026 at 11:30 (Europe/Paris)", "3 June 2026 at 09:30 (Europe/Paris)"}


def test_format_moment_survives_unknown_timezone():
    moment = datetime(2026, 6, 3, 9, 30, tzinfo=UTC)
    assert format_moment(moment, "Mars/Olympus", ENGLISH) == "3 June 2026 at 09:30 (Mars/Olympus)"


def test_format_moment_without_date():
    assert format_moment(None, "UTC", ENGLISH) == "—"


def test_wrap_caption_lines_respects_width():
    text = "The build is green on every runner but the German locale files are unreviewed."
    lines = wrap_caption_lines(text, 42)
    assert all(len(line) <= 42 for line in lines)
    assert " ".join(lines) == text


def test_wrap_caption_lines_keeps_oversized_words_intact():
    lines = wrap_caption_lines("short " + "x" * 60, 42)
    assert lines == ("short", "x" * 60)


def test_wrap_caption_lines_of_blank_text_is_empty():
    assert wrap_caption_lines("   \n  ", 42) == ()


def test_group_lines_into_cues_chunks_by_maximum():
    assert group_lines_into_cues(["a", "b", "c"], 2) == (("a", "b"), ("c",))


def test_cues_never_overlap_and_respect_layout(transcript):
    cues = subtitle_cues(transcript, LAYOUT)
    assert cues
    assert [cue.index for cue in cues] == list(range(1, len(cues) + 1))
    for cue in cues:
        assert len(cue.lines) <= LAYOUT.max_lines
        assert all(len(line) <= LAYOUT.max_characters_per_line for line in cue.lines)
        assert cue.span.duration >= LAYOUT.minimum_duration - 1e-9
        assert cue.span.duration <= LAYOUT.maximum_duration + 1e-9
    for previous, following in pairwise(cues):
        assert following.span.start >= previous.span.end - 1e-9


def test_short_utterances_are_stretched_to_minimum_duration():
    transcript = Transcript(utterances=(_utterance(0.0, 0.2, "Yes."),))
    cues = subtitle_cues(transcript, LAYOUT)
    assert cues[0].span.duration == pytest.approx(LAYOUT.minimum_duration)


def test_dense_utterances_are_pushed_instead_of_overlapping():
    transcript = Transcript(
        utterances=tuple(_utterance(index * 0.2, index * 0.2 + 0.1, "Yes.") for index in range(5))
    )
    cues = subtitle_cues(transcript, LAYOUT)
    starts = [cue.span.start for cue in cues]
    assert starts == sorted(starts)
    for previous, following in pairwise(cues):
        assert following.span.start >= previous.span.end


def test_long_utterance_is_split_into_several_cues():
    text = " ".join(["word"] * 60)
    transcript = Transcript(utterances=(_utterance(0.0, 30.0, text),))
    cues = subtitle_cues(transcript, LAYOUT)
    assert len(cues) > 1
    assert " ".join(line for cue in cues for line in cue.lines) == text


def test_word_timings_drive_cue_boundaries():
    words = tuple(
        Word(text=f"word{index}", span=TimeSpan(float(index), float(index) + 1.0))
        for index in range(20)
    )
    text = " ".join(word.text for word in words)
    transcript = Transcript(utterances=(_utterance(0.0, 20.0, text, words=words),))
    cues = subtitle_cues(transcript, CueLayout(maximum_duration=30.0))
    assert cues[0].span.start == pytest.approx(0.0)
    assert cues[-1].span.end == pytest.approx(20.0)


def test_empty_transcript_produces_no_cues():
    assert subtitle_cues(Transcript(), LAYOUT) == ()


def test_transcript_document_metadata(context, transcript):
    document = compose_transcript_document(transcript, context, ENGLISH)
    labels = [entry.label for entry in document.metadata]
    assert labels == ["Date", "Duration", "Participants", "Language", "Produced with"]
    assert document.metadata[0].machine_value.startswith("2026-06-03T09:30")
    assert "No audio and no transcript left the organisation." in document.footer


def test_minutes_document_uses_translations(context, minutes):
    document = compose_minutes_document(minutes, context, translations_for("fr"))
    assert document.subtitle == "Compte rendu"
    assert document.actions[2].owner == "Non attribué"
    assert document.actions[2].due == "—"
    assert document.questions[0].attribution == "soulevé par Léa Fontaine"
    assert document.decisions[0].timecodes == ("00:06:11",)
    assert document.topics[0].period == "00:00:00 \u2013 00:07:00"
    assert document.speaking[0].share_label.endswith(" %")
