from datetime import UTC, datetime
from pathlib import Path

from hansard.adapters.summarization.registry import build_minutes_writer
from hansard.config import MinutesSettings
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Participant, Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word

MEETING_DATE = datetime(2026, 6, 3, 9, 30, tzinfo=UTC)

TURNS = [
    (0.0, 8.0, "Camille Dubois", "Bonjour, on ouvre le comité de lancement de la version 4.2."),
    (8.5, 18.0, "Sofia Ben Ali", "Je m'occupe du communiqué de presse, je te l'envoie demain matin."),
    (18.5, 28.0, "Marc Lefèvre", "Je prépare le périmètre détaillé pour vendredi prochain."),
]


def transcript_of(turns):
    utterances = []
    for start, end, speaker, text in turns:
        tokens = text.split()
        step = (end - start) / max(len(tokens), 1)
        words = tuple(
            Word(token, TimeSpan(start + index * step, start + (index + 1) * step), speaker=speaker)
            for index, token in enumerate(tokens)
        )
        utterances.append(Utterance(TimeSpan(start, end), text, speaker=speaker, words=words))
    return Transcript(utterances=tuple(utterances), language="fr", audio_duration=turns[-1][1])


def compose(starts_at):
    writer = build_minutes_writer(MinutesSettings(enabled=True, engine="extractive"))
    roster = Roster(
        participants=tuple(
            Participant(identifier=name, display_name=name)
            for name in ("Camille Dubois", "Sofia Ben Ali", "Marc Lefèvre")
        )
    )
    request = MeetingRequest(
        audio_path=Path("comite.wav"),
        title="Comité de lancement",
        language="fr",
        starts_at=starts_at,
    )
    return writer.compose(transcript_of(TURNS), roster, request)


def test_relative_deadlines_resolve_against_the_meeting_date():
    minutes = compose(MEETING_DATE)
    due = {action.due_date for action in minutes.actions if action.due_date}
    assert "2026-06-04" in due


def test_deadlines_move_when_the_meeting_date_moves():
    early = {action.due_date for action in compose(MEETING_DATE).actions if action.due_date}
    later = {
        action.due_date
        for action in compose(datetime(2026, 9, 2, 9, 30, tzinfo=UTC)).actions
        if action.due_date
    }
    assert early
    assert later
    assert early != later


def test_a_meeting_without_a_date_still_produces_minutes():
    minutes = compose(None)
    assert minutes.actions
