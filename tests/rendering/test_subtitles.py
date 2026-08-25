from __future__ import annotations

import re
from dataclasses import replace

from hansard.domain.speakers import UNKNOWN_SPEAKER
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.rendering.composition import CueLayout
from hansard.rendering.subtitles import SubRipRenderer, WebVttRenderer

VTT = WebVttRenderer()
SRT = SubRipRenderer()


def _timings(document, arrow):
    return [line for line in document.splitlines() if arrow in line]


def test_vtt_identity():
    assert VTT.name == "vtt"
    assert VTT.media_type == "text/vtt"
    assert VTT.file_extension == ".vtt"


def test_srt_identity():
    assert SRT.name == "srt"
    assert SRT.media_type == "application/x-subrip"
    assert SRT.file_extension == ".srt"


def test_vtt_golden(transcript, context, assert_golden):
    assert_golden("transcript.en.vtt", VTT.render_transcript(transcript, context))


def test_srt_golden(transcript, context, assert_golden):
    assert_golden("transcript.en.srt", SRT.render_transcript(transcript, context))


def test_french_vtt_golden(fr_transcript, fr_context, assert_golden):
    assert_golden("transcript.fr.vtt", VTT.render_transcript(fr_transcript, fr_context))


def test_vtt_starts_with_signature_and_title(transcript, context):
    rendered = VTT.render_transcript(transcript, context)
    assert rendered.startswith("WEBVTT - Weekly platform sync\n\nNOTE\n")
    assert "No data left the organisation." in rendered


def test_vtt_uses_the_teams_voice_convention(transcript, context):
    rendered = VTT.render_transcript(transcript, context)
    assert "<v Amara Okafor>Good morning everyone, let us start with" in rendered
    assert rendered.count("</v>") == rendered.count("<v ")


def test_vtt_omits_voice_tag_for_unidentified_speakers(context):
    transcript = Transcript(
        utterances=(Utterance(span=TimeSpan(0.0, 2.0), text="Anonymous.", speaker=UNKNOWN_SPEAKER),)
    )
    rendered = VTT.render_transcript(transcript, context)
    assert "<v " not in rendered
    assert "Anonymous." in rendered


def test_vtt_escapes_markup_in_text_and_names(context):
    transcript = Transcript(
        utterances=(
            Utterance(span=TimeSpan(0.0, 2.0), text="Use A & B < C > D.", speaker="Ada <Lovelace> & Co"),
        )
    )
    rendered = VTT.render_transcript(transcript, context)
    assert "<v Ada &lt;Lovelace&gt; &amp; Co>" in rendered
    assert "Use A &amp; B &lt; C &gt; D." in rendered


def test_vtt_header_cannot_contain_a_cue_arrow(context, transcript):
    hostile = replace(context, title="Sprint --> review")
    rendered = VTT.render_transcript(transcript, hostile)
    assert rendered.splitlines()[0] == "WEBVTT - Sprint -> review"


def test_vtt_timings_are_millisecond_precise(transcript, context):
    timings = _timings(VTT.render_transcript(transcript, context), " --> ")
    assert timings[0] == "00:00:08.000 --> 00:00:14.600"
    assert all(len(line) == len("00:00:00.000 --> 00:00:00.000") for line in timings)


def test_srt_timings_use_comma_decimals(transcript, context):
    timings = _timings(SRT.render_transcript(transcript, context), " --> ")
    assert timings[0] == "00:00:08,000 --> 00:00:14,600"


def test_srt_prefixes_the_speaker_only_when_it_changes(transcript, context):
    rendered = SRT.render_transcript(transcript, context)
    assert "Amara Okafor: Good morning everyone" in rendered
    assert rendered.count("Léa Fontaine: The build is green") == 1
    assert "Léa Fontaine: seven untranslated strings" not in rendered


def test_cue_numbering_is_contiguous(transcript, context):
    blocks = SRT.render_transcript(transcript, context).strip().split("\n\n")
    assert [block.splitlines()[0] for block in blocks] == [str(n) for n in range(1, len(blocks) + 1)]


def test_layout_is_configurable(transcript, context):
    narrow = WebVttRenderer(layout=CueLayout(max_lines=1, max_characters_per_line=20))
    cues = narrow.render_transcript(transcript, context).strip().split("\n\n")[2:]
    for cue in cues:
        payload = cue.splitlines()[2:]
        assert len(payload) == 1
        assert len(re.sub(r"^<v [^>]*>|</v>$", "", payload[0])) <= 20


def test_empty_transcript_still_yields_a_valid_vtt(context):
    rendered = VTT.render_transcript(Transcript(), context)
    assert rendered.startswith("WEBVTT")
    assert " --> " not in rendered


def test_empty_transcript_yields_empty_srt(context):
    assert SRT.render_transcript(Transcript(), context) == ""


def test_cue_identifiers_can_be_disabled(transcript, context):
    rendered = WebVttRenderer(include_cue_identifiers=False).render_transcript(transcript, context)
    assert "\n\n1\n" not in rendered
