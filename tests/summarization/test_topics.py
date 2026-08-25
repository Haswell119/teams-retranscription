from __future__ import annotations

from itertools import pairwise

from hansard.adapters.summarization.topics import TopicOptions, segment_topics
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance

FRENCH_BLOCKS: tuple[str, ...] = (
    "la livraison de la version 4.2 est prête, le pipeline d'intégration est au vert partout",
    "la traduction allemande de la facturation bloque encore la livraison de la version",
    "l'astreinte de nuit a déclenché un incident sur la réplique de la base de données",
    "la réplique de la base de données a réveillé l'astreinte deux fois pendant la nuit",
    "le budget du cluster de calcul demande deux nœuds supplémentaires et un bon de commande",
    "le bon de commande du budget cluster doit être signé par la direction financière",
)

ENGLISH_BLOCKS: tuple[str, ...] = (
    "the release build pipeline is green on every runner and the release notes are drafted",
    "the german locale files still contain untranslated billing strings for the release",
    "the on call rotation produced an incident with the database replica during the night",
    "the database replica lag alert paged the on call engineer twice during that night",
    "the budget forecast for the compute cluster needs two extra nodes and a purchase order",
    "the purchase order for the cluster budget must be signed by finance before the quarter",
)


def _blocked_transcript(blocks: tuple[str, ...], language: str, per_block: int = 8) -> Transcript:
    utterances = []
    cursor = 0.0
    for block in blocks:
        for index in range(per_block):
            utterances.append(
                Utterance(
                    span=TimeSpan(cursor, cursor + 12.0),
                    text=f"{block}, point {index}.",
                    speaker=f"S{index % 2}",
                    language=language,
                )
            )
            cursor += 13.0
    return Transcript(utterances=tuple(utterances), language=language, audio_duration=cursor)


def test_french_topic_shift_is_detected():
    transcript = _blocked_transcript(FRENCH_BLOCKS, "fr")
    segments = segment_topics(transcript, "fr", TopicOptions(minimum_duration=60.0))
    assert len(segments) >= 3
    assert segments[0].first_utterance == 0
    assert segments[-1].last_utterance == len(transcript.utterances) - 1
    boundaries = [segment.first_utterance for segment in segments[1:]]
    assert any(abs(boundary - 16) <= 4 for boundary in boundaries)


def test_english_topic_shift_is_detected():
    transcript = _blocked_transcript(ENGLISH_BLOCKS, "en")
    segments = segment_topics(transcript, "en", TopicOptions(minimum_duration=60.0))
    assert len(segments) >= 3
    assert [segment.index for segment in segments] == list(range(len(segments)))


def test_segments_are_contiguous_and_ordered():
    transcript = _blocked_transcript(ENGLISH_BLOCKS, "en")
    segments = segment_topics(transcript, "en", TopicOptions(minimum_duration=60.0))
    for previous, current in pairwise(segments):
        assert current.first_utterance == previous.last_utterance + 1
        assert current.span.start >= previous.span.end


def test_minimum_duration_is_respected():
    transcript = _blocked_transcript(ENGLISH_BLOCKS, "en")
    segments = segment_topics(transcript, "en", TopicOptions(minimum_duration=200.0, adaptive=False))
    assert all(segment.span.duration >= 200.0 for segment in segments)


def test_topics_carry_keywords_from_their_own_span():
    transcript = _blocked_transcript(FRENCH_BLOCKS, "fr")
    segments = segment_topics(transcript, "fr", TopicOptions(minimum_duration=60.0))
    for segment in segments:
        assert segment.keywords
        assert segment.title
        assert segment.title[0].isupper()


def test_short_transcript_yields_a_single_topic():
    transcript = Transcript(
        utterances=(
            Utterance(span=TimeSpan(0.0, 5.0), text="Bonjour à tous, on commence.", speaker="A"),
            Utterance(span=TimeSpan(6.0, 10.0), text="Bonjour, je suis prêt.", speaker="B"),
        ),
        language="fr",
    )
    segments = segment_topics(transcript, "fr")
    assert len(segments) == 1
    assert segments[0].span.start == 0.0


def test_empty_transcript_yields_no_topic():
    assert segment_topics(Transcript()) == ()
