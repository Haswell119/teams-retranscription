from pathlib import Path

from hansard.evaluation.ami import load_meeting

WORDS_TEMPLATE = """<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<nite:root nite:id="M1.{code}.words" xmlns:nite="http://nite.sourceforge.net/">
{body}
</nite:root>
"""

SEGMENTS_TEMPLATE = """<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<nite:root nite:id="M1.{code}.segs" xmlns:nite="http://nite.sourceforge.net/">
{body}
</nite:root>
"""


def write_meeting(root: Path) -> Path:
    (root / "words").mkdir(parents=True)
    (root / "segments").mkdir(parents=True)
    speaker_a = "\n".join(
        [
            '   <w nite:id="a0" starttime="1.0" endtime="1.5">hello</w>',
            '   <w nite:id="a1" starttime="1.5" endtime="2.0">everyone</w>',
            '   <w nite:id="a2" starttime="2.0" endtime="2.0" punc="true">.</w>',
            '   <vocalsound nite:id="a3" starttime="2.1" endtime="2.4" type="laugh"/>',
            '   <w nite:id="a4" starttime="9.0" endtime="9.6">later</w>',
        ]
    )
    speaker_b = '   <w nite:id="b0" starttime="1.8" endtime="2.4">bonjour</w>'
    (root / "words" / "M1.A.words.xml").write_text(
        WORDS_TEMPLATE.format(code="A", body=speaker_a), encoding="utf-8"
    )
    (root / "words" / "M1.B.words.xml").write_text(
        WORDS_TEMPLATE.format(code="B", body=speaker_b), encoding="utf-8"
    )
    (root / "segments" / "M1.A.segments.xml").write_text(
        SEGMENTS_TEMPLATE.format(
            code="A",
            body='   <segment nite:id="s0" transcriber_start="1.0" transcriber_end="2.0"/>',
        ),
        encoding="utf-8",
    )
    (root / "segments" / "M1.B.segments.xml").write_text(
        SEGMENTS_TEMPLATE.format(
            code="B",
            body='   <segment nite:id="s1" transcriber_start="1.8" transcriber_end="2.4"/>',
        ),
        encoding="utf-8",
    )
    return root


def test_words_are_grouped_per_speaker(tmp_path):
    annotations = write_meeting(tmp_path)
    meeting = load_meeting("M1", tmp_path / "M1.wav", annotations)
    assert meeting.speaker_count == 2
    assert {utterance.speaker for utterance in meeting.reference.utterances} == {"A", "B"}


def test_punctuation_and_vocal_sounds_are_dropped(tmp_path):
    meeting = load_meeting("M1", tmp_path / "M1.wav", write_meeting(tmp_path))
    texts = " ".join(utterance.text for utterance in meeting.reference.utterances)
    assert "." not in texts
    assert "laugh" not in texts
    assert meeting.reference.word_count == 4


def test_a_long_pause_starts_a_new_utterance(tmp_path):
    meeting = load_meeting("M1", tmp_path / "M1.wav", write_meeting(tmp_path), utterance_gap=1.0)
    speaker_a = [item for item in meeting.reference.utterances if item.speaker == "A"]
    assert len(speaker_a) == 2
    assert speaker_a[0].text == "hello everyone"
    assert speaker_a[1].text == "later"


def test_overlapping_speech_is_preserved(tmp_path):
    meeting = load_meeting("M1", tmp_path / "M1.wav", write_meeting(tmp_path))
    first = next(item for item in meeting.reference.utterances if item.speaker == "A")
    second = next(item for item in meeting.reference.utterances if item.speaker == "B")
    assert first.span.intersects(second.span)


def test_diarization_turns_are_read(tmp_path):
    meeting = load_meeting("M1", tmp_path / "M1.wav", write_meeting(tmp_path))
    assert len(meeting.diarization.turns) == 2
    assert set(meeting.diarization.labels) == {"A", "B"}


def test_missing_speaker_files_are_tolerated(tmp_path):
    annotations = write_meeting(tmp_path)
    (annotations / "words" / "M1.B.words.xml").unlink()
    meeting = load_meeting("M1", tmp_path / "M1.wav", annotations)
    assert meeting.reference.speakers == ("A",)
