from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.evaluation.metrics.quiet import (
    bucket_for,
    quiet_speaker_report,
    speech_seconds,
)


def utterance(start, end, text, speaker):
    return Utterance(span=TimeSpan(start, end), text=text, speaker=speaker)


def transcript(*utterances):
    return Transcript(utterances=tuple(utterances), language="fr")


def diarization(*turns):
    return Diarization(
        turns=tuple(SpeakerTurn(TimeSpan(start, end), label) for start, end, label in turns),
        labels=tuple(dict.fromkeys(label for _, _, label in turns)),
    )


def test_the_buckets_split_at_fifteen_seconds_one_minute_and_five_minutes():
    assert bucket_for(4.0) == "under_15s"
    assert bucket_for(15.0) == "15s_to_60s"
    assert bucket_for(59.0) == "15s_to_60s"
    assert bucket_for(61.0) == "1m_to_5m"
    assert bucket_for(3600.0) == "over_5m"


def test_speech_time_is_summed_per_speaker():
    totals = speech_seconds(diarization((0.0, 5.0, "A"), (6.0, 8.0, "A"), (9.0, 10.0, "B")))
    assert totals == {"A": 7.0, "B": 1.0}


def test_a_quiet_speaker_folded_into_a_loud_one_is_reported_as_lost():
    reference = transcript(
        utterance(0.0, 60.0, "un long discours sur le budget de cette annee", "A"),
        utterance(61.0, 65.0, "je ne suis pas d accord", "B"),
    )
    hypothesis = transcript(
        utterance(0.0, 60.0, "un long discours sur le budget de cette annee", "cluster_0"),
        utterance(61.0, 65.0, "je ne suis pas d accord", "cluster_0"),
    )
    report = quiet_speaker_report(
        reference,
        hypothesis,
        diarization((0.0, 60.0, "A"), (61.0, 65.0, "B")),
        diarization((0.0, 65.0, "cluster_0")),
    )
    quiet = next(item for item in report.speakers if item.speaker == "B")
    assert quiet.bucket == "under_15s"
    assert quiet.recall == 0.0


def test_a_speaker_kept_apart_is_reported_as_found():
    reference = transcript(
        utterance(0.0, 60.0, "le budget de cette annee est serre", "A"),
        utterance(61.0, 70.0, "je ne suis pas d accord du tout", "B"),
    )
    hypothesis = transcript(
        utterance(0.0, 60.0, "le budget de cette annee est serre", "cluster_0"),
        utterance(61.0, 70.0, "je ne suis pas d accord du tout", "cluster_1"),
    )
    report = quiet_speaker_report(
        reference,
        hypothesis,
        diarization((0.0, 60.0, "A"), (61.0, 70.0, "B")),
        diarization((0.0, 60.0, "cluster_0"), (61.0, 70.0, "cluster_1")),
    )
    quiet = next(item for item in report.speakers if item.speaker == "B")
    assert quiet.matched == "cluster_1"
    assert quiet.recall == 1.0
    assert quiet.wer == 0.0


def test_buckets_aggregate_speaker_recall():
    reference = transcript(
        utterance(0.0, 400.0, "un tres long expose sur les chiffres", "A"),
        utterance(401.0, 405.0, "oui tout a fait", "B"),
        utterance(406.0, 410.0, "non pas du tout", "C"),
    )
    hypothesis = transcript(
        utterance(0.0, 400.0, "un tres long expose sur les chiffres", "cluster_0"),
        utterance(401.0, 405.0, "oui tout a fait", "cluster_1"),
        utterance(406.0, 410.0, "non pas du tout", "cluster_0"),
    )
    report = quiet_speaker_report(
        reference,
        hypothesis,
        diarization((0.0, 400.0, "A"), (401.0, 405.0, "B"), (406.0, 410.0, "C")),
        diarization((0.0, 400.0, "cluster_0"), (401.0, 405.0, "cluster_1"), (406.0, 410.0, "cluster_0")),
    )
    quiet = next(item for item in report.buckets if item.bucket == "under_15s")
    assert quiet.speakers == 2
    assert quiet.found == 1
    assert quiet.speaker_recall == 0.5
    loud = next(item for item in report.buckets if item.bucket == "over_5m")
    assert loud.speakers == 1
    assert loud.speaker_recall == 1.0


def test_the_report_serialises_both_views():
    reference = transcript(utterance(0.0, 20.0, "bonjour a tous", "A"))
    hypothesis = transcript(utterance(0.0, 20.0, "bonjour a tous", "cluster_0"))
    payload = quiet_speaker_report(
        reference,
        hypothesis,
        diarization((0.0, 20.0, "A")),
        diarization((0.0, 20.0, "cluster_0")),
    ).as_dict()
    assert payload["by_speaker"][0]["speaker"] == "A"
    assert payload["by_duration"][0]["bucket"] == "15s_to_60s"
