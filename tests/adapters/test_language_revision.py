from hansard.adapters.language.identification import UtteranceLanguageTagger
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance


def utterance(start, text, speaker="A"):
    return Utterance(span=TimeSpan(start, start + 2.0), text=text, speaker=speaker)


def tagged(*utterances, **options):
    transcript = Transcript(utterances=tuple(utterances), language="mixed")
    options.setdefault("revise_weak_verdicts", True)
    return [item.language for item in UtteranceLanguageTagger(**options).tag(transcript).utterances]


def test_a_weak_verdict_is_revised_towards_a_speakers_settled_language():
    languages = tagged(
        utterance(0.0, "je pense que nous devons revoir le budget de cette annee"),
        utterance(3.0, "the thing"),
        utterance(6.0, "il faut vraiment que nous parlions de cette question ensemble"),
    )
    assert languages == ["fr", "fr", "fr"]


def test_revision_is_off_by_default():
    languages = [
        item.language
        for item in UtteranceLanguageTagger()
        .tag(
            Transcript(
                utterances=(
                    utterance(0.0, "je pense que nous devons revoir le budget de cette annee"),
                    utterance(3.0, "the thing"),
                    utterance(6.0, "il faut vraiment que nous parlions de cette question ensemble"),
                ),
                language="mixed",
            )
        )
        .utterances
    ]
    assert languages[1] == "en"


def test_revision_is_off_when_it_is_turned_off():
    languages = tagged(
        utterance(0.0, "je pense que nous devons revoir le budget de cette annee"),
        utterance(3.0, "the thing"),
        utterance(6.0, "il faut vraiment que nous parlions de cette question ensemble"),
        revise_weak_verdicts=False,
    )
    assert languages[1] == "en"


def test_a_strong_verdict_survives_a_disagreeing_context():
    languages = tagged(
        utterance(0.0, "je pense que nous devons revoir le budget de cette annee"),
        utterance(3.0, "I really think that we should not be doing this at all today"),
        utterance(6.0, "il faut vraiment que nous parlions de cette question ensemble"),
    )
    assert languages[1] == "en"


def test_a_disagreeing_context_leaves_a_weak_verdict_alone():
    languages = tagged(
        utterance(0.0, "je pense que nous devons revoir le budget de cette annee"),
        utterance(3.0, "the thing"),
        utterance(6.0, "I really think that we should not be doing this at all today"),
    )
    assert languages[1] == "en"


def test_another_speakers_language_does_not_revise_this_one():
    languages = tagged(
        utterance(0.0, "je pense que nous devons revoir le budget de cette annee", speaker="A"),
        utterance(3.0, "the thing", speaker="B"),
        utterance(6.0, "il faut vraiment que nous parlions de cette question ensemble", speaker="A"),
    )
    assert languages[1] == "en"


def test_an_empty_transcript_is_returned_unchanged():
    assert UtteranceLanguageTagger().tag(Transcript()).utterances == ()
