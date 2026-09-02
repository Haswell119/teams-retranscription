import json

from hansard.evaluation.comparison import (
    compare,
    comparison_markdown,
    comparison_payload,
    load_transcript,
    transcript_diarization,
)

REFERENCE = {
    "language": "mixed",
    "utterances": [
        {
            "start": 0.0,
            "end": 4.0,
            "speaker": "Claire Dubois",
            "language": "fr",
            "text": "on doit valider le NAV avant vendredi avec Bloomberg",
        },
        {
            "start": 4.5,
            "end": 8.0,
            "speaker": "Tom Baker",
            "language": "en",
            "text": "I will check the settlement with the counterparty tomorrow",
        },
        {
            "start": 8.5,
            "end": 10.0,
            "speaker": "Yves Roche",
            "language": "fr",
            "text": "d'accord",
        },
    ],
}

TEAMS_VTT = """WEBVTT

00:00:00.000 --> 00:00:04.000
<v Claire Dubois>on doit valider le nav avant vendredi avec bloomberg</v>

00:00:04.500 --> 00:00:08.000
<v Tom Baker>I will check the settlement with the counterparty tomorrow</v>
"""


def write_reference(tmp_path):
    path = tmp_path / "truth.ref.json"
    path.write_text(json.dumps(REFERENCE), encoding="utf-8")
    return path


def test_a_teams_webvtt_export_loads_with_its_speakers(tmp_path):
    path = tmp_path / "teams.vtt"
    path.write_text(TEAMS_VTT, encoding="utf-8")
    transcript = load_transcript(path)
    assert [item.speaker for item in transcript.utterances] == ["Claire Dubois", "Tom Baker"]
    assert "bloomberg" in transcript.text


def test_the_system_that_drops_a_speaker_is_charged_for_it(tmp_path):
    reference = load_transcript(write_reference(tmp_path))
    teams = tmp_path / "teams.vtt"
    teams.write_text(TEAMS_VTT, encoding="utf-8")
    complete = load_transcript(write_reference(tmp_path))
    result = compare(
        "board",
        reference,
        [("teams", load_transcript(teams)), ("hansard", complete)],
    )
    scores = {score.name: score for score in result.scores}
    assert scores["hansard"].wer == 0.0
    assert scores["teams"].wer > 0.0
    assert scores["teams"].cpwer > scores["hansard"].cpwer


def test_the_comparison_breaks_down_by_language_spoken(tmp_path):
    reference = load_transcript(write_reference(tmp_path))
    result = compare("board", reference, [("hansard", reference)])
    assert set(result.reference_languages) == {"fr", "en"}
    assert result.scores[0].slice_for("fr") is not None
    assert result.scores[0].slice_for("en") is not None


def test_a_glossary_makes_domain_terms_scoreable(tmp_path):
    reference = load_transcript(write_reference(tmp_path))
    result = compare("board", reference, [("hansard", reference)], glossary=("NAV", "Bloomberg"))
    names = result.scores[0].decomposition.counts_for("proper_noun")
    assert names.reference_words >= 2
    assert names.recall == 1.0


def test_a_lost_domain_term_shows_up_as_a_lost_proper_noun(tmp_path):
    reference = load_transcript(write_reference(tmp_path))
    damaged = {
        "language": "mixed",
        "utterances": [
            dict(item, text=item["text"].replace("NAV", "the nav").replace("Bloomberg", "bloom bird"))
            for item in REFERENCE["utterances"]
        ],
    }
    path = tmp_path / "damaged.ref.json"
    path.write_text(json.dumps(damaged), encoding="utf-8")
    result = compare(
        "board", reference, [("hansard", load_transcript(path))], glossary=("NAV", "Bloomberg")
    )
    names = result.scores[0].decomposition.counts_for("proper_noun")
    assert names.recall < 1.0


def test_the_payload_carries_every_breakdown_the_protocol_needs(tmp_path):
    reference = load_transcript(write_reference(tmp_path))
    payload = comparison_payload(compare("board", reference, [("hansard", reference)]))
    system = payload["systems"][0]
    for key in ("wer_percent", "cer_percent", "cpwer_percent", "tcpwer_percent", "wder_percent"):
        assert key in system
    assert system["decomposition"]["categories"]
    assert system["speakers"]["by_duration"]
    assert system["by_language"][0]["decomposition"] is not None


def test_the_markdown_report_names_the_quiet_speakers(tmp_path):
    reference = load_transcript(write_reference(tmp_path))
    markdown = comparison_markdown(compare("board", reference, [("hansard", reference)]))
    assert "tcpWER@5s" in markdown
    assert "Names kept" in markdown
    assert "how long each speaker actually spoke" in markdown


def test_a_transcript_becomes_a_diarization_for_scoring(tmp_path):
    reference = load_transcript(write_reference(tmp_path))
    diarization = transcript_diarization(reference)
    assert diarization.speaker_count == 3
    assert diarization.speaking_time()["Yves Roche"] == 1.5
