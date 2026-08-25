from __future__ import annotations

from datetime import date

from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Participant, Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word

MEETING_DATE = date(2026, 6, 3)

CAMILLE = Participant(identifier="camille", display_name="Camille Dubois", is_organizer=True)
MARC = Participant(identifier="marc", display_name="Marc Lefèvre")
SOFIA = Participant(identifier="sofia", display_name="Sofia Ben Ali")

PRIYA = Participant(identifier="priya", display_name="Priya Raman", is_organizer=True)
TOM = Participant(identifier="tom", display_name="Tom Becker")
ELENA = Participant(identifier="elena", display_name="Elena Costa")

FRENCH_TURNS: tuple[tuple[str, str], ...] = (
    (
        "Camille Dubois",
        "Bonjour à tous, merci d'être là. On a trois points ce matin : la date de lancement de la "
        "version 4.2, la campagne marketing associée et l'incident de production de jeudi dernier.",
    ),
    (
        "Marc Lefèvre",
        "Sur la date de lancement, l'intégration continue est au vert depuis mardi sur tous les "
        "exécuteurs. Il reste deux anomalies bloquantes sur le module de facturation.",
    ),
    (
        "Camille Dubois",
        "Est-ce que ces deux anomalies de facturation peuvent être corrigées avant la fin de la semaine ?",
    ),
    (
        "Marc Lefèvre",
        "Oui, j'ai déjà un correctif pour la première anomalie. La seconde dépend de l'équipe paiement "
        "mais elle est bien identifiée.",
    ),
    (
        "Camille Dubois",
        "Très bien. On part sur un lancement de la version 4.2 le 12 juin, sans la traduction allemande.",
    ),
    (
        "Sofia Ben Ali",
        "Peux-tu me confirmer le périmètre exact, Marc ? La campagne marketing doit être calée sur le "
        "périmètre réel de la version.",
    ),
    (
        "Marc Lefèvre",
        "Oui bien sûr. Je t'envoie le périmètre détaillé de la version 4.2 demain matin.",
    ),
    (
        "Sofia Ben Ali",
        "Parfait. Sur la campagne, il faut encore valider les visuels avec l'agence. Je m'en occupe "
        "cette semaine et je reviens vers vous avec les maquettes.",
    ),
    (
        "Camille Dubois",
        "Sofia, peux-tu aussi préparer le communiqué de presse pour le 10 juin ?",
    ),
    ("Sofia Ben Ali", "Oui, c'est noté, je le mets dans mon planning."),
    (
        "Camille Dubois",
        "Dernier point, l'incident de production de jeudi. Nous avons perdu vingt minutes de service "
        "sur la région Europe pendant l'heure de pointe.",
    ),
    (
        "Marc Lefèvre",
        "La cause est un dépassement de mémoire sur le nœud de transcription. On valide le passage à "
        "quatre nœuds de transcription pour absorber la charge de production.",
    ),
    (
        "Sofia Ben Ali",
        "Qui prend en charge la communication client sur cet incident de production ?",
    ),
    (
        "Camille Dubois",
        "Bonne question, on en reparle plus tard. Merci à tous, on se retrouve lundi prochain.",
    ),
)

ENGLISH_TURNS: tuple[tuple[str, str], ...] = (
    (
        "Priya Raman",
        "Morning everyone. Three items today: the database migration cutover, the on-call rotation, "
        "and the customer escalation we had on Friday.",
    ),
    (
        "Tom Becker",
        "The database migration dry run finished last night. It took four hours end to end and we "
        "lost no data during the copy.",
    ),
    (
        "Elena Costa",
        "Four hours is longer than the maintenance window we promised our enterprise customers.",
    ),
    (
        "Tom Becker",
        "It is. Most of the four hours went into rebuilding the search index after the database copy "
        "finished.",
    ),
    (
        "Priya Raman",
        "Let's go with a Saturday cutover on the twentieth, so the maintenance window covers the "
        "search index rebuild as well.",
    ),
    (
        "Elena Costa",
        "That works for me. Can you send the customer notice about the maintenance window by Friday, Tom?",
    ),
    (
        "Tom Becker",
        "Yes. I will also rerun the migration dry run with the search index rebuild disabled, to see "
        "how much time it saves.",
    ),
    (
        "Priya Raman",
        "On the on-call rotation, we agreed to move to a two week cycle starting in July.",
    ),
    (
        "Tom Becker",
        "Good. The weekly handover was exactly where the on-call engineers kept losing context.",
    ),
    (
        "Elena Costa",
        "I'll update the escalation policy page so that support knows who to page during a database "
        "incident.",
    ),
    ("Priya Raman", "Who owns the postmortem for the Friday customer escalation?"),
    (
        "Elena Costa",
        "We can settle that offline, I would rather not guess in the meeting.",
    ),
    ("Priya Raman", "Fine. Same time next week, thanks everyone."),
)


def _words(text: str, span: TimeSpan, speaker: str) -> tuple[Word, ...]:
    tokens = text.split()
    step = span.duration / len(tokens)
    return tuple(
        Word(
            text=token,
            span=TimeSpan(span.start + index * step, span.start + (index + 1) * step),
            confidence=0.94,
            speaker=speaker,
        )
        for index, token in enumerate(tokens)
    )


def _transcript(
    turns: tuple[tuple[str, str], ...],
    language: str,
    with_words: bool = False,
) -> Transcript:
    utterances: list[Utterance] = []
    cursor = 4.0
    for speaker, text in turns:
        duration = max(6.0, len(text.split()) * 0.42)
        span = TimeSpan(cursor, cursor + duration)
        utterances.append(
            Utterance(
                span=span,
                text=text,
                speaker=speaker,
                language=language,
                confidence=0.93,
                words=_words(text, span, speaker) if with_words else (),
            )
        )
        cursor = span.end + 1.4
    return Transcript(utterances=tuple(utterances), language=language, audio_duration=cursor)


def french_transcript(with_words: bool = False) -> Transcript:
    return _transcript(FRENCH_TURNS, "fr", with_words)


def english_transcript(with_words: bool = False) -> Transcript:
    return _transcript(ENGLISH_TURNS, "en", with_words)


def french_roster() -> Roster:
    return Roster(participants=(CAMILLE, MARC, SOFIA))


def english_roster() -> Roster:
    return Roster(participants=(PRIYA, TOM, ELENA))


def french_request() -> MeetingRequest:
    return MeetingRequest(
        join_url="https://teams.microsoft.com/l/meetup-join/fr",
        title="Comité de lancement 4.2",
        language="fr",
        expected_participants=("Camille Dubois", "Marc Lefèvre", "Sofia Ben Ali"),
    )


def english_request() -> MeetingRequest:
    return MeetingRequest(
        join_url="https://teams.microsoft.com/l/meetup-join/en",
        title="Weekly platform sync",
        language="en",
        expected_participants=("Priya Raman", "Tom Becker", "Elena Costa"),
    )
