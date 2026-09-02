import io
import json

import numpy as np
import soundfile as sf

from hansard.evaluation.corpora import meeting_diarization, meeting_transcript, read_meeting
from hansard.evaluation.prepare import _resampled_mono, _SummReAccumulator


def _write_summ_re_meeting(directory, rows, keep_tracks=False):
    accumulator = _SummReAccumulator(directory, keep_tracks)
    for row in rows:
        accumulator.add(row)
    accumulator.finish()


def encoded(samples, rate):
    buffer = io.BytesIO()
    sf.write(buffer, samples.astype(np.float32), rate, format="WAV", subtype="FLOAT")
    return buffer.getvalue()


def track(speaker, segments, seconds=6.0, rate=32_000):
    tone = np.sin(np.linspace(0.0, 400.0, int(seconds * rate))).astype(np.float32)
    return {
        "meeting_id": "m1",
        "speaker_id": speaker,
        "audio": {"bytes": encoded(tone, rate), "path": f"{speaker}.wav"},
        "segments": segments,
    }


def segment(start, end, transcript):
    return {"start": start, "end": end, "transcript": transcript, "words": []}


def test_resampling_lands_on_the_target_rate():
    samples = np.sin(np.linspace(0.0, 50.0, 32_000)).astype(np.float32)
    assert len(_resampled_mono(encoded(samples, 32_000))) == 16_000


def test_audio_already_at_the_target_rate_is_untouched():
    samples = np.sin(np.linspace(0.0, 50.0, 16_000)).astype(np.float32)
    assert len(_resampled_mono(encoded(samples, 16_000))) == 16_000


def test_stereo_input_is_mixed_down_to_mono():
    stereo = np.zeros((16_000, 2), dtype=np.float32)
    assert _resampled_mono(encoded(stereo, 16_000)).ndim == 1


def test_the_written_meeting_reads_back_through_the_shared_loader(tmp_path):
    _write_summ_re_meeting(
        tmp_path / "m1",
        [
            track("017", [segment(0.5, 2.0, "bonjour à toutes et à tous")]),
            track("053", [segment(2.5, 4.0, "on commence par le budget")]),
        ],
    )
    meeting = read_meeting(tmp_path / "m1")
    assert meeting.mixed_audio is not None
    assert sorted(meeting.speakers) == ["017", "053"]
    transcript = meeting_transcript(meeting)
    assert transcript.language == "fr"
    assert "budget" in transcript.text
    assert meeting_diarization(meeting).speaker_count == 2


def test_empty_transcripts_are_dropped(tmp_path):
    _write_summ_re_meeting(
        tmp_path / "m1",
        [track("017", [segment(0.5, 2.0, "   "), segment(2.5, 4.0, "d'accord")])],
    )
    records = json.loads((tmp_path / "m1" / "017.json").read_text(encoding="utf-8"))
    assert [record["text"] for record in records] == ["d'accord"]


def test_the_mixture_spans_the_longest_track(tmp_path):
    _write_summ_re_meeting(
        tmp_path / "m1",
        [
            track("017", [segment(0.0, 1.0, "oui")], seconds=4.0),
            track("053", [segment(0.0, 1.0, "non")], seconds=9.0),
        ],
    )
    info = sf.info(str(tmp_path / "m1" / "mixed.wav"))
    assert info.samplerate == 16_000
    assert round(info.duration) == 9


def test_pause_markers_never_become_words():
    from hansard.evaluation.corpora import strip_annotation

    assert strip_annotation("ensuite euh + donc voilà") == "ensuite euh donc voilà"
    assert strip_annotation("alors qui + qui + serait") == "alors qui qui serait"


def test_laughter_and_unintelligible_markers_are_dropped():
    from hansard.evaluation.corpora import strip_annotation

    assert strip_annotation("donc * enfin @ oui") == "donc enfin oui"


def test_multiword_joiners_become_spaces():
    from hansard.evaluation.corpora import strip_annotation

    assert strip_annotation("il_y a de#temps") == "il y a de temps"


def test_a_word_containing_a_marker_character_survives():
    from hansard.evaluation.corpora import strip_annotation

    assert strip_annotation("c++ et j'ai") == "c++ et j'ai"


def test_the_reader_strips_annotation_from_the_reference(tmp_path):
    _write_summ_re_meeting(
        tmp_path / "m1",
        [track("017", [segment(0.5, 2.0, "alors + on commence @ le budget")])],
    )
    meeting = read_meeting(tmp_path / "m1")
    assert meeting_transcript(meeting).text == "alors on commence le budget"


def test_an_utterance_that_is_only_annotation_is_dropped(tmp_path):
    _write_summ_re_meeting(
        tmp_path / "m1",
        [track("017", [segment(0.5, 1.0, "+ @"), segment(2.0, 3.0, "d'accord")])],
    )
    records = json.loads((tmp_path / "m1" / "017.json").read_text(encoding="utf-8"))
    meeting = read_meeting(tmp_path / "m1")
    assert len(records) == 2
    assert [item.text for item in meeting.tracks[0].utterances] == ["d'accord"]
